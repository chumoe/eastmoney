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
        """
        try:
            import akshare as ak
            import pandas as pd
            from datetime import datetime

            print(f"[FundEngine] Generating fallback recommendations using AkShare...")

            try:
                # fund_open_fund_rank_em 返回全部基金排行，包含近1周/近1月/近3月/近6月/近1年等收益率
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
                if count >= top_n * 2:
                    break

                try:
                    code = str(row.get('基金代码', ''))
                    name = str(row.get('基金简称', ''))

                    if not code or len(code) != 6:
                        continue

                    return_1m = row.get('近1月', 0)
                    return_3m = row.get('近3月', 0)
                    return_6m = row.get('近6月', 0)
                    return_1y = row.get('近1年', 0)
                    nav = row.get('单位净值', 0)
                    fund_type = row.get('基金类型', '')

                    return_1m = float(return_1m) if pd.notna(return_1m) else 0.0
                    return_3m = float(return_3m) if pd.notna(return_3m) else 0.0
                    return_6m = float(return_6m) if pd.notna(return_6m) else 0.0
                    return_1y = float(return_1y) if pd.notna(return_1y) else 0.0

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
                        'factors': {
                            'return_1m': return_1m,
                            'return_3m': return_3m,
                            'return_6m': return_6m,
                            'return_1y': return_1y,
                            'nav': float(nav) if pd.notna(nav) else None,
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
