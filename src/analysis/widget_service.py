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
    SOUTHBOUND_FLOW = "southbound_flow"
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
    WidgetType.SOUTHBOUND_FLOW: WidgetCacheConfig(ttl=300, api_name="southbound_flow"),
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

    def get_southbound_flow(self, days: int = 5) -> Dict[str, Any]:
        """
        获取南向资金流向数据（港股通）.

        数据源:
        - AkShare stock_hsgt_hist_em (历史数据，每日更新)
        - AkShare stock_hsgt_fund_flow_summary_em (实时数据，可选更新)

        返回:
            包含最新数据、5日累计、历史数据的字典
        """
        cache_key = f"southbound_flow:{days}"
        config = WIDGET_CACHE_CONFIG[WidgetType.SOUTHBOUND_FLOW]

        # 检查缓存
        cached = self._get_cache(cache_key)
        if cached:
            return cached

        history = []
        cumulative_5d = 0
        hist_latest = None

        try:
            import akshare as ak

            # 1. 获取南向资金历史数据
            df = ak.stock_hsgt_hist_em(symbol="南向资金")
            if df is not None and not df.empty:
                df = df.sort_values('日期', ascending=False).reset_index(drop=True)

                # 使用"当日成交净买额"列
                net_col = '当日成交净买额'
                if net_col in df.columns:
                    valid = df[df[net_col].notna()].copy()
                    valid = valid.sort_values('日期', ascending=False).reset_index(drop=True)

                    if not valid.empty:
                        recent = valid.head(days)
                        cumulative_5d = round(self._safe_float(recent[net_col].sum()), 2)

                        for _, row in recent.iterrows():
                            history.append({
                                "date": str(row['日期']),
                                "south_money": round(self._safe_float(row[net_col]), 2),
                            })

                        latest_row = valid.iloc[0]
                        hist_latest = {
                            "date": str(latest_row['日期']),
                            "south_money": round(self._safe_float(latest_row[net_col]), 2),
                            "hk_sh_net": 0.0,
                            "hk_sz_net": 0.0,
                        }
                        print(f"Southbound history: {len(valid)} days, latest={hist_latest['date']}")

            # 2. 尝试用实时数据补充分项数据
            try:
                rt_df = ak.stock_hsgt_fund_flow_summary_em()
                if rt_df is not None and not rt_df.empty:
                    # 筛选南向资金
                    south = rt_df[rt_df['资金方向'] == '南向']
                    if not south.empty:
                        hk_sh_net = 0.0
                        hk_sz_net = 0.0
                        rt_date = None

                        if '板块' in south.columns:
                            hk_sh_rows = south[south['板块'].str.contains('港股通(沪)', na=False, regex=False)]
                            hk_sz_rows = south[south['板块'].str.contains('港股通(深)', na=False, regex=False)]
                            if not hk_sh_rows.empty:
                                hk_sh_net = self._safe_float(hk_sh_rows.iloc[0].get('成交净买额'))
                                # 获取实时数据的日期
                                if '交易日' in hk_sh_rows.columns:
                                    rt_date = str(hk_sh_rows.iloc[0]['交易日'])
                            if not hk_sz_rows.empty:
                                hk_sz_net = self._safe_float(hk_sz_rows.iloc[0].get('成交净买额'))
                                if rt_date is None and '交易日' in hk_sz_rows.columns:
                                    rt_date = str(hk_sz_rows.iloc[0]['交易日'])

                        total = hk_sh_net + hk_sz_net

                        if hist_latest is not None:
                            hist_date = hist_latest.get('date', '')
                            # 如果实时数据有分项，且日期 >= 历史最新日期，更新分项数据
                            if (hk_sh_net != 0 or hk_sz_net != 0) and rt_date and rt_date >= hist_date:
                                hist_latest['hk_sh_net'] = round(hk_sh_net, 2)
                                hist_latest['hk_sz_net'] = round(hk_sz_net, 2)
                                # 如果日期更新，同时更新总额和日期
                                if rt_date > hist_date:
                                    hist_latest['date'] = rt_date
                                    hist_latest['south_money'] = round(total, 2)
                                    new_history = [{"date": rt_date, "south_money": round(total, 2)}]
                                    new_history.extend(history[:days-1])
                                    history = new_history
                                    cumulative_5d = round(
                                        sum(item["south_money"] for item in history[:5]), 2
                                    )
                                    print(f"Southbound realtime update: date={rt_date}, net={total:.2f}亿")
                                else:
                                    # 同一天，只更新分项
                                    print(f"Southbound realtime: updated components for {rt_date}")

            except Exception as rt_e:
                print(f"Southbound realtime error: {rt_e}")

        except Exception as e:
            print(f"Southbound flow error: {e}")

        result = {
            "latest": hist_latest,
            "cumulative_5d": cumulative_5d,
            "history": history,
            "updated_at": datetime.now().isoformat(),
            "source": "akshare"
        }

        if hist_latest is not None or history:
            self._set_cache(cache_key, result, config.ttl)
            return result

        # 所有数据源都失败，返回错误
        result["error"] = "All southbound flow data sources failed"
        return result

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
