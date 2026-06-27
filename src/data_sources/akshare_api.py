import akshare as ak
import pandas as pd
from datetime import datetime, timedelta
import inspect
import time
import threading
from typing import Dict, List, Optional


_A_STOCK_SPOT_CACHE_LOCK = threading.Lock()
_A_STOCK_SPOT_CACHE_FETCHED_AT: float = 0.0
_A_STOCK_SPOT_CACHE_BY_CODE: Optional[Dict[str, Dict]] = None


def _normalize_a_stock_code(stock_code: str) -> str:
    if not stock_code:
        return ""
    stock_code = str(stock_code).strip()
    # Common cases: "600519", "600519.SH", "SZ000001"
    for part in (stock_code.split(".")[0], stock_code):
        digits = "".join(ch for ch in part if ch.isdigit())
        if len(digits) == 6:
            return digits
    return stock_code


def get_all_stock_spot_map(cache_ttl_seconds: int = 30, force_refresh: bool = False) -> Optional[Dict[str, Dict]]:
    """Return a cached mapping {code -> row_dict} built from ak.stock_zh_a_spot_em()."""
    global _A_STOCK_SPOT_CACHE_FETCHED_AT, _A_STOCK_SPOT_CACHE_BY_CODE

    now = time.time()
    with _A_STOCK_SPOT_CACHE_LOCK:
        if (
            not force_refresh
            and _A_STOCK_SPOT_CACHE_BY_CODE is not None
            and (now - _A_STOCK_SPOT_CACHE_FETCHED_AT) < max(cache_ttl_seconds, 1)
        ):
            return _A_STOCK_SPOT_CACHE_BY_CODE

        try:
            df = ak.stock_zh_a_spot_em()
            if df is None or df.empty or '代码' not in df.columns:
                # Keep old cache if fetch fails? Or clear? Let's clear to be safe or maybe keep old is better?
                # If fetch fails, returning None lets caller handle it.
                return _A_STOCK_SPOT_CACHE_BY_CODE
            
            # Build once for O(1) lookups during holdings loops
            # Columns usually: 代码, 名称, 最新价, 涨跌幅, ...
            by_code = df.set_index('代码').to_dict('index')
            _A_STOCK_SPOT_CACHE_BY_CODE = by_code
            _A_STOCK_SPOT_CACHE_FETCHED_AT = time.time()
            return by_code
        except Exception as e:
            print(f"Error refreshing stock spot map: {e}")
            return _A_STOCK_SPOT_CACHE_BY_CODE

def get_stock_history(code: str, days: int = 100) -> List[Dict]:
    """
    Fetch daily history for a stock.
    """
    # Use TuShare for stock history
    try:
        from src.data_sources.data_source_manager import get_stock_history_from_tushare
        result = get_stock_history_from_tushare(code, days)
        if result:
                return result
    except Exception as e:
            print(f"TuShare stock history failed, falling back to AkShare: {e}")
    

# ============================================================================
# SECTION 1: 全球宏观市场数据 (Global Macro Data)
# ============================================================================

def get_us_market_overview() -> Dict:
    """
    获取隔夜美股市场概览：三大指数
    Returns: {指数名: {最新价, 涨跌幅, ...}}

    Migration Note: Now uses yFinance as primary source (Phase 3 - US market priority)
    """
    from config.settings import DATA_SOURCE_PROVIDER

    # Use yFinance for US market data (more reliable per Phase 3 priority)
    if DATA_SOURCE_PROVIDER in ('yfinance', 'hybrid'):
        try:
            from src.data_sources.data_source_manager import get_us_market_overview_from_yfinance
            result = get_us_market_overview_from_yfinance()
            if result and '说明' not in result:
                return result
        except Exception as e:
            print(f"yFinance US market fetch failed, falling back to AkShare: {e}")

    # Fallback to AkShare if yFinance fails or provider is 'akshare'
    result = {}
    try:
        # 使用全球指数接口获取美股三大指数
        df = ak.index_global_spot_em()
        if not df.empty:
            # 美股三大指数映射 (Name -> Code for reference, but here we search by Name)
            # Actually index_global_spot_em has '名称' column.
            # We want to match these names:
            target_names = ['道琼斯', '纳斯达克', '标普500']

            # Optimized: Filter dataframe directly
            filtered_df = df[df['名称'].isin(target_names)]

            for _, r in filtered_df.iterrows():
                name = r['名称']
                result[name] = {
                    '最新价': r.get('最新价', 'N/A'),
                    '涨跌额': r.get('涨跌额', 'N/A'),
                    '涨跌幅': f"{r.get('涨跌幅', 0)}%",
                    '开盘价': r.get('开盘价', 'N/A'),
                    '最高价': r.get('最高价', 'N/A'),
                    '最低价': r.get('最低价', 'N/A'),
                    '更新时间': r.get('最新行情时间', 'N/A')
                }
    except Exception as e:
        print(f"Error fetching US market: {e}")

    return result if result else {"说明": "美股数据暂时无法获取"}

def get_a50_futures() -> Dict:
    """
    获取富时A50相关指数数据
    由于直接A50期货数据不稳定，使用全球指数中的新加坡/恒生指数作为亚太市场参考
    """
    result = {}
    try:
        # 方案1：从全球指数获取亚太市场数据
        df = ak.index_global_spot_em()
        if not df.empty:
            # 获取相关亚太指数
            target_names = ['恒生指数', '富时新加坡海峡时报', '日经225']
            
            # Optimized filtering
            filtered_df = df[df['名称'].isin(target_names)]
            
            for _, r in filtered_df.iterrows():
                name = r['名称']
                result[name] = {
                    '最新价': r.get('最新价', 'N/A'),
                    '涨跌幅': r.get('涨跌幅', 'N/A'),
                    '更新时间': r.get('最新行情时间', 'N/A')
                }
    except Exception as e:
        print(f"Error fetching A50/Asia index: {e}")
    
    if not result:
        return {"说明": "A50期货数据暂时无法获取，请关注盘前竞价"}
    return result

def get_forex_rates() -> Dict:
    """
    获取关键汇率：美元/人民币

    Migration Note: Phase 5 - Hybrid strategy
    - TuShare: Daily EOD closing prices (historical data)
    - AkShare: Real-time bid/ask quotes (live data)
    """
    from config.settings import DATA_SOURCE_PROVIDER

    result = {}

    # TuShare for daily historical/EOD data
    if DATA_SOURCE_PROVIDER in ('tushare', 'hybrid'):
        try:
            from src.data_sources.data_source_manager import get_forex_rates_from_tushare
            ts_result = get_forex_rates_from_tushare()
            if ts_result:
                result.update(ts_result)
        except Exception as e:
            print(f"TuShare forex error: {e}")

    # AkShare for real-time bid/ask quotes (complement)
    try:
        df = ak.fx_spot_quote()
        if not df.empty:
            # fx_spot_quote 返回的列是: 货币对, 买报价, 卖报价
            usdcny = df[df['货币对'].str.contains('USD/CNY', na=False, case=False)]
            if not usdcny.empty:
                row = usdcny.iloc[0]
                # If TuShare provided data, augment with real-time prices
                if "美元/人民币" in result:
                    result["美元/人民币"]["实时买入价"] = row.get('买报价', 'N/A')
                    result["美元/人民币"]["实时卖出价"] = row.get('卖报价', 'N/A')
                else:
                    # Otherwise, use AkShare as primary
                    result["美元/人民币"] = {
                        "货币对": row.get('货币对', 'USD/CNY'),
                        "买入价": row.get('买报价', 'N/A'),
                        "卖出价": row.get('卖报价', 'N/A')
                    }

            # 获取其他重要汇率
            eurcny = df[df['货币对'].str.contains('EUR/CNY', na=False, case=False)]
            if not eurcny.empty:
                row = eurcny.iloc[0]
                result["欧元/人民币"] = {
                    "买入价": row.get('买报价', 'N/A'),
                    "卖出价": row.get('卖报价', 'N/A')
                }
    except Exception as e:
        print(f"Error fetching forex from AkShare: {e}")

    # 备选方案：使用百度汇率
    if not result:
        try:
            fx_data = ak.fx_quote_baidu()
            if not fx_data.empty:
                usd = fx_data[fx_data['货币'].str.contains('美元', na=False)]
                if not usd.empty:
                    result["美元/人民币"] = {"最新价": usd.iloc[0].get('现汇买入价', 'N/A')}
        except Exception as e:
            print(f"Baidu forex fallback failed: {e}")

    return result if result else {"说明": "汇率数据暂时无法获取"}

def get_global_macro_summary() -> Dict:
    """
    汇总全球宏观数据 - 盘前分析核心输入
    """
    return {
        "美股市场": get_us_market_overview(),
        "A50期货": get_a50_futures(),
        "汇率": get_forex_rates()
    }

# ============================================================================
# SECTION 2: 北向资金与资金流向 (Capital Flow)
# ============================================================================

def get_northbound_flow() -> Dict:
    """
    获取北向资金（沪股通+深股通）净流入数据
    使用 TuShare Pro 作为主要数据源，AkShare 作为后备

    Migration Note: Now uses TuShare as primary source (Phase 4)
    """
    from config.settings import DATA_SOURCE_PROVIDER

    # Use TuShare for northbound flow data
    if DATA_SOURCE_PROVIDER in ('tushare', 'hybrid'):
        try:
            from src.data_sources.data_source_manager import get_northbound_flow_from_tushare
            result = get_northbound_flow_from_tushare()
            if result:
                return result
        except Exception as e:
            print(f"TuShare northbound flow failed, falling back to AkShare: {e}")

    # Fallback to AkShare
    result = {}
    try:
        # ==========================================
        # 方案1：使用实时汇总数据（最可靠）
        # ==========================================
        df = ak.stock_hsgt_fund_flow_summary_em()
        if df is not None and not df.empty:
            # 兼容不同的列名
            direction_col = '资金方向' if '资金方向' in df.columns else ('方向' if '方向' in df.columns else None)
            net_col = None
            for col in ['成交净买额', '净买额', '净流入', '当日净流入']:
                if col in df.columns:
                    net_col = col
                    break
            board_col = '板块' if '板块' in df.columns else None
            date_col = None
            for col in ['交易日', '日期', 'trade_date']:
                if col in df.columns:
                    date_col = col
                    break

            if direction_col and net_col:
                # 筛选北向资金
                north = df[df[direction_col] == '北向']
                if not north.empty:
                    hgt_net = 0
                    sgt_net = 0

                    # 分别获取沪股通和深股通
                    if board_col:
                        hgt_rows = north[north[board_col].str.contains('沪股通', na=False)]
                        sgt_rows = north[north[board_col].str.contains('深股通', na=False)]
                        if not hgt_rows.empty:
                            try:
                                hgt_net = float(hgt_rows.iloc[0].get(net_col, 0) or 0)
                            except (ValueError, TypeError):
                                hgt_net = 0
                        if not sgt_rows.empty:
                            try:
                                sgt_net = float(sgt_rows.iloc[0].get(net_col, 0) or 0)
                            except (ValueError, TypeError):
                                sgt_net = 0

                    total_net = hgt_net + sgt_net

                    # 如果没找到分项，尝试直接遍历求和
                    if total_net == 0:
                        for _, row in north.iterrows():
                            try:
                                total_net += float(row.get(net_col, 0) or 0)
                            except (ValueError, TypeError):
                                pass

                    # 填充结果
                    if board_col:
                        for _, row in north.iterrows():
                            board = str(row.get(board_col, ''))
                            try:
                                net_buy = float(row.get(net_col, 0) or 0)
                            except (ValueError, TypeError):
                                net_buy = 0
                            result[board] = {
                                '成交净买额': f"{net_buy:.2f}亿",
                                '交易状态': '交易中' if row.get('交易状态') == 1 else '休市',
                                '相关指数': str(row.get('相关指数', 'N/A')),
                                '指数涨跌幅': f"{row.get('指数涨跌幅', 0)}%"
                            }

                    result['最新净流入'] = f"{total_net:.2f}亿"

                    # 数据日期
                    if date_col:
                        trade_date = north.iloc[0].get(date_col, 'N/A')
                        if hasattr(trade_date, 'strftime'):
                            trade_date = trade_date.strftime('%Y-%m-%d')
                        result['数据日期'] = str(trade_date)
                    else:
                        result['数据日期'] = datetime.now().strftime('%Y-%m-%d')

        # ==========================================
        # 方案2：获取历史数据计算5日累计
        # ==========================================
        try:
            # 分别获取沪股通和深股通历史数据再合并
            hgt_hist = None
            sgt_hist = None

            for symbol in ["沪股通", "深股通"]:
                try:
                    hist_df = ak.stock_hsgt_hist_em(symbol=symbol)
                    if hist_df is not None and not hist_df.empty:
                        if symbol == "沪股通":
                            hgt_hist = hist_df
                        else:
                            sgt_hist = hist_df
                except Exception as e:
                    print(f"{symbol} history fetch error: {e}")

            total_5d = 0
            if hgt_hist is not None and sgt_hist is not None:
                # 找出净流入列
                def _find_flow_col(df):
                    priority = ['当日成交净买额', '成交净买额', '当日资金流入', '当日净流入', '净买额', '净流入', '资金流入']
                    for pattern in priority:
                        for col in df.columns:
                            if pattern in col and '累计' not in col:
                                try:
                                    vals = pd.to_numeric(df[col], errors='coerce')
                                    if vals.notna().any():
                                        return col
                                except Exception:
                                    continue
                    return None

                hgt_col = _find_flow_col(hgt_hist)
                sgt_col = _find_flow_col(sgt_hist)

                if hgt_col and sgt_col:
                    # 统一日期列
                    date_col_h = '日期' if '日期' in hgt_hist.columns else hgt_hist.columns[0]
                    date_col_s = '日期' if '日期' in sgt_hist.columns else sgt_hist.columns[0]

                    hgt_hist = hgt_hist.rename(columns={date_col_h: '日期'})
                    sgt_hist = sgt_hist.rename(columns={date_col_s: '日期'})

                    hgt_hist['日期'] = pd.to_datetime(hgt_hist['日期'], errors='coerce').dt.date
                    sgt_hist['日期'] = pd.to_datetime(sgt_hist['日期'], errors='coerce').dt.date

                    hgt_hist['_flow'] = pd.to_numeric(hgt_hist[hgt_col], errors='coerce')
                    sgt_hist['_flow'] = pd.to_numeric(sgt_hist[sgt_col], errors='coerce')

                    # 按日期合并
                    merged = pd.merge(
                        hgt_hist[['日期', '_flow']].rename(columns={'_flow': 'hgt'}),
                        sgt_hist[['日期', '_flow']].rename(columns={'_flow': 'sgt'}),
                        on='日期', how='outer'
                    )
                    merged['north'] = merged['hgt'].fillna(0) + merged['sgt'].fillna(0)
                    merged = merged.sort_values('日期', ascending=False)

                    recent_5 = merged.head(5)
                    total_5d = recent_5['north'].sum()

            # 如果分别获取失败，尝试直接用"北向资金"
            if total_5d == 0:
                try:
                    direct_df = ak.stock_hsgt_hist_em(symbol="北向资金")
                    if direct_df is not None and not direct_df.empty:
                        def _find_flow_col_direct(df):
                            priority = ['当日成交净买额', '成交净买额', '当日资金流入', '当日净流入', '净买额', '净流入', '资金流入']
                            for pattern in priority:
                                for col in df.columns:
                                    if pattern in col and '累计' not in col:
                                        try:
                                            vals = pd.to_numeric(df[col], errors='coerce')
                                            if vals.notna().any():
                                                return col
                                        except Exception:
                                            continue
                            return None

                        flow_col = _find_flow_col_direct(direct_df)
                        if flow_col:
                            date_col_d = '日期' if '日期' in direct_df.columns else direct_df.columns[0]
                            direct_df = direct_df.rename(columns={date_col_d: '日期'})
                            direct_df['日期'] = pd.to_datetime(direct_df['日期'], errors='coerce').dt.date
                            direct_df['_flow'] = pd.to_numeric(direct_df[flow_col], errors='coerce')
                            direct_df = direct_df.sort_values('日期', ascending=False)
                            total_5d = direct_df.head(5)['_flow'].sum()
                except Exception as direct_e:
                    print(f"Direct northbound history error: {direct_e}")

            if total_5d != 0:
                result['5日累计净流入'] = f"{total_5d:.2f}亿"

        except Exception as e:
            print(f"Historical northbound data failed: {e}")

    except Exception as e:
        print(f"Error fetching northbound flow: {e}")
        import traceback
        traceback.print_exc()

    return result if result else {"说明": "北向资金数据暂时无法获取"}

def get_industry_capital_flow(industry: str = None) -> Dict:
    """
    获取行业资金流向

    Migration Note: Phase 5 - TuShare pro.concept_detail() as primary
    """
    from config.settings import DATA_SOURCE_PROVIDER

    # Try TuShare first (if enabled and industry specified)
    if industry and DATA_SOURCE_PROVIDER in ('tushare', 'hybrid'):
        try:
            from src.data_sources.data_source_manager import get_industry_capital_flow_from_tushare
            result = get_industry_capital_flow_from_tushare(industry)
            if result:
                return result
        except Exception as e:
            print(f"TuShare industry flow error: {e}")

    # Fallback to AkShare
    try:
        df = ak.stock_sector_fund_flow_rank()
        if not df.empty:
            if industry:
                filtered = df[df['名称'].str.contains(industry, na=False, regex=False)]
                if not filtered.empty:
                    return filtered.iloc[0].to_dict()
            # 返回前10行业
            return {"行业资金流向Top10": df.head(10).to_dict('records')}
    except Exception as e:
        print(f"Error fetching industry capital flow: {e}")
    return {}

# ============================================================================
# SECTION 3: 个股深度数据 (Stock Deep Dive)
# ============================================================================

def get_stock_announcement(stock_code: str, stock_name: str) -> List[Dict]:
    """
    获取个股最新公告（巨潮资讯）

    Migration Note: Phase 5 - TuShare pro.anns() as primary, AkShare fallback
    """
    from config.settings import DATA_SOURCE_PROVIDER

    # Try TuShare first (if enabled)
    if DATA_SOURCE_PROVIDER in ('tushare', 'hybrid'):
        try:
            from src.data_sources.data_source_manager import get_stock_announcements_from_tushare
            result = get_stock_announcements_from_tushare(stock_code, limit=5)
            if result:
                return result
        except Exception as e:
            print(f"TuShare announcements error for {stock_name}: {e}")

    # Fallback to AkShare
    announcements = []
    try:
        # 尝试获取公告 - 使用巨潮资讯接口，支持更多市场（包括北交所）
        df = ak.stock_zh_a_disclosure_report_cninfo(symbol=stock_code)
        if df is not None and not df.empty:
            # 按时间倒序排序 (API通常已排序，但也可能未排序)
            if '公告时间' in df.columns:
                 df.sort_values(by='公告时间', ascending=False, inplace=True)

            # 最近5条公告
            recent = df.head(5)
            announcements = recent.to_dict('records')
    except Exception as e:
        print(f"Error fetching announcements for {stock_name} ({stock_code}): {e}")
    return announcements


def get_stock_realtime_quote_min(stock_code: str) -> Dict:
    """
    使用分钟线数据获取最新行情（更稳定的替代方案）
    """
    from datetime import datetime, timedelta
    
    try:
        code = _normalize_a_stock_code(stock_code)
        if not code:
            return {}
        
        now = datetime.now()
        
        # 判断当前是否在交易时间内
        current_time = now.hour * 100 + now.minute
        is_trading_hours = (930 <= current_time <= 1130) or (1300 <= current_time <= 1500)
        
        if is_trading_hours:
            # 交易时间：取前5分钟到后1分钟
            start_dt = now - timedelta(minutes=5)
            end_dt = now + timedelta(minutes=1)
        else:
            # 非交易时间：取今天收盘前的数据
            if now.hour >= 15:
                # 收盘后，取14:55-15:01
                start_dt = now.replace(hour=14, minute=55, second=0)
                end_dt = now.replace(hour=15, minute=1, second=0)
            else:
                # 开盘前，取前一交易日收盘数据（用昨天的）
                yesterday = now - timedelta(days=1)
                # 如果是周一，取上周五
                if now.weekday() == 0:
                    yesterday = now - timedelta(days=3)
                start_dt = yesterday.replace(hour=14, minute=55, second=0)
                end_dt = yesterday.replace(hour=15, minute=1, second=0)
        
        start_str = start_dt.strftime('%Y-%m-%d %H:%M:%S')
        end_str = end_dt.strftime('%Y-%m-%d %H:%M:%S')
        
        df = ak.stock_zh_a_hist_min_em(
            symbol=code, 
            start_date=start_str, 
            end_date=end_str, 
            period='1', 
            adjust='hfq'
        )
        
        if df is None or df.empty:
            return {}
        
        # 获取最后一条（最新）数据
        latest = df.iloc[-1]
        
        # 获取第一条用于计算涨跌
        first_open = df.iloc[0]['开盘'] if len(df) > 0 else latest['开盘']
        
        # 计算涨跌幅和涨跌额（如果有昨收数据）
        close_price = float(latest['收盘'])
        open_price = float(latest['开盘'])
        high_price = float(latest['最高'])
        low_price = float(latest['最低'])
        
        return {
            '代码': code,
            '名称': '',  # 分钟线不包含名称
            '最新价': close_price,
            '涨跌幅': None,  # 分钟线不包含涨跌幅，需要额外计算
            '涨跌额': None,
            '成交量': int(latest['成交量']) * 100 if latest['成交量'] else None,
            '成交额': float(latest['成交额']) if latest['成交额'] else None,
            '最高': high_price,
            '最低': low_price,
            '今开': open_price,
            '昨收': None,  # 分钟线不包含昨收
            '均价': float(latest['均价']) if latest.get('均价') else None,
            '数据时间': str(latest['时间']),
        }
    except Exception as e:
        print(f"Error fetching realtime quote (min) for {stock_code}: {e}")
        import traceback
        traceback.print_exc()
        return {}


def get_stock_realtime_quote(
    stock_code: str,
    use_cache: bool = True,
    cache_ttl_seconds: int = 30,
    force_refresh: bool = False,
) -> Dict:
    """
    获取个股实时/最新行情
    Prioritizes cache, then fast single-stock fetch (bid_ask_em), then full market spot.
    """
    try:
        code = _normalize_a_stock_code(stock_code)
        if not code:
            return {}

        
        # 2. Fast Fetch (Single Stock)
        try:
            df = ak.stock_bid_ask_em(symbol=code)
            if not df.empty:
                # df columns: item, value. 
                # Keys: 最新, 涨幅, 总手, 金额, 最高, 最低, 今开, 昨收, 涨跌
                info = dict(zip(df['item'], df['value']))
                
                # Map to standard keys (compatible with stock_zh_a_spot_em)
                return {
                    '代码': code,
                    '名称': '', # Name not available in bid_ask
                    '最新价': info.get('最新'),
                    '涨跌幅': info.get('涨幅'),
                    '涨跌额': info.get('涨跌'),
                    '成交量': float(info.get('总手', 0)) * 100 if info.get('总手') else None,
                    '成交额': info.get('金额'),
                    '最高': info.get('最高'),
                    '最低': info.get('最低'),
                    '今开': info.get('今开'),
                    '昨收': info.get('昨收'),
                    # Extra fields useful for debug
                    '均价': info.get('均价'),
                    '量比': info.get('量比'),
                    '换手': info.get('换手'),
                    '涨停': info.get('涨停'),
                    '跌停': info.get('跌停'),
                    '外盘': info.get('外盘'),
                    '内盘': info.get('内盘'),
                }
        except BaseException as e:
            # print(f"Bid/Ask fetch failed for {code}: {e}") # Debug only
            pass
    except BaseException as e:
        print(f"Error fetching realtime quote for {stock_code}: {e}")
    return {}

def get_stock_news_sentiment(stock_name: str) -> List[Dict]:
    """
    获取个股相关新闻（东方财富）

    Migration Note: Phase 5 - Enhanced with web search
    - TuShare has no news API (keep using AkShare)
    - Supplement with web search when data is insufficient
    """
    results = []

    # Primary: AkShare (free and fast)
    try:
        df = ak.stock_news_em(symbol=stock_name)
        if not df.empty:
            for _, row in df.head(5).iterrows():
                results.append({
                    '标题': row.get('新闻标题', row.get('标题', '')),
                    '内容': row.get('新闻内容', row.get('内容', ''))[:200],  # Truncate
                    '发布时间': str(row.get('发布时间', row.get('时间', ''))),
                    '来源': 'AkShare-东方财富',
                    '网址': row.get('新闻链接', '')
                })
    except Exception as e:
        print(f"Error fetching news from AkShare for {stock_name}: {e}")

    # Supplement with web search if insufficient data
    if len(results) < 3:
        try:
            from src.data_sources.web_search import WebSearch
            searcher = WebSearch()

            # Use search_news method for general news
            web_results = searcher.search_news(f"{stock_name} 最新动态", max_results=5)

            for item in web_results:
                # Avoid duplicates
                if any(r.get('标题') == item.get('title') for r in results):
                    continue

                results.append({
                    '标题': item.get('title', ''),
                    '内容': item.get('content', '')[:200],
                    '发布时间': item.get('published_date', ''),
                    '来源': f"Web-{item.get('domain', 'Unknown')}",
                    '网址': item.get('url', '')
                })

                # Stop when we have enough
                if len(results) >= 10:
                    break

        except Exception as e:
            print(f"Web search supplement failed for {stock_name}: {e}")

    return results[:10]  # Max 10 results

# ============================================================================
# SECTION 4: 行业与板块数据 (Sector Data)
# ============================================================================

def get_sector_performance(sector_name: str = None) -> Dict:
    """
    获取板块行情表现
    """
    try:
        df = ak.stock_board_industry_name_em()
        if not df.empty:
            if sector_name:
                filtered = df[df['板块名称'].str.contains(sector_name, na=False, regex=False)]
                if not filtered.empty:
                    return filtered.iloc[0].to_dict()
            return {"板块涨幅榜": df.head(10).to_dict('records')}
    except Exception as e:
        print(f"Error fetching sector performance: {e}")
    return {}

def get_sector_performance_ths(sector_name: str) -> Dict:
    """
    获取同花顺行业板块表现

    Migration Note: Phase 5 - TuShare pro.ths_index() as primary
    """
    from config.settings import DATA_SOURCE_PROVIDER

    # Try TuShare first (if enabled)
    if DATA_SOURCE_PROVIDER in ('tushare', 'hybrid'):
        try:
            from src.data_sources.data_source_manager import get_sector_performance_ths_from_tushare
            result = get_sector_performance_ths_from_tushare(sector_name)
            if result:
                return result
        except Exception as e:
            print(f"TuShare THS index error for {sector_name}: {e}")

    # Fallback to AkShare
    try:
        # 1. Get all board names
        boards = ak.stock_board_industry_name_ths()
        if boards.empty:
            return {}

        target_name = None
        # Simple fuzzy match
        # If input is "半导体", match "半导体"
        # If input is "新能源", match "新能源汽车" or similar?
        # Let's try exact match first, then contains

        # Check if direct match exists
        if sector_name in boards['name'].values:
            target_name = sector_name
        else:
            # Contains
            matches = boards[boards['name'].str.contains(sector_name, na=False, regex=False)]
            if not matches.empty:
                target_name = matches.iloc[0]['name']

        if not target_name:
            return {}

        # 2. Fetch Index Data
        # akshare expects start/end date usually to reduce data
        end_date = datetime.now().strftime("%Y%m%d")
        start_date = (datetime.now() - timedelta(days=10)).strftime("%Y%m%d")

        df = ak.stock_board_industry_index_ths(symbol=target_name, start_date=start_date, end_date=end_date)

        if not df.empty:
            latest = df.iloc[-1]
            # Calculate change
            change_pct = "N/A"
            if len(df) >= 2:
                prev = df.iloc[-2]['收盘价']
                curr = latest['收盘价']
                if prev and float(prev) != 0:
                    pct = ((float(curr) - float(prev)) / float(prev)) * 100
                    change_pct = f"{pct:.2f}"

            return {
                "板块名称": target_name,
                "收盘价": latest['收盘价'],
                "涨跌幅": change_pct,
                "成交量": latest['成交量'],
                "成交额": latest['成交额'],
                "日期": latest['日期']
            }

    except Exception as e:
        print(f"Error fetching THS sector performance for {sector_name}: {e}")
    return {}

def get_concept_board_performance(concept: str = None) -> Dict:
    """
    获取概念板块表现（如：AI、新能源等）
    """
    try:
        df = ak.stock_board_concept_name_em()
        if not df.empty:
            if concept:
                filtered = df[df['板块名称'].str.contains(concept, na=False, regex=False)]
                if not filtered.empty:
                    return filtered.to_dict('records')
            return {"概念板块Top10": df.head(10).to_dict('records')}
    except Exception as e:
        print(f"Error fetching concept board: {e}")
    return {}

# ============================================================================
# SECTION 5: 原有函数（保留并优化）
# ============================================================================

def get_fund_info(fund_code: str):
    """
    Fetch basic fund information and net value history.
    Uses TuShare Pro as primary source, akshare as fallback.

    Migration Note: Now uses TuShare as primary source (Phase 4)
    """
    from config.settings import DATA_SOURCE_PROVIDER

    # Use TuShare for fund info
    if DATA_SOURCE_PROVIDER in ('tushare', 'hybrid'):
        try:
            from src.data_sources.data_source_manager import get_fund_info_from_tushare
            result = get_fund_info_from_tushare(fund_code)
            if result is not None and not result.empty:
                return result
        except Exception as e:
            print(f"TuShare fund info failed, falling back to AkShare: {e}")

    # Fallback to AkShare
    try:
        # Fetching net value history
        df = ak.fund_open_fund_info_em(symbol=fund_code, indicator="单位净值走势")

        if df is None or df.empty:
            return pd.DataFrame()

        # Expected columns: 净值日期, 单位净值, 日增长率
        # NOTE: Some environments may return mojibake column names (encoding issues).
        # To keep downstream logic stable, normalize columns when we can.
        if '净值日期' not in df.columns:
            cols = list(df.columns)
            if len(cols) >= 3:
                df = df.rename(
                    columns={
                        cols[0]: '净值日期',
                        cols[1]: '单位净值',
                        cols[2]: '日增长率',
                    }
                )

        # Sort by date descending so iloc[0] is the latest NAV
        if '净值日期' in df.columns:
            df['净值日期'] = pd.to_datetime(df['净值日期'], errors='coerce')
            df = df.sort_values('净值日期', ascending=False).reset_index(drop=True)
            # Keep a consistent display format
            df['净值日期'] = df['净值日期'].dt.date
        return df
    except Exception as e:
        print(f"Error fetching fund info for {fund_code}: {e}")
        return pd.DataFrame()

def get_fund_holdings(fund_code: str, year: str = None):
    """
    Fetch the latest top 10 holdings for the fund.
    Defaults to the current year if not specified.
    使用 TuShare Pro 作为主要数据源，AkShare 作为后备

    Migration Note: Now uses TuShare as primary source (Phase 4)
    """
    from config.settings import DATA_SOURCE_PROVIDER

    current_year = str(datetime.now().year)
    if not year:
        year = current_year

    # Use TuShare for fund holdings
    if DATA_SOURCE_PROVIDER in ('tushare', 'hybrid'):
        try:
            from src.data_sources.data_source_manager import get_fund_holdings_from_tushare
            result = get_fund_holdings_from_tushare(fund_code, year)
            if result is not None and not result.empty:
                return result
        except Exception as e:
            print(f"TuShare fund holdings failed, falling back to AkShare: {e}")

    # Fallback to AkShare
    try:
        # fund_portfolio_hold_em signature varies by AkShare version.
        # In the installed AkShare (2024/06+), it is: fund_portfolio_hold_em(symbol, date)
        sig = None
        try:
            sig = inspect.signature(ak.fund_portfolio_hold_em)
        except Exception:
            sig = None

        def _call_holdings(target_year: str):
            if sig and "symbol" in sig.parameters:
                return ak.fund_portfolio_hold_em(symbol=fund_code, date=target_year)
            # Fallback for older/newer variants: try positional to avoid keyword mismatches
            try:
                return ak.fund_portfolio_hold_em(fund_code, target_year)
            except TypeError:
                # Last-resort: try legacy keywords if positional fails
                return ak.fund_portfolio_hold_em(code=fund_code, year=target_year)

        # fund_portfolio_hold_em: returns holding details
        df = _call_holdings(year)

        # Fallback to previous year if current year is empty (common in early Jan)
        if df.empty and year == current_year:
            prev_year = str(int(year) - 1)
            print(f"DEBUG: No data for {year}, trying {prev_year}...")
            df = _call_holdings(prev_year)

        # We generally want the latest quarter available
        if not df.empty:
            # Sort by date/quarter to get the latest
            # This API usually returns all quarters for the year.
            # We might need to filter for the latest '季度'
            return df
        return df
    except Exception as e:
        print(f"Error fetching holdings for {fund_code}: {e}")
        return pd.DataFrame()

def get_market_indices():
    """
    Fetch key market indices for context (A50, Shanghai Composite, etc.)
    使用 TuShare Pro 作为主要数据源，AkShare 作为后备

    Migration Note: Now uses TuShare as primary source (Phase 4)
    """
    from config.settings import DATA_SOURCE_PROVIDER

    # Use TuShare for market indices
    if DATA_SOURCE_PROVIDER in ('tushare', 'hybrid'):
        try:
            from src.data_sources.data_source_manager import get_market_indices_from_tushare
            result = get_market_indices_from_tushare()
            if result:
                return result
        except Exception as e:
            print(f"TuShare market indices failed, falling back to AkShare: {e}")

    # Fallback to AkShare
    indices = {
        "sh000001": "上证指数",
        "sz399006": "创业板指数",
    }

    market_data: Dict[str, Dict] = {}
    try:
        for symbol, name in indices.items():
            # stock_zh_index_daily_em returns historical data
            df = ak.stock_zh_index_daily_em(symbol=symbol)
            if not df.empty:
                # Get the last row (most recent trading day)
                latest_row = df.iloc[-1]
                close = latest_row.get('close', None)
                trade_date = latest_row.get('date', None)

                pct_change = None
                if len(df) >= 2:
                    prev_close = df.iloc[-2].get('close', None)
                    try:
                        if prev_close not in (None, 0) and close is not None:
                            pct_change = (float(close) / float(prev_close) - 1.0) * 100.0
                    except Exception:
                        pct_change = None

                # Normalize fields to what the analyst code expects
                market_data[name] = {
                    '日期': trade_date,
                    '收盘': close,
                    '涨跌幅': (round(pct_change, 2) if pct_change is not None else 'N/A'),
                }
        return market_data
    except Exception as e:
        print(f"Error fetching market indices: {e}")
        return {}

def get_all_fund_list() -> List[Dict]:

    """

    获取全市场所有基金列表

    Returns: List of dicts with 'code', 'name', 'type', etc.

    """

    try:

        # fund_name_em returns: 基金代码, 基金简称, 基金类型, 拼音缩写

        df = ak.fund_name_em()

        if not df.empty:

            # Rename columns for consistency

            # 基金代码 -> code, 基金简称 -> name, 基金类型 -> type, 拼音缩写 -> pinyin

            df = df.rename(columns={

                '基金代码': 'code',

                '基金简称': 'name',

                '基金类型': 'type',

                '拼音缩写': 'pinyin'

            })

            return df[['code', 'name', 'type', 'pinyin']].to_dict('records')

    except Exception as e:

        print(f"Error fetching all fund list: {e}")

    return []



def search_funds(query: str, limit: int = 10) -> List[Dict]:

    """

    Search funds by code or name (fuzzy matching)

    """

    query = query.strip().lower()

    if not query:

        return []



    all_funds = get_all_fund_list()

    results = []

    

    # Priority 1: Exact Code Match

    for fund in all_funds:

        if fund['code'] == query:

            results.append(fund)

    

    # Priority 2: Code Starts With

    for fund in all_funds:

        if fund['code'].startswith(query) and fund not in results:

            results.append(fund)

            

    # Priority 3: Name Contains

    for fund in all_funds:

        if query in fund['name'].lower() and fund not in results:

            results.append(fund)

            

    # Priority 4: Pinyin Contains

    for fund in all_funds:

        if 'pinyin' in fund and query in str(fund['pinyin']).lower() and fund not in results:

            results.append(fund)

            

    return results[:limit]


# ============================================================================
# SECTION 6: 市场热点与涨跌停数据 (Market Hot & Limit Data)
# ============================================================================

def get_market_activity() -> Dict:
    """
    获取市场活跃度统计：涨跌家数、涨跌停数量等
    """
    result = {}
    try:
        df = ak.stock_market_activity_legu()
        if df is not None and not df.empty:
            # 转换为字典格式
            for _, row in df.iterrows():
                item = row.get('item', '')
                value = row.get('value', 0)
                result[item] = value
    except Exception as e:
        print(f"Error fetching market activity: {e}")
    return result if result else {"说明": "市场活跃度数据暂时无法获取"}


def get_hot_stocks(limit: int = 20) -> List[Dict]:
    """
    获取热门股票排行榜（东方财富人气榜）
    """
    result = []
    try:
        df = ak.stock_hot_rank_em()
        if df is not None and not df.empty:
            df = df.head(limit)
            for _, row in df.iterrows():
                code = str(row.get('代码', ''))
                # 去掉 SH/SZ 前缀
                if code.startswith('SH') or code.startswith('SZ'):
                    code = code[2:]
                result.append({
                    'rank': int(row.get('当前排名', 0)),
                    'code': code,
                    'name': row.get('股票名称', ''),
                    'price': float(row.get('最新价', 0)),
                    'change': float(row.get('涨跌额', 0)),
                    'change_pct': float(row.get('涨跌幅', 0)),
                })
    except Exception as e:
        print(f"Error fetching hot stocks: {e}")
    return result


def get_limit_up_pool(date: str = None, limit: int = 30) -> List[Dict]:
    """
    获取涨停池数据
    
    Args:
        date: 日期字符串，格式 YYYYMMDD，默认为今天
        limit: 返回数量限制
    """
    from datetime import datetime
    if date is None:
        date = datetime.now().strftime('%Y%m%d')
    
    result = []
    try:
        df = ak.stock_zt_pool_em(date)
        if df is not None and not df.empty:
            df = df.head(limit)
            for _, row in df.iterrows():
                result.append({
                    'rank': int(row.get('序号', 0)),
                    'code': str(row.get('代码', '')),
                    'name': str(row.get('名称', '')),
                    'price': float(row.get('最新价', 0)),
                    'change_pct': float(row.get('涨跌幅', 0)),
                    'amount': float(row.get('成交额', 0)),
                    'market_cap': float(row.get('流通市值', 0)),
                    'turnover': float(row.get('换手率', 0)),
                    'seal_money': float(row.get('封板资金', 0)),
                    'first_seal_time': str(row.get('首次封板时间', '')),
                    'last_seal_time': str(row.get('最后封板时间', '')),
                    'open_count': int(row.get('炸板次数', 0)),
                    'limit_stats': str(row.get('涨停统计', '')),
                    'consecutive': int(row.get('连板数', 0)),
                    'industry': str(row.get('所属行业', '')),
                })
    except Exception as e:
        print(f"Error fetching limit up pool: {e}")
    return result


def get_limit_down_pool(date: str = None, limit: int = 30) -> List[Dict]:
    """
    获取跌停池数据
    
    Args:
        date: 日期字符串，格式 YYYYMMDD，默认为今天
        limit: 返回数量限制
    """
    from datetime import datetime
    if date is None:
        date = datetime.now().strftime('%Y%m%d')
    
    result = []
    try:
        df = ak.stock_zt_pool_dtgc_em(date)
        if df is not None and not df.empty:
            df = df.head(limit)
            for _, row in df.iterrows():
                result.append({
                    'rank': int(row.get('序号', 0)),
                    'code': str(row.get('代码', '')),
                    'name': str(row.get('名称', '')),
                    'price': float(row.get('最新价', 0)),
                    'change_pct': float(row.get('涨跌幅', 0)),
                    'amount': float(row.get('成交额', 0)),
                    'market_cap': float(row.get('流通市值', 0)),
                    'turnover': float(row.get('换手率', 0)),
                    'seal_money': float(row.get('封单资金', 0)),
                    'last_seal_time': str(row.get('最后封板时间', '')),
                    'consecutive': int(row.get('连续跌停', 0)),
                    'open_count': int(row.get('开板次数', 0)),
                    'industry': str(row.get('所属行业', '')),
                })
    except Exception as e:
        print(f"Error fetching limit down pool: {e}")
    return result


def get_stock_changes(limit: int = 20) -> List[Dict]:
    """
    获取盘中异动股票
    """
    result = []
    try:
        df = ak.stock_changes_em(symbol="大笔买入")
        if df is not None and not df.empty:
            df = df.head(limit)
            for _, row in df.iterrows():
                code = str(row.get('代码', ''))
                result.append({
                    'time': str(row.get('时间', '')),
                    'code': code,
                    'name': str(row.get('名称', '')),
                    'event': str(row.get('板块', '')),
                    'price': float(row.get('相关信息', 0)) if row.get('相关信息') else 0,
                })
    except Exception as e:
        print(f"Error fetching stock changes: {e}")
    return result
