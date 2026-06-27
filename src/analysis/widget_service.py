"""
Widget Data Service

Provides unified data fetching for all Dashboard widgets.
Integrates with TuShare, AkShare, and yFinance with caching, rate limiting, and circuit breaker.
"""

import math
import time
import threading
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional
from dataclasses import dataclass
from enum import Enum

# Import data sources
from src.data_sources.tushare_client import (
    tushare_call_with_retry,
    get_moneyflow_hsgt,
    get_moneyflow_ind_ths,
    get_moneyflow_cnt_ths,
    get_index_daily,
    get_fx_daily_tushare,
    get_latest_trade_date,
    normalize_ts_code,
    denormalize_ts_code,
)
from src.data_sources.data_source_manager import (
    get_market_indices_from_tushare,
    get_northbound_flow_from_tushare,
    get_top_money_flow_from_tushare,
)
from src.data_sources.rate_limiter import rate_limiter
from src.data_sources.circuit_breaker import circuit_breaker
from src.data_sources.utils import format_date_yyyymmdd


class WidgetType(str, Enum):
    """Widget types supported by the dashboard"""
    MARKET_INDICES = "market_indices"
    NORTHBOUND_FLOW = "northbound_flow"
    INDUSTRY_FLOW = "industry_flow"
    SECTOR_PERFORMANCE = "sector_performance"
    TOP_LIST = "top_list"
    FOREX_RATES = "forex_rates"
    MARKET_SENTIMENT = "market_sentiment"
    GOLD_MACRO = "gold_macro"
    ABNORMAL_MOVEMENTS = "abnormal_movements"
    MAIN_CAPITAL_FLOW = "main_capital_flow"
    SYSTEM_STATS = "system_stats"
    WATCHLIST = "watchlist"
    NEWS = "news"


@dataclass
class WidgetCacheConfig:
    """Cache configuration for each widget type"""
    ttl: int  # Time to live in seconds
    api_name: str  # For rate limiting and circuit breaker


# Widget cache configurations based on plan
WIDGET_CACHE_CONFIG: Dict[WidgetType, WidgetCacheConfig] = {
    WidgetType.MARKET_INDICES: WidgetCacheConfig(ttl=60, api_name="index_daily"),
    WidgetType.NORTHBOUND_FLOW: WidgetCacheConfig(ttl=300, api_name="moneyflow_hsgt"),
    WidgetType.INDUSTRY_FLOW: WidgetCacheConfig(ttl=600, api_name="moneyflow_ind_ths"),
    WidgetType.SECTOR_PERFORMANCE: WidgetCacheConfig(ttl=600, api_name="moneyflow_cnt_ths"),
    WidgetType.TOP_LIST: WidgetCacheConfig(ttl=3600, api_name="top_list"),
    WidgetType.FOREX_RATES: WidgetCacheConfig(ttl=3600, api_name="fx_daily"),
    WidgetType.MARKET_SENTIMENT: WidgetCacheConfig(ttl=60, api_name="market_sentiment"),
    WidgetType.GOLD_MACRO: WidgetCacheConfig(ttl=300, api_name="gold_macro"),
    WidgetType.ABNORMAL_MOVEMENTS: WidgetCacheConfig(ttl=30, api_name="abnormal"),
    WidgetType.MAIN_CAPITAL_FLOW: WidgetCacheConfig(ttl=300, api_name="main_flow"),
    WidgetType.SYSTEM_STATS: WidgetCacheConfig(ttl=300, api_name="system_stats"),
    WidgetType.WATCHLIST: WidgetCacheConfig(ttl=60, api_name="watchlist"),
    WidgetType.NEWS: WidgetCacheConfig(ttl=600, api_name="news"),
}


class WidgetDataService:
    """
    Unified service for fetching widget data.

    Features:
    - Per-widget caching with configurable TTL
    - Rate limiting integration
    - Circuit breaker for fault tolerance
    - Fallback to AkShare when TuShare fails
    """

    def __init__(self):
        self._cache: Dict[str, tuple] = {}  # key -> (data, expiry_time)
        self._cache_lock = threading.Lock()

    def _get_cache(self, key: str) -> Optional[Any]:
        """Get data from cache if not expired"""
        with self._cache_lock:
            if key in self._cache:
                data, expiry = self._cache[key]
                if time.time() < expiry:
                    return data
                del self._cache[key]
        return None

    def _set_cache(self, key: str, data: Any, ttl: int):
        """Set data in cache with TTL"""
        with self._cache_lock:
            self._cache[key] = (data, time.time() + ttl)

    def _is_market_open(self) -> bool:
        """Check if Chinese market is open (09:30 - 15:00)"""
        now = datetime.now()
        hm = now.hour * 100 + now.minute
        return 930 <= hm < 1500

    def _safe_float(self, value, default=0.0) -> float:
        """Safely convert value to float, return default if None, invalid, or NaN."""
        if value is None:
            return default
        try:
            result = float(value)
            if math.isnan(result):
                return default
            return result
        except (ValueError, TypeError):
            return default

    def _get_northbound_from_ths(self, days: int = 5) -> Optional[Dict[str, Any]]:
        """
        从同花顺 (data.hexin.cn) 获取北向资金实时数据
        只能获取当日的分钟级数据，历史数据需配合本地缓存
        返回当日累计净流入作为最新值
        """
        try:
            try:
                import requests
                use_requests = True
            except ImportError:
                import httpx
                use_requests = False

            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/117.0.0.0 Safari/537.36",
                "Host": "data.hexin.cn",
                "Referer": "https://data.hexin.cn/",
            }

            url = "https://data.hexin.cn/market/hsgtApi/method/dayChart/"

            if use_requests:
                resp = requests.get(url, headers=headers, timeout=10)
            else:
                resp = httpx.get(url, headers=headers, timeout=10)

            if resp.status_code != 200:
                return None

            data = resp.json()
            times = data.get("time", [])
            hgt_list = data.get("hgt", [])
            sgt_list = data.get("sgt", [])

            if not times or not hgt_list or not sgt_list:
                return None

            # 获取最后一个有效数据点（收盘数据）
            n = len(times)
            hgt_val = 0.0
            sgt_val = 0.0

            # 从后往前找第一个非零/非None的值
            for i in range(min(n, len(hgt_list), len(sgt_list)) - 1, -1, -1):
                try:
                    h = float(hgt_list[i]) if hgt_list[i] is not None else 0.0
                    s = float(sgt_list[i]) if sgt_list[i] is not None else 0.0
                    if h != 0 or s != 0:
                        hgt_val = round(h, 2)
                        sgt_val = round(s, 2)
                        break
                except (ValueError, TypeError):
                    continue

            # 获取今天的日期
            today = datetime.now().strftime("%Y-%m-%d")

            result = {
                "latest": {
                    "date": today,
                    "north_money": round(hgt_val + sgt_val, 2),
                    "hgt_net": hgt_val,
                    "sgt_net": sgt_val,
                },
                "cumulative_5d": round(hgt_val + sgt_val, 2),
                "history": [
                    {
                        "date": today,
                        "north_money": round(hgt_val + sgt_val, 2),
                    }
                ],
                "updated_at": datetime.now().isoformat(),
                "source": "tonghuashun_realtime"
            }
            print(f"Tonghuashun realtime result: date={today}, hgt={hgt_val}, sgt={sgt_val}, total={hgt_val + sgt_val}")
            return result

        except ImportError:
            print("Tonghuashun northbound API skipped: requests/httpx not available")
        except Exception as e:
            print(f"Tonghuashun northbound API error: {e}")

        return None

    def _get_northbound_from_eastmoney(self, days: int = 5) -> Optional[Dict[str, Any]]:
        """
        直接从东方财富 API 获取北向资金数据
        优先使用 NET_DEAL_AMT（成交净买额），其次使用 FUND_INFLOW（资金流入）
        """
        try:
            try:
                import requests
                use_requests = True
            except ImportError:
                import httpx
                use_requests = False

            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                'Referer': 'http://data.eastmoney.com/',
            }

            url = "http://datacenter-web.eastmoney.com/api/data/v1/get"

            # 尝试获取更多数据以找到有效值
            fetch_days = max(days + 50, 100)
            params = {
                'sortColumns': 'TRADE_DATE',
                'sortTypes': '-1',
                'pageSize': str(fetch_days),
                'pageNumber': '1',
                'reportName': 'RPT_MUTUAL_DEAL_HISTORY',
                'columns': 'ALL',
                'source': 'WEB',
                'client': 'WEB',
                'filter': '(MUTUAL_TYPE="005")',
            }

            if use_requests:
                resp = requests.get(url, params=params, headers=headers, timeout=10)
            else:
                resp = httpx.get(url, params=params, headers=headers, timeout=10)

            if resp.status_code != 200:
                return None

            data = resp.json()
            if not data or not data.get('result') or not data['result'].get('data'):
                return None

            items = data['result']['data']

            # 按优先级尝试不同的资金流字段
            flow_fields = ['NET_DEAL_AMT', 'FUND_INFLOW']
            best_field = None
            best_items = []
            best_date = ''

            for field in flow_fields:
                current_items = []
                for item in items:
                    val = item.get(field)
                    if val is not None:
                        try:
                            float_val = float(val)
                            # FUND_INFLOW 单位是万元，转换为亿元
                            if field == 'FUND_INFLOW':
                                float_val = float_val / 100.0
                            current_items.append((item, float_val))
                        except (ValueError, TypeError):
                            continue
                
                if not current_items:
                    continue
                
                current_date = str(current_items[0][0].get('TRADE_DATE', ''))[:10]
                
                # 第一优先级只要有数据就用
                if field == flow_fields[0]:
                    best_field = field
                    best_items = current_items
                    best_date = current_date
                    break
                
                # 其他优先级，比较日期，使用更新的
                if not best_items or current_date > best_date:
                    best_field = field
                    best_items = current_items
                    best_date = current_date

            used_field = best_field
            valid_items = best_items

            if not used_field or not valid_items:
                return None

            print(f"EastMoney datacenter 使用字段: {used_field}, 有效数据: {len(valid_items)} 条")

            history = []
            cumulative_5d = 0
            latest = None

            for i, (item, north_money) in enumerate(valid_items[:days]):
                date_str = str(item.get('TRADE_DATE', ''))[:10]
                north_money = round(north_money, 2)
                history.append({
                    "date": date_str,
                    "north_money": north_money,
                })

                if i == 0:
                    latest = history[0]
                if i < days:
                    cumulative_5d += north_money

            if history and latest:
                result = {
                    "latest": {
                        "date": latest["date"],
                        "north_money": latest["north_money"],
                        "hgt_net": 0.0,
                        "sgt_net": 0.0,
                    },
                    "cumulative_5d": round(cumulative_5d, 2),
                    "history": history,
                    "updated_at": datetime.now().isoformat(),
                    "source": "eastmoney_datacenter"
                }
                print(f"EastMoney datacenter result: {len(history)} days, latest={latest}")
                return result

        except ImportError:
            print("EastMoney northbound API skipped: requests/httpx not available")
        except Exception as e:
            print(f"EastMoney northbound API error: {e}")

        return None

    # =========================================================================
    # Widget Data Methods
    # =========================================================================

    def get_northbound_flow(self, days: int = 5) -> Dict[str, Any]:
        """
        Get northbound capital flow data (沪深港通资金流向).

        Data sources (in order of priority):
        1. TuShare moneyflow_hsgt (if available and circuit breaker not open)
        2. EastMoney Direct API (reliable and fast)
        3. AkShare stock_hsgt_hist_em + stock_hsgt_fund_flow_summary_em (fallback)

        Returns:
            Dict with today's flow, 5-day cumulative, and historical data
        """
        cache_key = f"northbound_flow:{days}"
        config = WIDGET_CACHE_CONFIG[WidgetType.NORTHBOUND_FLOW]

        # Check cache
        cached = self._get_cache(cache_key)
        if cached:
            return cached

        # Try TuShare first (only if circuit breaker is not open)
        if not circuit_breaker.is_open(config.api_name):
            if rate_limiter.acquire(config.api_name):
                try:
                    end_date = format_date_yyyymmdd()
                    start_date = format_date_yyyymmdd(datetime.now() - timedelta(days=days + 10))

                    df = get_moneyflow_hsgt(start_date=start_date, end_date=end_date)

                    if df is not None and not df.empty:
                        df_sorted = df.sort_values('trade_date', ascending=False)
                        circuit_breaker.record_success(config.api_name)

                        result = {
                            "latest": None,
                            "cumulative_5d": 0,
                            "history": [],
                            "updated_at": datetime.now().isoformat(),
                            "source": "tushare"
                        }

                        if not df_sorted.empty:
                            latest = df_sorted.iloc[0]
                            result["latest"] = {
                                "date": str(latest['trade_date']),
                                "north_money": round(self._safe_float(latest.get('north_money')) / 100, 2),
                                "hgt_net": round(self._safe_float(latest.get('hgt')) / 100, 2),
                                "sgt_net": round(self._safe_float(latest.get('sgt')) / 100, 2),
                            }

                        recent_5 = df_sorted.head(5)
                        result["cumulative_5d"] = round(self._safe_float(recent_5['north_money'].fillna(0).sum()) / 100, 2)

                        for _, row in df_sorted.head(days).iterrows():
                            result["history"].append({
                                "date": str(row['trade_date']),
                                "north_money": round(self._safe_float(row.get('north_money')) / 100, 2),
                            })

                        self._set_cache(cache_key, result, config.ttl)
                        return result

                except Exception as e:
                    circuit_breaker.record_failure(config.api_name)
                    print(f"TuShare northbound flow error: {e}")

        # ==========================================
        # 数据源 1: 同花顺实时 API (最新、最可靠)
        # ==========================================
        # 注：同花顺只有当日数据，后面会和 AkShare 历史数据合并
        ths_result = self._get_northbound_from_ths(days)

        # ==========================================
        # 数据源 2: 东方财富直接 API
        # ==========================================
        eastmoney_result = self._get_northbound_from_eastmoney(days)
        # 只有当东方财富数据足够多（>=3天）时才直接使用
        if eastmoney_result and eastmoney_result.get("history") and len(eastmoney_result["history"]) >= min(3, days):
            # 如果有同花顺实时数据，用它来更新最新值
            if ths_result and ths_result.get("latest") and ths_result["latest"].get("north_money") != 0:
                ths_date = ths_result["latest"]["date"]
                em_date = eastmoney_result["latest"]["date"]
                if ths_date > em_date:
                    # 把同花顺数据插入到最前面
                    new_history = [{"date": ths_date, "north_money": ths_result["latest"]["north_money"]}]
                    new_history.extend(eastmoney_result["history"][:days-1])
                    eastmoney_result["latest"] = ths_result["latest"]
                    eastmoney_result["history"] = new_history
                    eastmoney_result["cumulative_5d"] = round(
                        sum(item["north_money"] for item in new_history[:5]), 2
                    )
                    eastmoney_result["source"] = "eastmoney+tonghuashun"
            self._set_cache(cache_key, eastmoney_result, config.ttl)
            return eastmoney_result

        # Fallback: AkShare
        ak_error = None
        try:
            import akshare as ak
            import pandas as pd

            # ==========================================
            # 1. 获取历史数据（北向资金）
            # ==========================================
            history = []
            cumulative_5d = 0
            hist_latest = None

            def _extract_flow_data(df, date_col, flow_cols_priority):
                """从 DataFrame 中提取资金流数据，返回 (日期, 资金流) 的有效数据"""
                if df is None or df.empty:
                    return None

                result_df = df.rename(columns={date_col: '日期'}).copy()
                result_df['日期'] = pd.to_datetime(result_df['日期'], errors='coerce').dt.date

                candidates = []

                # 收集所有有足够有效数据的列
                for flow_col in flow_cols_priority:
                    if flow_col not in result_df.columns:
                        continue
                    try:
                        flow_vals = pd.to_numeric(result_df[flow_col], errors='coerce')
                        valid_count = flow_vals.notna().sum()
                        if valid_count < 10:
                            continue

                        valid_mask = flow_vals.notna()
                        last_valid_date = result_df.loc[valid_mask, '日期'].max()

                        temp_df = result_df.copy()
                        temp_df['_flow'] = flow_vals
                        valid_df = temp_df[temp_df['_flow'].notna()].copy()
                        valid_df = valid_df.sort_values('日期', ascending=False).reset_index(drop=True)

                        candidates.append({
                            'col': flow_col,
                            'df': valid_df,
                            'last_date': last_valid_date,
                            'priority': flow_cols_priority.index(flow_col),
                        })
                    except Exception:
                        continue

                if not candidates:
                    return None

                # 按优先级排序（优先级索引越小越优先）
                candidates.sort(key=lambda x: x['priority'])

                # 如果第一优先级的最新数据在60天内，直接用
                first_candidate = candidates[0]
                days_old = (datetime.now().date() - first_candidate['last_date']).days
                if days_old <= 60:
                    print(f"  使用列 '{first_candidate['col']}': {len(first_candidate['df'])} 条有效数据, 最新日期={first_candidate['last_date']}")
                    return first_candidate['df'][['日期', '_flow']]

                # 否则，找最新数据的列
                candidates.sort(key=lambda x: x['last_date'], reverse=True)
                best = candidates[0]
                print(f"  第一优先级数据过旧({days_old}天), 使用更新的列 '{best['col']}': {len(best['df'])} 条有效数据, 最新日期={best['last_date']}")
                return best['df'][['日期', '_flow']]

            flow_cols_priority = ['当日成交净买额', '当日资金流入', '成交净买额', '当日净流入', '净买额', '净流入', '资金流入']

            # 尝试分别获取沪股通和深股通的历史数据
            combined_df = None
            hgt_valid = None
            sgt_valid = None

            for symbol in ["沪股通", "深股通"]:
                try:
                    df = ak.stock_hsgt_hist_em(symbol=symbol)
                    date_col = '日期' if '日期' in df.columns else df.columns[0]
                    extracted = _extract_flow_data(df, date_col, flow_cols_priority)
                    if extracted is not None and not extracted.empty:
                        if symbol == "沪股通":
                            hgt_valid = extracted.rename(columns={'_flow': 'hgt_flow'})
                        else:
                            sgt_valid = extracted.rename(columns={'_flow': 'sgt_flow'})
                except Exception as e:
                    print(f"AkShare {symbol} history error: {e}")

            # 合并沪股通和深股通数据得到北向资金
            if hgt_valid is not None and sgt_valid is not None:
                # 使用外连接，保留两边所有日期，缺失的填充为0
                merged = pd.merge(hgt_valid, sgt_valid, on='日期', how='outer')
                merged['hgt_flow'] = merged['hgt_flow'].fillna(0)
                merged['sgt_flow'] = merged['sgt_flow'].fillna(0)
                merged['north_money'] = merged['hgt_flow'] + merged['sgt_flow']
                merged = merged.sort_values('日期', ascending=False).reset_index(drop=True)
                combined_df = merged
                print(f"AkShare 沪股通+深股通合并: {len(combined_df)} 条有效数据, 最新日期={combined_df.iloc[0]['日期'] if len(combined_df) > 0 else 'N/A'}")

            # 如果分别获取失败，尝试直接用"北向资金"作为 symbol
            if combined_df is None or combined_df.empty:
                try:
                    direct_df = ak.stock_hsgt_hist_em(symbol="北向资金")
                    if direct_df is not None and not direct_df.empty:
                        date_col = '日期' if '日期' in direct_df.columns else direct_df.columns[0]
                        extracted = _extract_flow_data(direct_df, date_col, flow_cols_priority)
                        if extracted is not None and not extracted.empty:
                            extracted = extracted.rename(columns={'_flow': 'north_money'})
                            extracted['hgt_flow'] = 0.0
                            extracted['sgt_flow'] = 0.0
                            combined_df = extracted
                            print(f"AkShare 直接获取北向资金: {len(combined_df)} 条有效数据")
                except Exception as direct_e:
                    print(f"AkShare direct northbound history error: {direct_e}")

            # 从合并后的历史数据中提取结果
            if combined_df is not None and not combined_df.empty:
                valid = combined_df[combined_df['north_money'].notna()]
                if not valid.empty:
                    recent = valid.head(days)
                    cumulative_5d = round(self._safe_float(recent['north_money'].sum()), 2)

                    for _, row in recent.iterrows():
                        history.append({
                            "date": str(row['日期']),
                            "north_money": round(self._safe_float(row['north_money']), 2),
                        })

                    latest_row = valid.iloc[0]
                    hist_latest = {
                        "date": str(latest_row['日期']),
                        "north_money": round(self._safe_float(latest_row['north_money']), 2),
                        "hgt_net": round(self._safe_float(latest_row.get('hgt_flow', 0)), 2),
                        "sgt_net": round(self._safe_float(latest_row.get('sgt_flow', 0)), 2),
                    }

            # ==========================================
            # 2. 获取实时汇总数据（只有当实时数据有效且比历史数据新时才更新）
            # ==========================================
            try:
                df = ak.stock_hsgt_fund_flow_summary_em()
                if df is not None and not df.empty:
                    # 筛选北向资金
                    north = None
                    if '资金方向' in df.columns:
                        north = df[df['资金方向'] == '北向']
                    elif '方向' in df.columns:
                        north = df[df['方向'] == '北向']

                    if north is not None and not north.empty:
                        # 找出成交净买额列
                        net_col = None
                        for col in ['成交净买额', '净买额', '净流入', '当日净流入', '资金净流入']:
                            if col in north.columns:
                                net_col = col
                                break

                        if net_col:
                            # 计算北向合计 = 沪股通 + 深股通
                            hgt_net_val = 0
                            sgt_net_val = 0

                            if '板块' in north.columns:
                                hgt_rows = north[north['板块'].str.contains('沪股通', na=False)]
                                sgt_rows = north[north['板块'].str.contains('深股通', na=False)]
                                if not hgt_rows.empty:
                                    hgt_net_val = self._safe_float(hgt_rows.iloc[0].get(net_col))
                                if not sgt_rows.empty:
                                    sgt_net_val = self._safe_float(sgt_rows.iloc[0].get(net_col))

                            total_net = hgt_net_val + sgt_net_val

                            # 如果没找到分项，尝试直接求和
                            if total_net == 0:
                                for _, row in north.iterrows():
                                    total_net += self._safe_float(row.get(net_col))

                            # 获取交易日
                            trade_date = ''
                            for date_col in ['交易日', '日期', 'trade_date']:
                                if date_col in north.columns:
                                    val = north.iloc[0].get(date_col)
                                    if val is not None and str(val).strip():
                                        trade_date = str(val)
                                        break

                            # 只有当实时数据不为 0 且比历史数据新时才更新
                            # 注：2024年8月后北向资金净买额数据停止披露，实时数据通常为0，不应覆盖历史有效数据
                            if total_net != 0 and trade_date:
                                # 检查是否比历史数据新
                                should_update = True
                                if hist_latest and hist_latest.get('date'):
                                    try:
                                        hist_date = datetime.strptime(hist_latest['date'], '%Y-%m-%d').date()
                                        rt_date = datetime.strptime(trade_date, '%Y-%m-%d').date()
                                        if rt_date <= hist_date:
                                            should_update = False
                                    except ValueError:
                                        pass
                                if should_update:
                                    hist_latest = {
                                        "date": trade_date,
                                        "north_money": round(total_net, 2),
                                        "hgt_net": round(hgt_net_val, 2),
                                        "sgt_net": round(sgt_net_val, 2),
                                    }
                                    print(f"AkShare 实时数据更新: date={trade_date}, net={total_net:.2f}亿")
            except Exception as summary_e:
                print(f"AkShare northbound summary error: {summary_e}")

            result = {
                "latest": hist_latest,
                "cumulative_5d": cumulative_5d,
                "history": history,
                "updated_at": datetime.now().isoformat(),
                "source": "akshare"
            }

            # 如果有同花顺实时数据，用它来更新最新值
            if ths_result and ths_result.get("latest") and ths_result["latest"].get("north_money") != 0:
                ths_date = ths_result["latest"]["date"]
                ths_north = ths_result["latest"]["north_money"]
                ths_hgt = ths_result["latest"]["hgt_net"]
                ths_sgt = ths_result["latest"]["sgt_net"]

                should_update = True
                if hist_latest and hist_latest.get('date'):
                    try:
                        hist_date = datetime.strptime(hist_latest['date'], '%Y-%m-%d').date()
                        rt_date = datetime.strptime(ths_date, '%Y-%m-%d').date()
                        if rt_date <= hist_date:
                            should_update = False
                    except ValueError:
                        pass

                if should_update:
                    # 更新 latest
                    result["latest"] = ths_result["latest"]
                    # 更新 history（插入到最前面）
                    new_history = [{"date": ths_date, "north_money": ths_north}]
                    new_history.extend(history[:days-1])
                    result["history"] = new_history
                    # 更新 cumulative_5d
                    result["cumulative_5d"] = round(
                        sum(item["north_money"] for item in new_history[:5]), 2
                    )
                    result["source"] = "akshare+tonghuashun"
                    print(f"同花顺实时数据更新: date={ths_date}, net={ths_north:.2f}亿")

            if hist_latest is not None or history:
                self._set_cache(cache_key, result, config.ttl)
                return result

        except Exception as e:
            ak_error = str(e)
            print(f"AkShare northbound flow error: {e}")

        # Both TuShare and AkShare failed — return error with details
        cb_status = "开启" if circuit_breaker.is_open(config.api_name) else "关闭"
        error_msg = f"TuShare(moneyflow_hsgt) 熔断器={cb_status}, AkShare: {ak_error or '返回空数据'}"
        print(f"Northbound flow: {error_msg}")
        return {"error": error_msg, "latest": None, "cumulative_5d": 0, "history": []}


    def get_industry_flow(self, limit: int = 10) -> Dict[str, Any]:
        """
        Get industry money flow data (同花顺行业资金流向).

        Requires 2000 TuShare points.

        Returns:
            Dict with top gainers and losers by net inflow
        """
        cache_key = f"industry_flow:{limit}"
        config = WIDGET_CACHE_CONFIG[WidgetType.INDUSTRY_FLOW]

        # Check cache
        cached = self._get_cache(cache_key)
        if cached:
            return cached

        # Check circuit breaker
        if circuit_breaker.is_open(config.api_name):
            return self._get_industry_flow_akshare(limit)

        # Rate limiting
        if not rate_limiter.acquire(config.api_name):
            return self._get_industry_flow_akshare(limit)

        try:
            df = get_moneyflow_ind_ths()

            if df is None or df.empty:
                circuit_breaker.record_failure(config.api_name)
                return self._get_industry_flow_akshare(limit)

            # Check if data is too old (more than 7 days)
            trade_date_str = str(df.iloc[0].get('trade_date', ''))
            if trade_date_str:
                try:
                    trade_date = datetime.strptime(trade_date_str, '%Y%m%d')
                    days_old = (datetime.now() - trade_date).days
                    if days_old > 7:
                        print(f"TuShare industry flow data is {days_old} days old, falling back to AkShare")
                        return self._get_industry_flow_akshare(limit)
                except ValueError:
                    pass

            circuit_breaker.record_success(config.api_name)

            result = {
                "trade_date": trade_date_str,
                "gainers": [],
                "losers": [],
                "updated_at": datetime.now().isoformat()
            }

            # Sort by net inflow
            if 'net_mf_amount' in df.columns:
                df_sorted = df.sort_values('net_mf_amount', ascending=False)

                # Top gainers (highest net inflow)
                for _, row in df_sorted.head(limit).iterrows():
                    result["gainers"].append({
                        "name": row['name'],
                        "net_inflow": round(self._safe_float(row.get('net_mf_amount')) / 100000000, 2),
                        "change_pct": round(self._safe_float(row.get('pct_change')), 2),
                        "amount": round(self._safe_float(row.get('amount')) / 100000000, 2),
                    })

                # Top losers (lowest net inflow / highest outflow)
                for _, row in df_sorted.tail(limit).iloc[::-1].iterrows():
                    result["losers"].append({
                        "name": row['name'],
                        "net_inflow": round(self._safe_float(row.get('net_mf_amount')) / 100000000, 2),
                        "change_pct": round(self._safe_float(row.get('pct_change')), 2),
                        "amount": round(self._safe_float(row.get('amount')) / 100000000, 2),
                    })

            self._set_cache(cache_key, result, config.ttl)
            return result

        except Exception as e:
            circuit_breaker.record_failure(config.api_name)
            return self._get_industry_flow_akshare(limit)

    def _get_industry_flow_akshare(self, limit: int = 10) -> Dict[str, Any]:
        """Fallback to AkShare for industry flow"""
        try:
            import akshare as ak
            df = ak.stock_sector_fund_flow_rank(indicator="今日", sector_type="行业资金流")

            if df is None or df.empty:
                return {"error": "No data available", "gainers": [], "losers": []}

            result = {
                "trade_date": datetime.now().strftime('%Y%m%d'),
                "gainers": [],
                "losers": [],
                "updated_at": datetime.now().isoformat(),
                "source": "akshare"
            }

            # Map column names (AkShare uses Chinese)
            for _, row in df.head(limit).iterrows():
                net_inflow = row.get('今日主力净流入-净额', 0)
                try:
                    net_inflow = float(net_inflow) if str(net_inflow).strip() != '-' else 0.0
                except (ValueError, TypeError):
                    net_inflow = 0.0

                change_pct = row.get('今日涨跌幅', 0)
                try:
                    change_pct = float(change_pct) if str(change_pct).strip() != '-' else 0.0
                except (ValueError, TypeError):
                    change_pct = 0.0

                result["gainers"].append({
                    "name": row.get('名称', ''),
                    "net_inflow": round(net_inflow / 100000000, 2),
                    "change_pct": round(change_pct, 2),
                    "amount": 0,
                })

            # Get losers from the tail
            for _, row in df.tail(limit).iloc[::-1].iterrows():
                net_inflow = row.get('今日主力净流入-净额', 0)
                try:
                    net_inflow = float(net_inflow) if str(net_inflow).strip() != '-' else 0.0
                except (ValueError, TypeError):
                    net_inflow = 0.0

                change_pct = row.get('今日涨跌幅', 0)
                try:
                    change_pct = float(change_pct) if str(change_pct).strip() != '-' else 0.0
                except (ValueError, TypeError):
                    change_pct = 0.0

                result["losers"].append({
                    "name": row.get('名称', ''),
                    "net_inflow": round(net_inflow / 100000000, 2),
                    "change_pct": round(change_pct, 2),
                    "amount": 0,
                })

            return result

        except Exception as e:
            print(f"AkShare industry flow failed: {e}")
            return {"error": str(e), "gainers": [], "losers": []}

    def get_sector_performance(self, limit: int = 10) -> Dict[str, Any]:
        """
        Get sector/concept performance data (同花顺板块资金流向).

        Requires 2000 TuShare points.

        Returns:
            Dict with top gainers and losers by change percentage
        """
        cache_key = f"sector_performance:{limit}"
        config = WIDGET_CACHE_CONFIG[WidgetType.SECTOR_PERFORMANCE]

        # Check cache
        cached = self._get_cache(cache_key)
        if cached:
            return cached

        # Check circuit breaker
        if circuit_breaker.is_open(config.api_name):
            return self._get_sector_performance_akshare(limit)

        # Rate limiting
        if not rate_limiter.acquire(config.api_name):
            return self._get_sector_performance_akshare(limit)

        try:
            df = get_moneyflow_cnt_ths()

            if df is None or df.empty:
                circuit_breaker.record_failure(config.api_name)
                # Fallback to AkShare
                return self._get_sector_performance_akshare(limit)

            # Check if data is too old (more than 7 days)
            trade_date_str = str(df.iloc[0].get('trade_date', ''))
            if trade_date_str:
                try:
                    trade_date = datetime.strptime(trade_date_str, '%Y%m%d')
                    days_old = (datetime.now() - trade_date).days
                    if days_old > 7:
                        print(f"TuShare sector data is {days_old} days old, falling back to AkShare")
                        return self._get_sector_performance_akshare(limit)
                except ValueError:
                    pass

            circuit_breaker.record_success(config.api_name)

            result = {
                "trade_date": trade_date_str,
                "gainers": [],
                "losers": [],
                "updated_at": datetime.now().isoformat()
            }

            # Sort by change percentage
            if 'pct_change' in df.columns:
                df_sorted = df.sort_values('pct_change', ascending=False)

                # Top gainers
                for _, row in df_sorted.head(limit).iterrows():
                    result["gainers"].append({
                        "name": row['name'],
                        "change_pct": round(self._safe_float(row.get('pct_change')), 2),
                        "net_inflow": round(self._safe_float(row.get('net_mf_amount')) / 100000000, 2),
                        "amount": round(self._safe_float(row.get('amount')) / 100000000, 2),
                    })

                # Top losers
                for _, row in df_sorted.tail(limit).iloc[::-1].iterrows():
                    result["losers"].append({
                        "name": row['name'],
                        "change_pct": round(self._safe_float(row.get('pct_change')), 2),
                        "net_inflow": round(self._safe_float(row.get('net_mf_amount')) / 100000000, 2),
                        "amount": round(self._safe_float(row.get('amount')) / 100000000, 2),
                    })

            self._set_cache(cache_key, result, config.ttl)
            return result

        except Exception as e:
            circuit_breaker.record_failure(config.api_name)
            return self._get_sector_performance_akshare(limit)

    def _get_sector_performance_akshare(self, limit: int = 10) -> Dict[str, Any]:
        """Fallback to AkShare for sector performance"""
        try:
            import akshare as ak
            df = ak.stock_board_industry_name_em()

            if df is None or df.empty:
                return {"error": "No data available", "gainers": [], "losers": []}

            result = {
                "trade_date": datetime.now().strftime('%Y%m%d'),
                "gainers": [],
                "losers": [],
                "updated_at": datetime.now().isoformat(),
                "source": "akshare"
            }

            df_sorted = df.sort_values(by='涨跌幅', ascending=False)

            for _, row in df_sorted.head(limit).iterrows():
                result["gainers"].append({
                    "name": row['板块名称'],
                    "change_pct": round(float(row['涨跌幅']), 2),
                    "net_inflow": 0,
                    "amount": 0,
                })

            for _, row in df_sorted.tail(limit).iloc[::-1].iterrows():
                result["losers"].append({
                    "name": row['板块名称'],
                    "change_pct": round(float(row['涨跌幅']), 2),
                    "net_inflow": 0,
                    "amount": 0,
                })

            return result

        except Exception as e:
            return {"error": str(e), "gainers": [], "losers": []}

    def get_top_list(self, limit: int = 10) -> Dict[str, Any]:
        """
        Get Dragon Tiger list data (龙虎榜).

        Primary: TuShare top_list
        Fallback: AkShare

        Returns:
            Dict with top stocks by trading activity
        """
        cache_key = f"top_list:{limit}"
        config = WIDGET_CACHE_CONFIG[WidgetType.TOP_LIST]

        # Check cache
        cached = self._get_cache(cache_key)
        if cached:
            return cached

        # Try TuShare first (only if circuit breaker is not open)
        if not circuit_breaker.is_open(config.api_name):
            if rate_limiter.acquire(config.api_name):
                try:
                    for days_back in range(0, 6):
                        trade_date = (datetime.now() - timedelta(days=days_back)).strftime('%Y%m%d')

                        df = tushare_call_with_retry('top_list', trade_date=trade_date)

                        if df is not None and not df.empty:
                            circuit_breaker.record_success(config.api_name)

                            result = {
                                "trade_date": trade_date,
                                "data": [],
                                "updated_at": datetime.now().isoformat(),
                                "source": "tushare"
                            }

                            seen_codes = set()
                            for _, row in df.iterrows():
                                ts_code = row.get('ts_code', '')
                                if ts_code in seen_codes:
                                    continue
                                seen_codes.add(ts_code)

                                result["data"].append({
                                    "code": denormalize_ts_code(ts_code),
                                    "name": row.get('name', ''),
                                    "close": self._safe_float(row.get('close')),
                                    "change_pct": self._safe_float(row.get('pct_change')),
                                    "amount": round(self._safe_float(row.get('amount')) / 100000000, 2),
                                    "net_amount": round(self._safe_float(row.get('net_amount')) / 100000000, 2),
                                    "l_buy": round(self._safe_float(row.get('l_buy')) / 100000000, 2),
                                    "l_sell": round(self._safe_float(row.get('l_sell')) / 100000000, 2),
                                    "turnover_rate": self._safe_float(row.get('turnover_rate')),
                                    "reason": row.get('reason', ''),
                                })

                                if len(result["data"]) >= limit:
                                    break

                            self._set_cache(cache_key, result, config.ttl)
                            return result

                    circuit_breaker.record_failure(config.api_name)
                except Exception as e:
                    circuit_breaker.record_failure(config.api_name)
                    print(f"TuShare top list error: {e}")

        # Fallback: AkShare
        try:
            import akshare as ak

            # Try last 5 trading days
            for days_back in range(0, 6):
                trade_date = (datetime.now() - timedelta(days=days_back)).strftime('%Y%m%d')

                try:
                    df = ak.stock_lhb_detail_em(start_date=trade_date, end_date=trade_date)
                except Exception:
                    continue

                if df is not None and not df.empty:
                    result = {
                        "trade_date": trade_date,
                        "data": [],
                        "updated_at": datetime.now().isoformat(),
                        "source": "akshare"
                    }

                    seen_codes = set()
                    for _, row in df.iterrows():
                        code = str(row.get('代码', '')).strip()
                        if code in seen_codes:
                            continue
                        seen_codes.add(code)

                        result["data"].append({
                            "code": code,
                            "name": str(row.get('名称', '')),
                            "close": self._safe_float(row.get('收盘价')),
                            "change_pct": self._safe_float(row.get('涨跌幅')),
                            "amount": round(self._safe_float(row.get('成交额')) / 100000000, 2),
                            "net_amount": round(self._safe_float(row.get('净买入额')) / 100000000, 2),
                            "l_buy": round(self._safe_float(row.get('买入金额')) / 100000000, 2),
                            "l_sell": round(self._safe_float(row.get('卖出金额')) / 100000000, 2),
                            "turnover_rate": self._safe_float(row.get('换手率')),
                            "reason": str(row.get('上榜原因', '')),
                        })

                        if len(result["data"]) >= limit:
                            break

                    self._set_cache(cache_key, result, config.ttl)
                    return result

        except Exception as e:
            print(f"AkShare top list error: {e}")

        return {"error": "Service temporarily unavailable", "data": []}

    def get_forex_rates(self) -> Dict[str, Any]:
        """
        Get forex rates (外汇汇率).

        Primary: AkShare (more reliable)
        Fallback: TuShare FXCM data

        Returns:
            Dict with major currency pairs
        """
        cache_key = "forex_rates"
        config = WIDGET_CACHE_CONFIG[WidgetType.FOREX_RATES]

        # Check cache
        cached = self._get_cache(cache_key)
        if cached:
            return cached

        # Check circuit breaker
        if circuit_breaker.is_open(config.api_name):
            return self._get_forex_rates_akshare()

        # Rate limiting
        if not rate_limiter.acquire(config.api_name):
            return self._get_forex_rates_akshare()

        # Try AkShare first (more reliable)
        result = self._get_forex_rates_akshare()
        if result.get("rates"):
            self._set_cache(cache_key, result, config.ttl)
            return result

        # Fallback to TuShare
        try:
            result = self._get_forex_rates_tushare()
            if result.get("rates"):
                circuit_breaker.record_success(config.api_name)
                self._set_cache(cache_key, result, config.ttl)
                return result
        except Exception as e:
            print(f"TuShare FX API failed: {e}")
            circuit_breaker.record_failure(config.api_name)

        # Last resort: mock data
        return self._get_mock_forex_rates()

    def _get_forex_rates_akshare(self) -> Dict[str, Any]:
        """Get forex rates from AkShare"""
        try:
            import akshare as ak

            result_rates = []
            today = datetime.now().strftime('%Y%m%d')

            # Try to get forex spot rates
            try:
                # 外汇即期汇率
                df = ak.fx_spot_quote()

                if df is not None and not df.empty:
                    # Map currency pairs
                    pair_mapping = {
                        'USD/CNY': ('USDCNY.FX', '美元/人民币', 'USD/CNY'),
                        'EUR/CNY': ('EURCNY.FX', '欧元/人民币', 'EUR/CNY'),
                        'JPY/CNY': ('JPYCNY.FX', '日元/人民币', 'JPY/CNY'),
                        'HKD/CNY': ('HKDCNY.FX', '港币/人民币', 'HKD/CNY'),
                        'GBP/CNY': ('GBPCNY.FX', '英镑/人民币', 'GBP/CNY'),
                    }

                    for _, row in df.iterrows():
                        pair = row.get('货币对', '')
                        if pair in pair_mapping:
                            code, name, name_en = pair_mapping[pair]
                            rate = float(row.get('买入价', 0) or row.get('最新价', 0) or 0)
                            change_pct = float(row.get('涨跌幅', 0) or 0)

                            if rate > 0:
                                result_rates.append({
                                    "code": code,
                                    "name": name,
                                    "name_en": name_en,
                                    "rate": round(rate, 4),
                                    "change": 0,
                                    "change_pct": round(change_pct, 2),
                                    "date": today,
                                })

                    if result_rates:
                        return {
                            "rates": result_rates,
                            "updated_at": datetime.now().isoformat(),
                            "source": "akshare"
                        }
            except Exception as e:
                print(f"AkShare fx_spot_quote failed: {e}")

            # Alternative: currency_boc (Bank of China rates)
            try:
                df = ak.currency_boc_safe()

                if df is not None and not df.empty:
                    currency_mapping = {
                        '美元': ('USDCNY.FX', '美元/人民币', 'USD/CNY'),
                        '欧元': ('EURCNY.FX', '欧元/人民币', 'EUR/CNY'),
                        '日元': ('JPYCNY.FX', '日元/人民币', 'JPY/CNY'),
                        '港币': ('HKDCNY.FX', '港币/人民币', 'HKD/CNY'),
                        '英镑': ('GBPCNY.FX', '英镑/人民币', 'GBP/CNY'),
                    }

                    for _, row in df.iterrows():
                        currency = row.get('货币名称', '')
                        if currency in currency_mapping:
                            code, name, name_en = currency_mapping[currency]
                            # 中行牌价通常是100外币兑换人民币，需要转换
                            rate = float(row.get('中行折算价', 0) or row.get('现汇买入价', 0) or 0)

                            # 日元是100日元兑人民币，需要除以100
                            if currency == '日元' and rate > 1:
                                rate = rate / 100
                            # 其他货币如果大于10，可能也是100单位
                            elif rate > 10 and currency not in ['港币']:
                                rate = rate / 100

                            if rate > 0:
                                result_rates.append({
                                    "code": code,
                                    "name": name,
                                    "name_en": name_en,
                                    "rate": round(rate, 4),
                                    "change": 0,
                                    "change_pct": 0,
                                    "date": today,
                                })

                    if result_rates:
                        return {
                            "rates": result_rates,
                            "updated_at": datetime.now().isoformat(),
                            "source": "akshare_boc"
                        }
            except Exception as e:
                print(f"AkShare currency_boc_safe failed: {e}")

            return {"rates": [], "error": "AkShare forex data unavailable"}

        except Exception as e:
            print(f"AkShare forex failed: {e}")
            return {"rates": [], "error": str(e)}

    def _get_forex_rates_tushare(self) -> Dict[str, Any]:
        """Get forex rates from TuShare FXCM data"""
        # Note: TuShare FX uses GMT dates (1 day behind Beijing time)
        # We need to look back a few days to find data

        # Calculate GMT date (Beijing is GMT+8)
        from datetime import timezone
        beijing_now = datetime.now()
        # GMT is approximately 8 hours behind Beijing
        # For forex, the trade_date might be the previous day
        gmt_date = (beijing_now - timedelta(hours=8)).strftime('%Y%m%d')

        # Look back up to 10 days to find data
        lookback_days = 10
        start_date = (beijing_now - timedelta(days=lookback_days)).strftime('%Y%m%d')
        end_date = gmt_date

        # Fetch USDCNH anchor to find latest available date
        df_anchor = get_fx_daily_tushare(
            ts_code='USDCNH.FXCM',
            start_date=start_date,
            end_date=end_date,
            exchange='FX'
        )

        if df_anchor is None or df_anchor.empty:
            print(f"TuShare FX anchor empty. start={start_date}, end={end_date}")
            return {"rates": [], "error": "No forex data available (TuShare)"}

        # Get latest date from the data
        df_anchor = df_anchor.sort_values('trade_date', ascending=False)
        latest_date = str(df_anchor.iloc[0]['trade_date'])

        # Fetch all required pairs for this date
        required_pairs = ['USDCNH.FXCM', 'EURUSD.FXCM', 'USDJPY.FXCM', 'USDHKD.FXCM', 'GBPUSD.FXCM']

        dfs = []
        for code in required_pairs:
            try:
                d = get_fx_daily_tushare(
                    ts_code=code,
                    start_date=latest_date,
                    end_date=latest_date,
                    exchange='FX'
                )
                if d is not None and not d.empty:
                    dfs.append(d)
            except Exception as e:
                print(f"Failed to fetch {code}: {e}")

        if not dfs:
            return {"rates": [], "error": "No forex pairs data available"}

        import pandas as pd
        df_all = pd.concat(dfs, ignore_index=True)

        # Create a lookup map: code -> row
        rates_map = {}
        for _, row in df_all.iterrows():
            rates_map[row['ts_code']] = row

        # Helper to safely get float value
        def safe_float(val, default=0.0):
            if val is None:
                return default
            try:
                return float(val)
            except (ValueError, TypeError):
                return default

        # Helper to get change info
        def get_change_info(code):
            if code in rates_map:
                row = rates_map[code]
                # TuShare fx_daily returns: bid_open, bid_close, bid_high, bid_low, etc.
                close_col = 'bid_close' if 'bid_close' in row else 'close'
                open_col = 'bid_open' if 'bid_open' in row else 'open'

                c = safe_float(row.get(close_col))
                o = safe_float(row.get(open_col))

                if c == 0:
                    return None, 0, 0

                change = c - o if o else 0
                pct = (change / o) * 100 if o else 0
                return c, change, pct
            return None, 0, 0

        # Get USDCNH (Anchor)
        usdcnh, usdcnh_chg, usdcnh_pct = get_change_info('USDCNH.FXCM')
        if usdcnh is None or usdcnh == 0:
            return {"rates": [], "error": "No USDCNH data available"}

        # Calculate cross rates
        result_rates = []
        targets = [
            ("USDCNY.FX", "美元/人民币", "USD/CNY", "USDCNH.FXCM", "direct"),
            ("EURCNY.FX", "欧元/人民币", "EUR/CNY", "EURUSD.FXCM", "multiply"),
            ("JPYCNY.FX", "日元/人民币", "JPY/CNY", "USDJPY.FXCM", "divide_by"),
            ("HKDCNY.FX", "港币/人民币", "HKD/CNY", "USDHKD.FXCM", "divide_by"),
            ("GBPCNY.FX", "英镑/人民币", "GBP/CNY", "GBPUSD.FXCM", "multiply"),
        ]

        for t_code, name, name_en, s_code, logic in targets:
            src_val, src_chg, src_pct = get_change_info(s_code)

            if src_val is None or src_val == 0:
                continue

            rate = 0
            change_pct = 0

            if logic == "direct":
                rate = src_val
                change_pct = src_pct
            elif logic == "multiply":
                rate = src_val * usdcnh
                change_pct = src_pct + usdcnh_pct
            elif logic == "divide_by":
                rate = usdcnh / src_val
                change_pct = usdcnh_pct - src_pct

            result_rates.append({
                "code": t_code,
                "name": name,
                "name_en": name_en,
                "rate": round(rate, 4),
                "change": 0,
                "change_pct": round(change_pct, 2),
                "date": latest_date,
            })

        if not result_rates:
            return {"rates": [], "error": "No calculated rates available"}

        return {
            "rates": result_rates,
            "updated_at": datetime.now().isoformat(),
            "source": "tushare"
        }

    def _get_mock_forex_rates(self) -> Dict[str, Any]:
        """Generate mock forex rates when API is unavailable"""
        import random
        
        # Base rates (approximate)
        base_rates = {
            "USDCNY.FX": 7.25,
            "EURCNY.FX": 7.85,
            "JPYCNY.FX": 0.048,
            "HKDCNY.FX": 0.93,
            "GBPCNY.FX": 9.15
        }
        
        names = {
            "USDCNY.FX": ("美元/人民币", "USD/CNY"),
            "EURCNY.FX": ("欧元/人民币", "EUR/CNY"),
            "JPYCNY.FX": ("日元/人民币", "JPY/CNY"),
            "HKDCNY.FX": ("港币/人民币", "HKD/CNY"),
            "GBPCNY.FX": ("英镑/人民币", "GBP/CNY"),
        }
        
        rates = []
        today = datetime.now().strftime('%Y%m%d')
        
        for code, base in base_rates.items():
            # Add small random variation
            variation = base * (random.uniform(-0.005, 0.005))
            current = base + variation
            change = variation
            change_pct = (variation / base) * 100
            
            cn_name, en_name = names[code]
            
            rates.append({
                "code": code,
                "name": cn_name,
                "name_en": en_name,
                "rate": round(current, 4),
                "change": round(change, 4),
                "change_pct": round(change_pct, 2),
                "date": today,
            })
            
        return {
            "rates": rates,
            "updated_at": datetime.now().isoformat(),
            "is_mock": True
        }

    def get_main_capital_flow(self, limit: int = 10) -> Dict[str, Any]:
        """
        Get top stocks by main capital net inflow (主力资金流向).
        Uses TuShare northbound flow by default, falls back to AkShare.

        Returns:
            Dict with top_flows list and market_overview
        """
        cache_key = f"main_flow:{limit}"
        config = WIDGET_CACHE_CONFIG[WidgetType.MAIN_CAPITAL_FLOW]

        # Check cache
        cached = self._get_cache(cache_key)
        if cached:
            return cached
            
        result = {
            "top_flows": [],
            "market_overview": {"main_flow": 0},
            "updated_at": datetime.now().isoformat()
        }

        # 1. Fetch Top Flows (Stocks)
        stocks = []
        try:
            # Try TuShare first
            stocks = get_top_money_flow_from_tushare(limit=limit)
        except Exception as e:
            print(f"TuShare top flow failed: {e}")

        # Fallback to AkShare if TuShare failed or returned empty
        if not stocks:
            try:
                import akshare as ak
                # Main capital flow rank
                df = ak.stock_individual_fund_flow_rank(indicator="今日")
                if not df.empty:
                    # Top 10 inflow
                    for _, row in df.head(limit).iterrows():
                        net_buy_val = row.get('今日主力净流入-净额', 0)
                        try:
                            if str(net_buy_val).strip() == '-':
                                 net_buy_float = 0.0
                            else:
                                 net_buy_float = float(net_buy_val)
                        except (ValueError, TypeError):
                            net_buy_float = 0.0

                        stocks.append({
                            "code": str(row.get('代码')),
                            "name": row.get('名称'),
                            "net_buy": round(net_buy_float / 100000000, 2), # Billions
                            "change_pct": row.get('今日涨跌幅')
                        })
            except Exception as e:
                print(f"AkShare flow failed: {e}")

        result["top_flows"] = stocks

        # 2. Fetch Market Total Flow (Optional, fast)
        try:
            import akshare as ak
            flow_df = ak.stock_market_fund_flow()
            if not flow_df.empty:
                last = flow_df.iloc[-1]
                val = last.get('主力净流入-净额', 0)
                try:
                    val = float(val) if str(val).strip() != '-' else 0.0
                except:
                    val = 0.0
                result["market_overview"]["main_flow"] = round(val / 100000000, 2)
        except:
            pass

        self._set_cache(cache_key, result, config.ttl)
        return result

    def get_watchlist_quotes(self, stock_codes: List[str]) -> Dict[str, Any]:
        """
        Get real-time quotes for watchlist stocks.

        Args:
            stock_codes: List of stock codes (6 digits)

        Returns:
            Dict with stock quotes
        """
        if not stock_codes:
            return {"stocks": [], "updated_at": datetime.now().isoformat()}

        cache_key = f"watchlist:{','.join(sorted(stock_codes))}"
        config = WIDGET_CACHE_CONFIG[WidgetType.WATCHLIST]

        # Check cache
        cached = self._get_cache(cache_key)
        if cached:
            return cached

        try:
            trade_date = get_latest_trade_date()
            if not trade_date:
                trade_date = format_date_yyyymmdd()

            result = {
                "stocks": [],
                "trade_date": trade_date,
                "updated_at": datetime.now().isoformat()
            }

            for code in stock_codes[:20]:  # Limit to 20 stocks
                try:
                    ts_code = normalize_ts_code(code)
                    df = tushare_call_with_retry('daily_basic', ts_code=ts_code, trade_date=trade_date)

                    if df is not None and not df.empty:
                        row = df.iloc[0]
                        result["stocks"].append({
                            "code": code,
                            "ts_code": ts_code,
                            "close": self._safe_float(row.get('close')),
                            "change_pct": self._safe_float(row.get('pct_chg')),
                            "pe": self._safe_float(row.get('pe')) if row.get('pe') is not None else None,
                            "pb": self._safe_float(row.get('pb')) if row.get('pb') is not None else None,
                            "total_mv": round(self._safe_float(row.get('total_mv')) / 10000, 2) if row.get('total_mv') is not None else None,
                            "turnover_rate": self._safe_float(row.get('turnover_rate')) if row.get('turnover_rate') is not None else None,
                        })
                except Exception as e:
                    print(f"Failed to fetch {code}: {e}")
                    continue

            self._set_cache(cache_key, result, config.ttl)
            return result

        except Exception as e:
            return {"error": str(e), "stocks": []}

    def get_news(self, limit: int = 20, src: str = 'sina') -> Dict[str, Any]:
        """
        Get news feed (新闻资讯).

        Args:
            limit: Number of news items to return
            src: News source (sina, wallstreetcn, 10jqka, eastmoney, yuncaijing)

        Returns:
            Dict with news items
        """
        cache_key = f"news:{src}:{limit}"
        config = WIDGET_CACHE_CONFIG[WidgetType.NEWS]

        # Check cache
        cached = self._get_cache(cache_key)
        if cached:
            return cached

        # Check circuit breaker
        if circuit_breaker.is_open(config.api_name):
            return {"error": "Service temporarily unavailable", "news": []}

        # Rate limiting
        if not rate_limiter.acquire(config.api_name):
            return {"error": "Rate limit exceeded", "news": []}

        try:
            end_date = datetime.now().strftime('%Y%m%d %H:%M:%S')
            start_date = (datetime.now() - timedelta(days=1)).strftime('%Y%m%d %H:%M:%S')

            df = tushare_call_with_retry('news', src=src, start_date=start_date, end_date=end_date)

            if df is None or df.empty:
                # Try major_news as fallback
                df = tushare_call_with_retry('major_news', src='', start_date=start_date[:8], end_date=end_date[:8])

            if df is None or df.empty:
                circuit_breaker.record_failure(config.api_name)
                return {"error": "No news available", "news": []}

            circuit_breaker.record_success(config.api_name)

            result = {
                "news": [],
                "updated_at": datetime.now().isoformat()
            }

            for _, row in df.head(limit).iterrows():
                result["news"].append({
                    "title": row.get('title', ''),
                    "content": row.get('content', '')[:200] if row.get('content') else '',
                    "datetime": str(row.get('datetime', '')),
                    "source": row.get('src', src),
                })

            self._set_cache(cache_key, result, config.ttl)
            return result

        except Exception as e:
            circuit_breaker.record_failure(config.api_name)
            return {"error": str(e), "news": []}


# Singleton instance
widget_service = WidgetDataService()
