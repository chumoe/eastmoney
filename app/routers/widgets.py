"""
Widget data endpoints.
"""
import asyncio
from datetime import datetime
from fastapi import APIRouter, HTTPException, Depends

from app.models.auth import User
from app.core.dependencies import get_current_user
from app.core.utils import sanitize_data
from src.analysis.widget_service import widget_service
from src.storage.db import get_all_stocks

router = APIRouter(prefix="/api/widgets", tags=["Widgets"])


@router.get("/southbound-flow")
async def get_widget_southbound_flow(days: int = 5):
    """Get southbound capital flow data for widget."""
    try:
        data = await asyncio.to_thread(widget_service.get_southbound_flow, days)
        return sanitize_data(data)
    except Exception as e:
        print(f"Error fetching southbound flow: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/industry-flow")
async def get_widget_industry_flow(limit: int = 10):
    """Get industry money flow data for widget."""
    try:
        data = await asyncio.to_thread(widget_service.get_industry_flow, limit)
        return sanitize_data(data)
    except Exception as e:
        print(f"Error fetching industry flow: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/sector-performance")
async def get_widget_sector_performance(limit: int = 10):
    """Get sector performance data for widget."""
    try:
        data = await asyncio.to_thread(widget_service.get_sector_performance, limit)
        return sanitize_data(data)
    except Exception as e:
        print(f"Error fetching sector performance: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/top-list")
async def get_widget_top_list(limit: int = 10):
    """Get dragon tiger list data for widget."""
    try:
        data = await asyncio.to_thread(widget_service.get_top_list, limit)
        return sanitize_data(data)
    except Exception as e:
        print(f"Error fetching top list: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/forex-rates")
async def get_widget_forex_rates():
    """Get forex rates data for widget."""
    try:
        data = await asyncio.to_thread(widget_service.get_forex_rates)
        return sanitize_data(data)
    except Exception as e:
        print(f"Error fetching forex rates: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/watchlist")
async def get_widget_watchlist(current_user: User = Depends(get_current_user)):
    """Get watchlist quotes for widget."""
    try:
        stocks = get_all_stocks(user_id=current_user.id)
        stock_codes = [s['code'] for s in stocks]

        if not stock_codes:
            return {"stocks": [], "updated_at": datetime.now().isoformat()}

        data = await asyncio.to_thread(widget_service.get_watchlist_quotes, stock_codes)
        return sanitize_data(data)
    except Exception as e:
        print(f"Error fetching watchlist: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/news")
async def get_widget_news(limit: int = 20, src: str = 'sina'):
    """Get news feed for widget."""
    try:
        data = await asyncio.to_thread(widget_service.get_news, limit, src)
        return sanitize_data(data)
    except Exception as e:
        print(f"Error fetching news: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/main-capital-flow")
async def get_widget_main_capital_flow(limit: int = 10):
    """Get main capital flow for widget."""
    try:
        data = await asyncio.to_thread(widget_service.get_main_capital_flow, limit)
        return sanitize_data(data)
    except Exception as e:
        print(f"Error fetching main capital flow: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/dashboard-bundle")
async def get_dashboard_bundle(limit: int = 10, days: int = 5):
    """
    Dashboard 聚合接口：一次性返回所有 widget 数据。

    减少 HTTP 请求数，所有数据走缓存，加载更快。
    """
    try:
        data = await asyncio.to_thread(widget_service.get_dashboard_bundle, limit, days)
        return sanitize_data(data)
    except Exception as e:
        print(f"Error fetching dashboard bundle: {e}")
        raise HTTPException(status_code=500, detail=str(e))
