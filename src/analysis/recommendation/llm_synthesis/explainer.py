"""
LLM Synthesis Explainer - Generate explanations for quantitative recommendations.

Key principles:
- Quantitative model selects, LLM explains
- Max 2 LLM calls per recommendation cycle
- Batch process 10 stocks/funds per call
- Focus on investment logic, catalysts, and risks
"""
from typing import Dict, List
import json
import time

from src.llm.client import get_llm_client


class RecommendationExplainer:
    """
    Generates human-readable explanations for quantitative recommendations.

    The LLM does NOT participate in stock selection - it only explains
    the selections made by the quantitative model.
    """

    # Batch size for LLM calls
    BATCH_SIZE = 10
    MAX_CALLS_PER_CYCLE = 2

    @classmethod
    def explain_stock_recommendations(
        cls,
        recommendations: List[Dict],
        strategy: str = 'short_term'
    ) -> List[Dict]:
        """
        Generate explanations for stock recommendations.

        Args:
            recommendations: List of recommendation dicts from quantitative model
            strategy: 'short_term' or 'long_term'

        Returns:
            Recommendations with added 'explanation' field
        """
        if not recommendations:
            return recommendations

        # Batch process
        batches = [
            recommendations[i:i + cls.BATCH_SIZE]
            for i in range(0, len(recommendations), cls.BATCH_SIZE)
        ]

        # Limit batches
        batches = batches[:cls.MAX_CALLS_PER_CYCLE]

        explained_recs = []

        for batch in batches:
            explanations = cls._generate_stock_explanations(batch, strategy)

            for rec, explanation in zip(batch, explanations):
                _finalize_recommendation(rec, explanation)
                explained_recs.append(rec)

        # Add remaining without LLM explanation
        remaining_start = cls.MAX_CALLS_PER_CYCLE * cls.BATCH_SIZE
        for rec in recommendations[remaining_start:]:
            explanation = cls._generate_fallback_explanation(rec, strategy)
            _finalize_recommendation(rec, explanation)
            explained_recs.append(rec)

        return explained_recs

    @classmethod
    def explain_fund_recommendations(
        cls,
        recommendations: List[Dict],
        strategy: str = 'short_term'
    ) -> List[Dict]:
        """
        Generate explanations for fund recommendations.

        Args:
            recommendations: List of recommendation dicts
            strategy: 'short_term' or 'long_term'

        Returns:
            Recommendations with added 'explanation' field
        """
        if not recommendations:
            return recommendations

        batches = [
            recommendations[i:i + cls.BATCH_SIZE]
            for i in range(0, len(recommendations), cls.BATCH_SIZE)
        ]

        batches = batches[:cls.MAX_CALLS_PER_CYCLE]

        explained_recs = []

        for batch in batches:
            explanations = cls._generate_fund_explanations(batch, strategy)

            for rec, explanation in zip(batch, explanations):
                _finalize_recommendation(rec, explanation)
                explained_recs.append(rec)

        remaining_start = cls.MAX_CALLS_PER_CYCLE * cls.BATCH_SIZE
        for rec in recommendations[remaining_start:]:
            explanation = cls._generate_fallback_explanation(rec, strategy)
            _finalize_recommendation(rec, explanation)
            explained_recs.append(rec)

        return explained_recs

    @classmethod
    def _generate_stock_explanations(
        cls,
        recommendations: List[Dict],
        strategy: str
    ) -> List[str]:
        """Generate explanations for a batch of stock recommendations."""

        if strategy == 'short_term':
            prompt = cls._build_short_term_stock_prompt(recommendations)
        else:
            prompt = cls._build_long_term_stock_prompt(recommendations)

        try:
            client = get_llm_client()
            response = client.generate_content(prompt)

            # Parse response into list
            explanations = cls._parse_explanations(response, len(recommendations))

            return explanations

        except Exception as e:
            print(f"[LLM Explainer] Stock explanation failed: {e}")
            return [cls._generate_fallback_explanation(rec, strategy) for rec in recommendations]

    @classmethod
    def _generate_fund_explanations(
        cls,
        recommendations: List[Dict],
        strategy: str
    ) -> List[str]:
        """Generate explanations for a batch of fund recommendations."""

        if strategy == 'short_term':
            prompt = cls._build_short_term_fund_prompt(recommendations)
        else:
            prompt = cls._build_long_term_fund_prompt(recommendations)

        try:
            client = get_llm_client()
            response = client.generate_content(prompt)

            explanations = cls._parse_explanations(response, len(recommendations))

            return explanations

        except Exception as e:
            print(f"[LLM Explainer] Fund explanation failed: {e}")
            return [cls._generate_fallback_explanation(rec, strategy) for rec in recommendations]

    @classmethod
    def _build_short_term_stock_prompt(cls, recommendations: List[Dict]) -> str:
        """Build prompt for short-term stock explanations."""
        stocks_data = []
        for rec in recommendations:
            factors = rec.get('factors', {})
            stocks_data.append({
                'code': rec.get('code', ''),
                'name': rec.get('name', ''),
                'score': rec.get('score', 0),
                'consolidation_score': factors.get('consolidation_score'),
                'volume_precursor': factors.get('volume_precursor'),
                'main_inflow_5d': factors.get('main_inflow_5d'),
                'key_factors': rec.get('key_factors', []),
            })

        prompt = f"""你是投资分析师，需要解释量化模型的短期选股结果（7-30天持有期）。

量化模型已选出以下股票：
{json.dumps(stocks_data, ensure_ascii=False, indent=2)}

请为每只股票生成简洁的投资逻辑说明（50-80字），包含：
1. 基于因子数据的投资逻辑
2. 短期催化剂
3. 主要风险

注意：
- 不要修改选股结果，只需解释
- 必须引用具体的因子数据
- 用JSON数组格式返回，每个元素是一只股票的说明

返回格式示例：
["股票1说明", "股票2说明", ...]"""

        return prompt

    @classmethod
    def _build_long_term_stock_prompt(cls, recommendations: List[Dict]) -> str:
        """Build prompt for long-term stock explanations."""
        stocks_data = []
        for rec in recommendations:
            factors = rec.get('factors', {})
            stocks_data.append({
                'code': rec.get('code', ''),
                'name': rec.get('name', ''),
                'score': rec.get('score', 0),
                'roe': factors.get('roe'),
                'peg_ratio': factors.get('peg_ratio'),
                'pe_percentile': factors.get('pe_percentile'),
                'key_factors': rec.get('key_factors', []),
            })

        prompt = f"""你是投资分析师，需要解释量化模型的长期选股结果（3-12个月持有期）。

量化模型已选出以下优质股票：
{json.dumps(stocks_data, ensure_ascii=False, indent=2)}

请为每只股票生成简洁的投资逻辑说明（50-80字），包含：
1. 质量因子和估值分析
2. 长期成长逻辑
3. 主要风险

注意：
- 不要修改选股结果，只需解释
- 必须引用ROE、PEG等具体数据
- 用JSON数组格式返回

返回格式示例：
["股票1说明", "股票2说明", ...]"""

        return prompt

    @classmethod
    def _build_short_term_fund_prompt(cls, recommendations: List[Dict]) -> str:
        """Build prompt for short-term fund explanations."""
        funds_data = []
        for rec in recommendations:
            factors = rec.get('factors', {})
            funds_data.append({
                'code': rec.get('code', ''),
                'name': rec.get('name', ''),
                'score': rec.get('score', 0),
                'return_1m': factors.get('return_1m'),
                'sharpe_1y': factors.get('sharpe_1y'),
                'key_factors': rec.get('key_factors', []),
            })

        prompt = f"""你是基金分析师，需要解释量化模型的短期基金推荐结果（1-3个月持有期）。

量化模型已选出以下基金：
{json.dumps(funds_data, ensure_ascii=False, indent=2)}

请为每只基金生成简洁的投资逻辑说明（50-80字），包含：
1. 近期表现和动量分析
2. 风险调整收益
3. 主要风险

用JSON数组格式返回。"""

        return prompt

    @classmethod
    def _build_long_term_fund_prompt(cls, recommendations: List[Dict]) -> str:
        """Build prompt for long-term fund explanations."""
        funds_data = []
        for rec in recommendations:
            factors = rec.get('factors', {})
            funds_data.append({
                'code': rec.get('code', ''),
                'name': rec.get('name', ''),
                'score': rec.get('score', 0),
                'sharpe_1y': factors.get('sharpe_1y'),
                'max_drawdown_1y': factors.get('max_drawdown_1y'),
                'manager_tenure_years': factors.get('manager_tenure_years'),
                'key_factors': rec.get('key_factors', []),
            })

        prompt = f"""你是基金分析师，需要解释量化模型的长期基金推荐结果（6-12个月持有期）。

量化模型已选出以下优质基金：
{json.dumps(funds_data, ensure_ascii=False, indent=2)}

请为每只基金生成简洁的投资逻辑说明（50-80字），包含：
1. 风险调整收益和回撤控制
2. 基金经理能力评估
3. 主要风险

用JSON数组格式返回。"""

        return prompt

    @classmethod
    def _parse_explanations(cls, response: str, expected_count: int) -> List[str]:
        """Parse LLM response into list of explanations."""
        try:
            # Try to find JSON array in response
            start_idx = response.find('[')
            end_idx = response.rfind(']') + 1

            if start_idx >= 0 and end_idx > start_idx:
                json_str = response[start_idx:end_idx]
                explanations = json.loads(json_str)

                if isinstance(explanations, list):
                    # 处理元素可能是对象的情况（LLM可能返回对象数组而非字符串数组）
                    result = []
                    for item in explanations:
                        if isinstance(item, str):
                            result.append(item)
                        elif isinstance(item, dict):
                            # 尝试从对象中提取文本
                            text = (
                                item.get('explanation')
                                or item.get('reason')
                                or item.get('analysis')
                                or item.get('logic')
                                or item.get('text')
                                or item.get('description')
                                or ''
                            )
                            if not text and item:
                                # 如果是对象但没有已知字段，转成字符串
                                text = json.dumps(item, ensure_ascii=False)
                            result.append(text)
                        else:
                            result.append(str(item))

                    # Pad with empty strings if needed
                    while len(result) < expected_count:
                        result.append("暂无详细分析")
                    return result[:expected_count]

        except json.JSONDecodeError:
            pass

        # Fallback: try to parse as markdown list
        lines = response.strip().split('\n')
        text_lines = []
        for line in lines:
            line = line.strip()
            if line.startswith('- ') or line.startswith('* '):
                text_lines.append(line[2:].strip())
            elif line and not line.startswith('#') and not line.startswith('```'):
                text_lines.append(line)

        if text_lines and len(text_lines) >= expected_count // 2:
            result = text_lines[:expected_count]
            while len(result) < expected_count:
                result.append("暂无详细分析")
            return result

        # Fallback: return generic explanations
        return ["暂无详细分析"] * expected_count

    @classmethod
    def _generate_fallback_explanation(cls, rec: Dict, strategy: str) -> str:
        """Generate a fallback explanation without LLM."""
        key_factors = rec.get('key_factors', rec.get('key_reasons', []))
        score = rec.get('score', 0)
        confidence = rec.get('confidence', '中等')

        if strategy in ['short_term', 'momentum']:
            holding = "短期（7-30天）"
        else:
            holding = "中长期（3-12个月）"

        if key_factors:
            factors_str = '、'.join(key_factors[:3])
            return f"综合得分{score:.0f}分。主要优势：{factors_str}。建议{holding}持有。"
        else:
            return f"综合得分{score:.0f}分。建议{holding}持有，请结合市场情况决策。"


def _finalize_recommendation(rec: Dict, explanation: str) -> Dict:
    """标准化推荐结果，同时设置explanation和investment_logic两个字段，保持前后端兼容。"""
    rec['explanation'] = explanation
    rec['investment_logic'] = explanation
    return rec


# Synchronous wrapper for engine calls
def explain_recommendations_sync(
    recommendations: List[Dict],
    asset_type: str = 'stock',
    strategy: str = 'short_term'
) -> List[Dict]:
    """
    Synchronous function for explanation generation.

    Uses LLM for explanations, falls back to rule-based if LLM fails.
    """
    if not recommendations:
        return recommendations

    start_time = time.time()
    print(f"[LLM Explainer] Starting {asset_type} {strategy} explanations for {len(recommendations)} items...")

    try:
        if asset_type == 'stock':
            result = RecommendationExplainer.explain_stock_recommendations(recommendations, strategy)
        else:
            result = RecommendationExplainer.explain_fund_recommendations(recommendations, strategy)

        print(f"[LLM Explainer] Explanations completed in {time.time() - start_time:.2f}s")
        return result

    except Exception as e:
        print(f"[LLM Explainer] Failed: {e}, using fallback explanations")
        # Fallback to rule-based explanations
        for rec in recommendations:
            explanation = RecommendationExplainer._generate_fallback_explanation(rec, strategy)
            _finalize_recommendation(rec, explanation)
        return recommendations
