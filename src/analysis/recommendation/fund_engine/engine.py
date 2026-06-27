"""
Fund Recommendation Engine - Orchestrates factor computation and strategy scoring.

This engine:
1. Computes all factors (performance, risk, manager)
2. Applies strategy weights (momentum or alpha)
3. Generates ranked recommendations
4. Integrates with factor cache for performance
"""
from typing import Dict, List, Optional
from datetime import datetime

from src.data_sources.tushare_client import (
    get_latest_trade_date,
    format_date_yyyymmdd,
)
from src.storage.db import get_db_connection
from ..factor_store.cache import factor_cache

from .factors.performance import PerformanceFactors
from .factors.risk import RiskFactors
from .factors.manager import ManagerFactors
from .strategies.momentum import MomentumStrategy, get_momentum_recommendation
from .strategies.alpha import AlphaStrategy, get_alpha_recommendation


class FundRecommendationEngine:
    """
    Fund recommendation engine that orchestrates factor computation
    and strategy-based scoring.
    """

    DEFAULT_TOP_N = 20
    MIN_SCORE_SHORT = 55
    MIN_SCORE_LONG = 55

    def __init__(self):
        self._last_compute_time = None

    def compute_factors(
        self,
        fund_code: str,
        trade_date: str = None,
        use_cache: bool = True
    ) -> Dict:
        """
        Compute all factors for a single fund.

        Args:
            fund_code: Fund code
            trade_date: Trade date (default: latest trade date)
            use_cache: Whether to use cached factors

        Returns:
            Dict containing all computed factors
        """
        # Clean fund code (remove suffix if present)
        code = fund_code.split('.')[0] if '.' in fund_code else fund_code

        if not trade_date:
            trade_date = get_latest_trade_date()
            if not trade_date:
                trade_date = format_date_yyyymmdd()

        trade_date_db = f"{trade_date[:4]}-{trade_date[4:6]}-{trade_date[6:8]}"

        # Check cache first
        if use_cache:
            cached = factor_cache.get_fund_factors(code, trade_date_db)
            if cached:
                return cached

        # Compute all factor groups
        performance = PerformanceFactors.compute(code, trade_date)
        risk = RiskFactors.compute(code, trade_date)
        manager = ManagerFactors.compute(code, trade_date)

        # Merge factors
        factors = {
            **performance,
            **risk,
            **manager,
        }

        # Compute composite scores
        factors['short_term_score'] = MomentumStrategy.compute_score(factors)
        factors['long_term_score'] = AlphaStrategy.compute_score(factors)

        # Cache the result
        if use_cache:
            factor_cache.set_fund_factors(code, trade_date_db, factors)

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
        Get fund recommendations based on strategy.

        Args:
            strategy: 'short_term' (momentum) or 'long_term' (alpha)
            top_n: Number of top funds to return
            trade_date: Trade date
            min_score: Minimum score threshold
            use_cache: Whether to use cached factors

        Returns:
            List of recommendation dicts sorted by score
        """
        import time
        start_time = time.time()
        print(f"[FundEngine] get_recommendations started: strategy={strategy}, top_n={top_n}")

        if top_n is None:
            top_n = self.DEFAULT_TOP_N

        if min_score is None:
            min_score = self.MIN_SCORE_SHORT if strategy == 'short_term' else self.MIN_SCORE_LONG

        if not trade_date:
            trade_date = get_latest_trade_date()
            if not trade_date:
                trade_date = format_date_yyyymmdd()

        trade_date_db = f"{trade_date[:4]}-{trade_date[4:6]}-{trade_date[6:8]}"
        print(f"[FundEngine] Using trade_date_db={trade_date_db}")

        # Get top funds from cache/database
        cache_start = time.time()
        cached_factors = factor_cache.get_top_funds(
            trade_date_db,
            score_type=strategy,
            limit=top_n * 2,
            min_score=min_score
        )
        print(f"[FundEngine] Cache query took {time.time() - cache_start:.2f}s, found {len(cached_factors) if cached_factors else 0} funds")

        # IMPORTANT: Do NOT compute on-demand - factors should be pre-computed by scheduled task
        # If cache is empty, try fallback data source
        if not cached_factors:
            print(f"[FundEngine] WARNING: No cached fund factors for {trade_date_db}. Using fallback data source.")
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

            # Get fund info
            fund_info = self._get_fund_info(code)

            if strategy == 'short_term':
                rec = get_momentum_recommendation(factors, include_reasoning=True)
            else:
                rec = get_alpha_recommendation(factors, include_reasoning=True)

            rec.update({
                'code': code,
                'name': fund_info.get('name', ''),
                'type': fund_info.get('type', ''),
                'trade_date': trade_date_db,
                'factors': {
                    'sharpe_1y': factors.get('sharpe_1y'),
                    'sharpe_20d': factors.get('sharpe_20d'),
                    'max_drawdown_1y': factors.get('max_drawdown_1y'),
                    'return_1y': factors.get('return_1y'),
                    'return_1m': factors.get('return_1m'),
                    'return_1w': factors.get('return_1w'),
                    'volatility_60d': factors.get('volatility_60d'),
                    'manager_tenure_years': factors.get('manager_tenure_years'),
                    'momentum_score': factors.get('short_term_score'),
                    'alpha_score': factors.get('long_term_score'),
                }
            })

            recommendations.append(rec)

            if len(recommendations) >= top_n:
                break

        recommendations.sort(key=lambda x: x['score'], reverse=True)

        print(f"[FundEngine] get_recommendations completed in {time.time() - start_time:.2f}s, returning {len(recommendations)} funds")
        return recommendations[:top_n]

    def _compute_on_demand(
        self,
        trade_date: str,
        strategy: str,
        limit: int = 40
    ) -> List[Dict]:
        """
        Compute fund factors on-demand when cache is empty.

        Uses active user funds from the database.
        """
        print(f"Fund cache empty, computing factors on-demand...")

        # Get active funds from database
        conn = get_db_connection()
        results = conn.execute(
            "SELECT DISTINCT code FROM funds WHERE is_active = 1 LIMIT ?",
            (limit,)
        ).fetchall()
        conn.close()

        codes = [r[0] for r in results] if results else []

        if not codes:
            print("No active funds found for on-demand computation")
            return []

        computed_factors = []
        score_key = 'short_term_score' if strategy == 'short_term' else 'long_term_score'

        for code in codes:
            try:
                factors = self.compute_factors(code, trade_date, use_cache=True)
                if factors and factors.get(score_key, 0) > 0:
                    factors['code'] = code
                    computed_factors.append(factors)
            except Exception as e:
                print(f"Error computing factors for fund {code}: {e}")
                continue

        # Sort by strategy score
        computed_factors.sort(key=lambda x: x.get(score_key, 0), reverse=True)

        print(f"Computed factors for {len(computed_factors)} funds on-demand")
        return computed_factors

    def get_single_recommendation(
        self,
        fund_code: str,
        strategy: str = 'short_term',
        trade_date: str = None
    ) -> Dict:
        """
        Get recommendation for a single fund.

        Args:
            fund_code: Fund code
            strategy: 'short_term' or 'long_term'
            trade_date: Trade date

        Returns:
            Recommendation dict with full details
        """
        code = fund_code.split('.')[0] if '.' in fund_code else fund_code

        if not trade_date:
            trade_date = get_latest_trade_date()
            if not trade_date:
                trade_date = format_date_yyyymmdd()

        # Compute factors
        factors = self.compute_factors(fund_code, trade_date)

        # Get fund info
        fund_info = self._get_fund_info(code)

        # Generate recommendation
        if strategy == 'short_term':
            rec = get_momentum_recommendation(factors, include_reasoning=True)
        else:
            rec = get_alpha_recommendation(factors, include_reasoning=True)

        rec.update({
            'code': code,
            'name': fund_info.get('name', ''),
            'type': fund_info.get('type', ''),
            'trade_date': f"{trade_date[:4]}-{trade_date[4:6]}-{trade_date[6:8]}",
            'all_factors': factors,
        })

        return rec

    def compare_funds(
        self,
        codes: List[str],
        strategy: str = 'short_term',
        trade_date: str = None
    ) -> List[Dict]:
        """
        Compare multiple funds side by side.

        Args:
            codes: List of fund codes
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

    def _get_fund_info(self, code: str) -> Dict:
        """Get basic fund information from database."""
        conn = get_db_connection()

        # Try user's funds table first
        result = conn.execute(
            "SELECT name, style FROM funds WHERE code = ?",
            (code,)
        ).fetchone()

        if result and result[0]:
            conn.close()
            return {'name': result[0], 'type': result[1] or ''}

        # Fallback to fund_basic table (market funds)
        result = conn.execute(
            "SELECT name, fund_type FROM fund_basic WHERE code = ?",
            (code,)
        ).fetchone()

        if result and result[0]:
            conn.close()
            return {'name': result[0], 'type': result[1] or ''}

        conn.close()
        return {'name': code, 'type': ''}  # Use code as name if not found

    def _get_fallback_recommendations(
        self,
        strategy: str = 'short_term',
        top_n: int = 20,
        min_score: float = 55
    ) -> List[Dict]:
        """
        Fallback recommendation generator using AkShare fund ranking data when factor cache is empty.

        Uses fund performance rankings to generate basic recommendations.
        Multi-source fallback: fund_open_fund_rank_em -> individual fund history
        """
        try:
            import akshare as ak
            import pandas as pd
            import numpy as np
            from datetime import datetime

            print(f"[FundEngine] Generating fallback recommendations using AkShare...")

            try:
                rank_df = ak.fund_open_fund_rank_em(symbol="全部")
            except Exception as e:
                print(f"[FundEngine] Fallback: Failed to fetch fund ranking: {e}")
                return []

            if rank_df is None or rank_df.empty:
                print("[FundEngine] Fallback: No fund ranking data")
                return []

            recommendations = []
            count = 0

            for _, row in rank_df.iterrows():
                if count >= top_n * 3:
                    break

                try:
                    code = str(row.get('基金代码', ''))
                    name = str(row.get('基金简称', ''))

                    if not code or len(code) != 6:
                        continue

                    return_1w = row.get('近1周', 0)
                    return_1m = row.get('近1月', 0)
                    return_3m = row.get('近3月', 0)
                    return_6m = row.get('近6月', 0)
                    return_1y = row.get('近1年', 0)
                    return_2y = row.get('近2年', 0)
                    return_3y = row.get('近3年', 0)
                    nav = row.get('单位净值', 0)
                    daily_growth = row.get('日增长率', 0)
                    fund_type = row.get('基金类型', '')

                    return_1w = float(return_1w) if pd.notna(return_1w) else 0.0
                    return_1m = float(return_1m) if pd.notna(return_1m) else 0.0
                    return_3m = float(return_3m) if pd.notna(return_3m) else 0.0
                    return_6m = float(return_6m) if pd.notna(return_6m) else 0.0
                    return_1y = float(return_1y) if pd.notna(return_1y) else 0.0
                    return_2y = float(return_2y) if pd.notna(return_2y) else None
                    return_3y = float(return_3y) if pd.notna(return_3y) else None
                    nav = float(nav) if pd.notna(nav) else None

                    # 从不同区间收益率估算波动率和夏普比率
                    # 使用近1月、近3月、近6月、近1年的收益率变化来估算波动率
                    returns_list = []
                    if return_1w is not None:
                        returns_list.append(return_1w)
                    if return_1m is not None:
                        returns_list.append(return_1m)
                    if return_3m is not None:
                        returns_list.append(return_3m)
                    if return_6m is not None:
                        returns_list.append(return_6m)
                    if return_1y is not None:
                        returns_list.append(return_1y)

                    # 从不同区间收益率估算波动率和夏普比率
                    volatility_60d = None
                    sharpe_20d = None
                    sharpe_1y = None
                    sortino_1y = None
                    max_drawdown_1y = None

                    if len(returns_list) >= 2 and return_1y is not None:
                        # 用年化收益率反推合理的波动率范围
                        # 经验法则：
                        # - 债券型基金：年化波动率 5%-10%，年化收益 3%-8%
                        # - 混合型基金：年化波动率 15%-25%，年化收益 10%-30%
                        # - 股票型/行业基金：年化波动率 25%-45%，年化收益 30%+
                        annual_return = abs(return_1y)
                        if annual_return > 200:
                            # 超高收益（200%+），通常是集中持仓或行业beta
                            base_vol = 40 + min((annual_return - 200) * 0.05, 15)
                        elif annual_return > 100:
                            # 高收益（100%-200%），行业主题基金
                            base_vol = 30 + (annual_return - 100) * 0.1
                        elif annual_return > 50:
                            # 中高收益（50%-100%），偏股型
                            base_vol = 22 + (annual_return - 50) * 0.16
                        elif annual_return > 20:
                            # 中等收益（20%-50%），平衡型
                            base_vol = 15 + (annual_return - 20) * 0.23
                        elif annual_return > 8:
                            # 稳健收益（8%-20%），偏债混合
                            base_vol = 8 + (annual_return - 8) * 0.54
                        else:
                            # 低收益（8%以下），债券型
                            base_vol = max(3, annual_return * 0.8)

                        # 60日波动率约为年化波动率的 sqrt(60/252) ≈ 49%
                        volatility_60d = round(base_vol * 0.49, 2)

                        # 估算夏普比率（无风险利率按2%年化计）
                        # 正常范围：0.5以下=差，1左右=良好，2+=优秀
                        if base_vol > 0:
                            sharpe_1y = round(float((return_1y - 2) / base_vol), 2)
                            sharpe_20d = round(float(sharpe_1y * 0.3), 2)
                            # 索提诺比率（Sortino），通常约为夏普的1.3-1.8倍
                            sortino_1y = round(float(sharpe_1y * 1.5), 2)

                        # 估算最大回撤（经验值：约为年化波动率的 1.5-3 倍）
                        # 收益越高，回撤往往越大（因为波动大）
                        if return_1y > 50:
                            max_dd = base_vol * 2.5
                        elif return_1y > 0:
                            max_dd = base_vol * 2.0
                        else:
                            max_dd = base_vol * 3.0
                        max_drawdown_1y = round(min(max_dd, 70), 2)  # 最大不超过70%

                    score = 50.0
                    reasons = []

                    if strategy == 'short_term':
                        if return_1m > 5:
                            score += 20
                            reasons.append("近1月收益优秀")
                        elif return_1m > 3:
                            score += 15
                            reasons.append("近1月收益良好")
                        elif return_1m > 0:
                            score += 8
                            reasons.append("近1月正收益")
                        else:
                            score -= 5
                            reasons.append("近1月收益为负")

                        if return_3m > 10:
                            score += 10
                            reasons.append("近3月趋势向好")
                        elif return_3m > 5:
                            score += 5

                        # 波动率调整
                        if volatility_60d is not None and volatility_60d < 10:
                            score += 5
                            reasons.append("波动较小")
                    else:
                        if return_1y > 30:
                            score += 25
                            reasons.append("近1年收益优秀")
                        elif return_1y > 15:
                            score += 18
                            reasons.append("近1年收益良好")
                        elif return_1y > 5:
                            score += 10
                            reasons.append("近1年正收益")
                        else:
                            score -= 5

                        if return_6m > 15:
                            score += 8
                            reasons.append("近6月表现稳定")

                        # 夏普比率加分
                        if sharpe_1y is not None and sharpe_1y > 1.5:
                            score += 8
                            reasons.append("风险调整收益优秀")
                        elif sharpe_1y is not None and sharpe_1y > 1:
                            score += 5

                    if return_1m > 0 and return_3m > 0:
                        score += 5
                        reasons.append("短期中期均为正收益")

                    score = max(0, min(100, score))

                    if score < min_score:
                        continue

                    rec = {
                        'code': code,
                        'name': name,
                        'type': fund_type,
                        'score': round(score, 1),
                        'trade_date': datetime.now().strftime('%Y-%m-%d'),
                        'recommendation': '关注' if score >= 70 else '观望',
                        'time_horizon': '1-3个月' if strategy == 'short_term' else '6-12个月',
                        'risk_level': '中等',
                        'key_reasons': reasons[:3],
                        'investment_logic': f"综合得分{score:.0f}分。{'、'.join(reasons[:3])}。建议{'1-3个月' if strategy == 'short_term' else '6-12个月'}持有。",
                        'factors': {
                            'return_1w': return_1w,
                            'return_1m': return_1m,
                            'return_3m': return_3m,
                            'return_6m': return_6m,
                            'return_1y': return_1y,
                            'nav': nav,
                            'daily_growth': float(daily_growth) if pd.notna(daily_growth) else 0,
                            'sharpe_1y': sharpe_1y,
                            'sharpe_20d': sharpe_20d,
                            'sortino_1y': sortino_1y,
                            'volatility_60d': volatility_60d,
                            'max_drawdown_1y': max_drawdown_1y,
                            'momentum_score': round(score, 1),
                            'alpha_score': round(score * 0.9, 1),
                        },
                        'is_fallback': True,
                    }
                    recommendations.append(rec)
                    count += 1

                except Exception as e:
                    print(f"[FundEngine] Fallback: Error processing fund row: {e}")
                    continue

            recommendations.sort(key=lambda x: x['score'], reverse=True)
            print(f"[FundEngine] Fallback: Generated {len(recommendations)} recommendations")
            return recommendations[:top_n]

        except Exception as e:
            print(f"[FundEngine] Fallback recommendations failed: {e}")
            import traceback
            traceback.print_exc()
            return []


# Convenience functions

def get_momentum_picks(top_n: int = 20, trade_date: str = None) -> List[Dict]:
    """Get top short-term momentum fund picks."""
    engine = FundRecommendationEngine()
    return engine.get_recommendations(
        strategy='short_term',
        top_n=top_n,
        trade_date=trade_date
    )


def get_alpha_picks(top_n: int = 20, trade_date: str = None) -> List[Dict]:
    """Get top long-term alpha fund picks."""
    engine = FundRecommendationEngine()
    return engine.get_recommendations(
        strategy='long_term',
        top_n=top_n,
        trade_date=trade_date
    )


def analyze_fund(code: str, trade_date: str = None) -> Dict:
    """
    Comprehensive analysis of a single fund.

    Returns both short-term and long-term recommendations.
    """
    engine = FundRecommendationEngine()

    short_term = engine.get_single_recommendation(code, 'short_term', trade_date)
    long_term = engine.get_single_recommendation(code, 'long_term', trade_date)

    return {
        'code': code,
        'name': short_term.get('name', ''),
        'type': short_term.get('type', ''),
        'trade_date': short_term.get('trade_date', ''),
        'short_term': short_term,
        'long_term': long_term,
        'factors': short_term.get('all_factors', {}),
    }
