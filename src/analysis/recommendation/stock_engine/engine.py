"""
Stock Recommendation Engine - Orchestrates factor computation and strategy scoring.

This engine:
1. Computes all factors (technical, fundamental, sentiment)
2. Applies strategy weights (short-term or long-term)
3. Generates ranked recommendations
4. Integrates with factor cache for performance
"""
from typing import Dict, List, Optional, Tuple
from datetime import datetime, date
import time

from src.data_sources.tushare_client import (
    normalize_ts_code,
    denormalize_ts_code,
    get_latest_trade_date,
    format_date_yyyymmdd,
)
from src.storage.db import get_db_connection
from ..factor_store.cache import factor_cache

from .factors.technical import TechnicalFactors
from .factors.fundamental import FundamentalFactors
from .factors.sentiment import SentimentFactors
from .strategies.short_term import ShortTermStrategy, get_short_term_recommendation
from .strategies.long_term import LongTermStrategy, get_long_term_recommendation, passes_quality_gate


class StockRecommendationEngine:
    """
    Stock recommendation engine that orchestrates factor computation
    and strategy-based scoring.
    """

    # Default recommendation limits
    DEFAULT_TOP_N = 20
    MIN_SCORE_SHORT = 60
    MIN_SCORE_LONG = 60

    def __init__(self):
        self._last_compute_time = None

    def compute_factors(
        self,
        ts_code: str,
        trade_date: str = None,
        use_cache: bool = True
    ) -> Dict:
        """
        Compute all factors for a single stock.

        Args:
            ts_code: Stock code
            trade_date: Trade date (default: latest trade date)
            use_cache: Whether to use cached factors

        Returns:
            Dict containing all computed factors
        """
        ts_code = normalize_ts_code(ts_code)
        code = denormalize_ts_code(ts_code)

        if not trade_date:
            trade_date = get_latest_trade_date()
            if not trade_date:
                trade_date = format_date_yyyymmdd()

        # Convert to DB format for cache
        trade_date_db = f"{trade_date[:4]}-{trade_date[4:6]}-{trade_date[6:8]}"

        # Check cache first
        if use_cache:
            cached = factor_cache.get_stock_factors(code, trade_date_db)
            if cached:
                return cached

        # Compute all factor groups
        technical = TechnicalFactors.compute(ts_code, trade_date)
        fundamental = FundamentalFactors.compute(ts_code, trade_date)
        sentiment = SentimentFactors.compute(ts_code, trade_date)

        # Merge factors
        factors = {
            **technical,
            **fundamental,
            **sentiment,
        }

        # Compute composite scores
        factors['short_term_score'] = ShortTermStrategy.compute_score(factors)
        factors['long_term_score'] = LongTermStrategy.compute_score(factors)

        # Cache the result
        if use_cache:
            factor_cache.set_stock_factors(code, trade_date_db, factors)

        return factors

    def get_recommendations(
        self,
        strategy: str = 'short_term',
        top_n: int = None,
        trade_date: str = None,
        min_score: float = None,
        use_cache: bool = True
    ) -> List[Dict]:
        """
        Get stock recommendations based on strategy.

        Args:
            strategy: 'short_term' or 'long_term'
            top_n: Number of top stocks to return
            trade_date: Trade date
            min_score: Minimum score threshold
            use_cache: Whether to use cached factors

        Returns:
            List of recommendation dicts sorted by score
        """
        import time
        start_time = time.time()
        print(f"[StockEngine] get_recommendations started: strategy={strategy}, top_n={top_n}")

        if top_n is None:
            top_n = self.DEFAULT_TOP_N

        if min_score is None:
            min_score = self.MIN_SCORE_SHORT if strategy == 'short_term' else self.MIN_SCORE_LONG

        if not trade_date:
            trade_date = get_latest_trade_date()
            if not trade_date:
                trade_date = format_date_yyyymmdd()

        trade_date_db = f"{trade_date[:4]}-{trade_date[4:6]}-{trade_date[6:8]}"
        print(f"[StockEngine] Using trade_date_db={trade_date_db}")

        # Get top stocks from cache/database
        cache_start = time.time()
        cached_factors = factor_cache.get_top_stocks(
            trade_date_db,
            score_type=strategy,
            limit=top_n * 2,  # Get more to filter
            min_score=min_score
        )
        print(f"[StockEngine] Cache query took {time.time() - cache_start:.2f}s, found {len(cached_factors) if cached_factors else 0} stocks")

        if not cached_factors:
            print(f"[StockEngine] WARNING: No cached stock factors for {trade_date_db}. Using fallback data source.")
            fallback_recs = self._get_fallback_recommendations(strategy, top_n, min_score)
            if fallback_recs:
                return fallback_recs
            return []

        recommendations = []

        for factors in cached_factors:
            code = factors.get('code', '')
            score = factors.get(f'{strategy}_score', 0)

            if score < min_score:
                continue

            # Get stock info
            stock_info = self._get_stock_info(code)

            if strategy == 'short_term':
                rec = get_short_term_recommendation(factors, include_reasoning=True)
            else:
                # Long-term: Apply quality gate
                if not passes_quality_gate(factors):
                    continue
                rec = get_long_term_recommendation(factors, include_reasoning=True)

            rec.update({
                'code': code,
                'name': stock_info.get('name', ''),
                'industry': stock_info.get('industry', ''),
                'trade_date': trade_date_db,
                'factors': {
                    'roe': factors.get('roe'),
                    'peg_ratio': factors.get('peg_ratio'),
                    'pe_percentile': factors.get('pe_percentile'),
                    'consolidation_score': factors.get('consolidation_score'),
                    'volume_precursor': factors.get('volume_precursor'),
                    'main_inflow_5d': factors.get('main_inflow_5d'),
                    'quality_score': factors.get('quality_score'),
                    'change_pct': factors.get('change_pct'),
                    'price': factors.get('price'),
                }
            })

            recommendations.append(rec)

            if len(recommendations) >= top_n:
                break

        # Sort by score
        recommendations.sort(key=lambda x: x['score'], reverse=True)

        print(f"[StockEngine] get_recommendations completed in {time.time() - start_time:.2f}s, returning {len(recommendations)} stocks")
        return recommendations[:top_n]

    def get_single_recommendation(
        self,
        ts_code: str,
        strategy: str = 'short_term',
        trade_date: str = None
    ) -> Dict:
        """
        Get recommendation for a single stock.

        Args:
            ts_code: Stock code
            strategy: 'short_term' or 'long_term'
            trade_date: Trade date

        Returns:
            Recommendation dict with full details
        """
        ts_code = normalize_ts_code(ts_code)
        code = denormalize_ts_code(ts_code)

        if not trade_date:
            trade_date = get_latest_trade_date()
            if not trade_date:
                trade_date = format_date_yyyymmdd()

        # Compute factors
        factors = self.compute_factors(ts_code, trade_date)

        # Get stock info
        stock_info = self._get_stock_info(code)

        # Generate recommendation
        if strategy == 'short_term':
            rec = get_short_term_recommendation(factors, include_reasoning=True)
        else:
            rec = get_long_term_recommendation(factors, include_reasoning=True)
            rec['passes_quality_gate'] = passes_quality_gate(factors)

        rec.update({
            'code': code,
            'name': stock_info.get('name', ''),
            'industry': stock_info.get('industry', ''),
            'trade_date': f"{trade_date[:4]}-{trade_date[4:6]}-{trade_date[6:8]}",
            'all_factors': factors,
        })

        return rec

    def compare_stocks(
        self,
        codes: List[str],
        strategy: str = 'short_term',
        trade_date: str = None
    ) -> List[Dict]:
        """
        Compare multiple stocks side by side.

        Args:
            codes: List of stock codes
            strategy: Strategy to use for scoring
            trade_date: Trade date

        Returns:
            List of recommendations sorted by score
        """
        recommendations = []

        for code in codes:
            rec = self.get_single_recommendation(code, strategy, trade_date)
            recommendations.append(rec)

        recommendations.sort(key=lambda x: x['score'], reverse=True)

        return recommendations

    def _get_stock_info(self, code: str) -> Dict:
        """Get basic stock information from database."""
        conn = get_db_connection()
        result = conn.execute(
            "SELECT name, industry FROM stock_basic WHERE symbol = ? OR ts_code LIKE ?",
            (code, f"{code}.%")
        ).fetchone()
        conn.close()

        if result:
            return {'name': result[0], 'industry': result[1]}
        return {'name': '', 'industry': ''}

    def _get_fallback_recommendations(
        self,
        strategy: str = 'short_term',
        top_n: int = 20,
        min_score: float = 60
    ) -> List[Dict]:
        """
        Fallback recommendation generator using AkShare hot stocks when factor cache is empty.

        Uses hot stock lists and simple technical indicators to generate basic recommendations.
        """
        try:
            from src.data_sources.akshare_api import get_hot_stocks, get_limit_up_pool, get_all_stock_spot_map
            from src.data_sources.technical_analysis import (
                calculate_rsi,
                calculate_macd,
                calculate_bollinger_bands
            )
            import akshare as ak
            import pandas as pd
            from datetime import datetime, timedelta

            print(f"[StockEngine] Generating fallback recommendations using AkShare...")

            hot_stocks = get_hot_stocks(limit=top_n * 2)
            if not hot_stocks:
                print("[StockEngine] Fallback: No hot stocks available either")
                return []

            recommendations = []
            end_date = datetime.now().strftime('%Y%m%d')
            start_date = (datetime.now() - timedelta(days=60)).strftime('%Y%m%d')

            for stock in hot_stocks:
                code = stock.get('code', '')
                name = stock.get('name', '')
                change_pct = stock.get('change_pct', 0)

                if not code or len(code) != 6:
                    continue

                try:
                    hist_df = ak.stock_zh_a_hist(
                        symbol=code,
                        period="daily",
                        start_date=start_date,
                        end_date=end_date,
                        adjust="qfq"
                    )

                    if hist_df is None or hist_df.empty or len(hist_df) < 20:
                        continue

                    hist_df = hist_df.sort_values('日期').reset_index(drop=True)
                    close = pd.to_numeric(hist_df['收盘'], errors='coerce')
                    high = pd.to_numeric(hist_df['最高'], errors='coerce')
                    low = pd.to_numeric(hist_df['最低'], errors='coerce')
                    volume = pd.to_numeric(hist_df['成交量'], errors='coerce')

                    latest_close = float(close.iloc[-1])
                    latest_volume = float(volume.iloc[-1])
                    avg_volume_20 = float(volume.tail(20).mean())

                    rsi_14 = calculate_rsi(close, 14)
                    dif, dea, macd = calculate_macd(close)
                    boll_upper, boll_mid, boll_lower = calculate_bollinger_bands(close)

                    latest_rsi = float(rsi_14.iloc[-1]) if pd.notna(rsi_14.iloc[-1]) else 50
                    latest_dif = float(dif.iloc[-1]) if pd.notna(dif.iloc[-1]) else 0
                    latest_dea = float(dea.iloc[-1]) if pd.notna(dea.iloc[-1]) else 0
                    latest_macd = float(macd.iloc[-1]) if pd.notna(macd.iloc[-1]) else 0
                    latest_boll_upper = float(boll_upper.iloc[-1]) if pd.notna(boll_upper.iloc[-1]) else latest_close * 1.1
                    latest_boll_lower = float(boll_lower.iloc[-1]) if pd.notna(boll_lower.iloc[-1]) else latest_close * 0.9
                    latest_boll_mid = float(boll_mid.iloc[-1]) if pd.notna(boll_mid.iloc[-1]) else latest_close

                    score = 50.0
                    reasons = []

                    if 40 <= latest_rsi <= 60:
                        score += 10
                        reasons.append("RSI处于中性区间")
                    elif 30 <= latest_rsi < 40:
                        score += 15
                        reasons.append("RSI接近超卖区域，存在反弹可能")
                    elif latest_rsi < 30:
                        score += 5
                        reasons.append("RSI超卖，短期可能反弹")
                    elif 60 < latest_rsi <= 70:
                        score += 5
                        reasons.append("RSI偏强，趋势向好")
                    else:
                        score -= 5
                        reasons.append("RSI超买，注意回调风险")

                    if latest_dif > latest_dea:
                        score += 10
                        reasons.append("MACD金叉，多头信号")
                    elif latest_macd > 0:
                        score += 5
                        reasons.append("MACD位于零轴上方")
                    else:
                        score -= 5
                        reasons.append("MACD死叉，空头信号")

                    vol_ratio = latest_volume / avg_volume_20 if avg_volume_20 > 0 else 1
                    if vol_ratio > 1.5:
                        score += 8
                        reasons.append("成交量明显放大，资金关注")
                    elif vol_ratio > 1.2:
                        score += 4
                        reasons.append("成交量温和放大")
                    elif vol_ratio < 0.7:
                        score -= 3
                        reasons.append("成交量萎缩，关注度低")

                    boll_position = (latest_close - latest_boll_lower) / (latest_boll_upper - latest_boll_lower) * 100 if latest_boll_upper > latest_boll_lower else 50
                    if 40 <= boll_position <= 60:
                        score += 5
                        reasons.append("价格位于布林带中轨附近，震荡整理")
                    elif boll_position > 80:
                        score -= 3
                        reasons.append("价格接近布林带上轨，注意压力")
                    elif boll_position < 20:
                        score += 8
                        reasons.append("价格接近布林带下轨，支撑较强")

                    if strategy == 'short_term':
                        if change_pct > 0:
                            score += min(change_pct * 2, 10)
                        if vol_ratio > 1.3:
                            score += 5
                    else:
                        if -5 < change_pct < 5:
                            score += 5
                            reasons.append("近期走势平稳")

                    score = max(0, min(100, score))

                    if score < min_score:
                        continue

                    # 计算盘整评分：基于布林带位置，越接近中轨盘整越充分
                    consolidation_score = round(100 - abs(boll_position - 50) * 1.2, 0)
                    consolidation_score = max(0, min(100, consolidation_score))

                    # 量能信号评分：基于量比
                    volume_precursor = round(min(vol_ratio * 50, 100), 0)

                    # 估算质量评分（基于价格稳定性和趋势）
                    quality_score = round(50 + (100 - latest_rsi) * 0.3 + min(change_pct, 5) * 2, 0)
                    quality_score = max(0, min(100, quality_score))

                    # 尝试获取基本面数据（ROE、每股收益等）
                    roe = None
                    peg_ratio = None
                    pe_ttm = None

                    try:
                        fina_df = ak.stock_financial_abstract_ths(symbol=code, indicator='按报告期')
                        if fina_df is not None and not fina_df.empty and len(fina_df) > 0:
                            # 取最新一期的ROE
                            roe_col = '净资产收益率' if '净资产收益率' in fina_df.columns else None
                            eps_col = '基本每股收益' if '基本每股收益' in fina_df.columns else None

                            if roe_col:
                                roe_val = fina_df[roe_col].iloc[0]
                                if pd.notna(roe_val):
                                    # 处理带%号的字符串
                                    if isinstance(roe_val, str):
                                        roe_val = roe_val.replace('%', '')
                                    try:
                                        roe = float(roe_val)
                                    except (ValueError, TypeError):
                                        pass

                            # 估算PE：从实时行情中获取
                            try:
                                spot_map = get_all_stock_spot_map(cache_ttl_seconds=300)
                                if spot_map and code in spot_map:
                                    stock_info = spot_map[code]
                                    pe_val = stock_info.get('市盈率-动态') or stock_info.get('市盈率')
                                    if pe_val and pd.notna(pe_val):
                                        try:
                                            pe_ttm = float(pe_val)
                                        except (ValueError, TypeError):
                                            pass
                            except Exception:
                                pass

                            # 估算PEG：PE / 净利润增长率
                            if pe_ttm is not None and pe_ttm > 0:
                                growth_col = '净利润同比增长率' if '净利润同比增长率' in fina_df.columns else None
                                if growth_col:
                                    growth_val = fina_df[growth_col].iloc[0]
                                    if pd.notna(growth_val) and growth_val != False:
                                        if isinstance(growth_val, str):
                                            growth_val = growth_val.replace('%', '')
                                        try:
                                            growth = float(growth_val)
                                            if growth > 0:
                                                peg_ratio = round(pe_ttm / growth, 2)
                                        except (ValueError, TypeError):
                                            pass
                    except Exception as e:
                        pass  # 基本面数据获取失败不影响推荐

                    rec = {
                        'code': code,
                        'name': name,
                        'industry': stock.get('industry', ''),
                        'score': round(score, 1),
                        'trade_date': datetime.now().strftime('%Y-%m-%d'),
                        'recommendation': '关注' if score >= 70 else '观望',
                        'time_horizon': '7-15天' if strategy == 'short_term' else '3-6个月',
                        'risk_level': '中等',
                        'key_reasons': reasons[:3],
                        'investment_logic': f"综合得分{score:.0f}分。{'、'.join(reasons[:3])}。建议{'7-15天' if strategy == 'short_term' else '3-6个月'}持有。",
                        'factors': {
                            'rsi': round(latest_rsi, 2),
                            'macd': round(latest_macd, 4),
                            'boll_position': round(boll_position, 1),
                            'volume_ratio': round(vol_ratio, 2),
                            'change_pct': change_pct,
                            'price': latest_close,
                            'consolidation_score': consolidation_score,
                            'volume_precursor': volume_precursor,
                            'main_inflow_5d': None,
                            'quality_score': quality_score,
                            'roe': roe,
                            'peg_ratio': peg_ratio,
                            'pe_ttm': pe_ttm,
                            'pe_percentile': None,
                        },
                        'is_fallback': True,
                    }
                    recommendations.append(rec)

                except Exception as e:
                    print(f"[StockEngine] Fallback: Error processing {code}: {e}")
                    continue

                if len(recommendations) >= top_n:
                    break

            recommendations.sort(key=lambda x: x['score'], reverse=True)
            print(f"[StockEngine] Fallback: Generated {len(recommendations)} recommendations")
            return recommendations[:top_n]

        except Exception as e:
            print(f"[StockEngine] Fallback recommendations failed: {e}")
            import traceback
            traceback.print_exc()
            return []


# Convenience functions

def get_short_term_picks(top_n: int = 20, trade_date: str = None) -> List[Dict]:
    """Get top short-term stock picks."""
    engine = StockRecommendationEngine()
    return engine.get_recommendations(
        strategy='short_term',
        top_n=top_n,
        trade_date=trade_date
    )


def get_long_term_picks(top_n: int = 20, trade_date: str = None) -> List[Dict]:
    """Get top long-term stock picks."""
    engine = StockRecommendationEngine()
    return engine.get_recommendations(
        strategy='long_term',
        top_n=top_n,
        trade_date=trade_date
    )


def analyze_stock(code: str, trade_date: str = None) -> Dict:
    """
    Comprehensive analysis of a single stock.

    Returns both short-term and long-term recommendations.
    """
    engine = StockRecommendationEngine()

    short_term = engine.get_single_recommendation(code, 'short_term', trade_date)
    long_term = engine.get_single_recommendation(code, 'long_term', trade_date)

    return {
        'code': code,
        'name': short_term.get('name', ''),
        'industry': short_term.get('industry', ''),
        'trade_date': short_term.get('trade_date', ''),
        'short_term': short_term,
        'long_term': long_term,
        'factors': short_term.get('all_factors', {}),
    }
