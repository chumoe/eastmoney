"""
Dashboard-related Pydantic models.
"""
from typing import Optional, Dict, Any
from pydantic import BaseModel


class LayoutCreate(BaseModel):
    """Create a new dashboard layout."""
    name: str
    layout: Dict[str, Any]
    is_default: bool = False


class LayoutUpdate(BaseModel):
    """Update an existing dashboard layout."""
    name: Optional[str] = None
    layout: Optional[Dict[str, Any]] = None
    is_default: Optional[bool] = None


# Dashboard layout presets
DASHBOARD_PRESETS = {
    "trader": {
        "name": "交易者视图",
        "name_en": "Trader View",
        "description": "实时异动、南向资金、龙虎榜、行业资金流",
        "widgets": [
            {"id": "abnormal", "type": "abnormal_movements", "position": {"x": 0, "y": 0, "w": 6, "h": 4}},
            {"id": "southbound", "type": "southbound_flow", "position": {"x": 6, "y": 0, "w": 6, "h": 4}},
            {"id": "toplist", "type": "top_list", "position": {"x": 0, "y": 4, "w": 8, "h": 4}},
            {"id": "industry", "type": "industry_flow", "position": {"x": 8, "y": 4, "w": 4, "h": 4}},
        ]
    },
    "investor": {
        "name": "投资者视图",
        "name_en": "Investor View",
        "description": "市场指数、板块涨跌、主力资金、自选股",
        "widgets": [
            {"id": "indices", "type": "market_indices", "position": {"x": 0, "y": 0, "w": 12, "h": 2}},
            {"id": "sectors", "type": "sector_performance", "position": {"x": 0, "y": 2, "w": 6, "h": 4}},
            {"id": "mainflow", "type": "main_capital_flow", "position": {"x": 6, "y": 2, "w": 6, "h": 4}},
            {"id": "watchlist", "type": "watchlist", "position": {"x": 0, "y": 6, "w": 12, "h": 4}},
        ]
    },
    "macro": {
        "name": "宏观视图",
        "name_en": "Macro View",
        "description": "市场指数、外汇汇率、黄金宏观、南向资金",
        "widgets": [
            {"id": "indices", "type": "market_indices", "position": {"x": 0, "y": 0, "w": 10, "h": 2}},
            {"id": "gold", "type": "gold_macro", "position": {"x": 10, "y": 0, "w": 2, "h": 2}},
            {"id": "forex", "type": "forex_rates", "position": {"x": 0, "y": 2, "w": 5, "h": 4}},
            {"id": "southbound", "type": "southbound_flow", "position": {"x": 5, "y": 2, "w": 7, "h": 4}},
        ]
    },
    "compact": {
        "name": "精简视图",
        "name_en": "Compact View",
        "description": "市场指数、市场情绪、主力资金",
        "widgets": [
            {"id": "indices", "type": "market_indices", "position": {"x": 0, "y": 0, "w": 12, "h": 2}},
            {"id": "sentiment", "type": "market_sentiment", "position": {"x": 0, "y": 2, "w": 6, "h": 3}},
            {"id": "mainflow", "type": "main_capital_flow", "position": {"x": 6, "y": 2, "w": 6, "h": 3}},
        ]
    },
}
