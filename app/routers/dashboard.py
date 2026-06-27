"""
Dashboard endpoints.
"""
import asyncio
from fastapi import APIRouter, HTTPException, Depends

from app.models.dashboard import LayoutCreate, LayoutUpdate, DASHBOARD_PRESETS
from app.models.auth import User
from app.core.dependencies import get_current_user, get_user_report_dir
from app.core.config import REPORT_DIR
from src.analysis.dashboard import DashboardService
from src.services.market_snapshot_service import market_snapshot_service
from src.storage.db import (
    get_user_layouts, get_layout_by_id, get_default_layout,
    save_layout, update_layout, delete_layout, set_default_layout
)

router = APIRouter(prefix="/api/dashboard", tags=["Dashboard"])


@router.get("/overview")
async def get_dashboard_overview():
    """Get full dashboard overview."""
    try:
        service = DashboardService(REPORT_DIR)
        return await asyncio.to_thread(service.get_full_dashboard)
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/snapshot")
async def get_market_snapshot():
    """Get pre-generated market snapshot (fast)."""
    try:
        snapshot = await asyncio.to_thread(market_snapshot_service.get_snapshot)
        return snapshot
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/snapshot/refresh")
async def refresh_market_snapshot():
    """Force refresh market snapshot."""
    try:
        success = await asyncio.to_thread(market_snapshot_service.refresh)
        return {"success": success}
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/stats")
async def get_dashboard_stats(current_user: User = Depends(get_current_user)):
    """Get system stats for dashboard."""
    try:
        user_report_dir = get_user_report_dir(current_user.id)
        service = DashboardService(REPORT_DIR)
        return service.get_system_stats(user_report_dir)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/layouts")
async def get_dashboard_layouts(current_user: User = Depends(get_current_user)):
    """Get all dashboard layouts for current user."""
    try:
        layouts = get_user_layouts(user_id=current_user.id)
        return {"layouts": layouts}
    except Exception as e:
        print(f"Error fetching layouts: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/layouts/count")
async def get_dashboard_layout_count(current_user: User = Depends(get_current_user)):
    """Get layout count for current user."""
    try:
        layouts = get_user_layouts(user_id=current_user.id)
        count = len(layouts) if layouts else 0
        return {"count": count, "max": 3}
    except Exception as e:
        print(f"Error fetching layout count: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/layouts/default")
async def get_default_dashboard_layout(current_user: User = Depends(get_current_user)):
    """Get the default dashboard layout."""
    try:
        layout = get_default_layout(user_id=current_user.id)
        if not layout:
            return {"layout": None, "preset": "investor"}
        return {"layout": layout}
    except Exception as e:
        print(f"Error fetching default layout: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/layouts/{layout_id}")
async def get_dashboard_layout(layout_id: int, current_user: User = Depends(get_current_user)):
    """Get a specific dashboard layout."""
    try:
        layout = get_layout_by_id(layout_id, user_id=current_user.id)
        if not layout:
            raise HTTPException(status_code=404, detail="Layout not found")
        return layout
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error fetching layout: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/layouts")
async def create_dashboard_layout(
    layout_data: LayoutCreate,
    current_user: User = Depends(get_current_user)
):
    """Create a new dashboard layout."""
    try:
        existing_layouts = get_user_layouts(user_id=current_user.id)
        if existing_layouts and len(existing_layouts) >= 3:
            raise HTTPException(
                status_code=400,
                detail="Maximum number of custom layouts (3) reached. Please delete an existing layout first."
            )

        layout_id = save_layout(
            user_id=current_user.id,
            name=layout_data.name,
            layout=layout_data.layout,
            is_default=layout_data.is_default
        )
        return {"id": layout_id, "message": "Layout created successfully"}
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error creating layout: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/layouts/{layout_id}")
async def update_dashboard_layout(
    layout_id: int,
    layout_data: LayoutUpdate,
    current_user: User = Depends(get_current_user)
):
    """Update a dashboard layout."""
    try:
        updates = {}
        if layout_data.name is not None:
            updates['name'] = layout_data.name
        if layout_data.layout is not None:
            updates['layout'] = layout_data.layout
        if layout_data.is_default is not None:
            updates['is_default'] = layout_data.is_default

        success = update_layout(layout_id, user_id=current_user.id, updates=updates)
        if not success:
            raise HTTPException(status_code=404, detail="Layout not found")
        return {"message": "Layout updated successfully"}
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error updating layout: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/layouts/{layout_id}")
async def delete_dashboard_layout(layout_id: int, current_user: User = Depends(get_current_user)):
    """Delete a dashboard layout."""
    try:
        success = delete_layout(layout_id, user_id=current_user.id)
        if not success:
            raise HTTPException(status_code=404, detail="Layout not found")
        return {"message": "Layout deleted successfully"}
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error deleting layout: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/layouts/{layout_id}/set-default")
async def set_default_dashboard_layout(layout_id: int, current_user: User = Depends(get_current_user)):
    """Set a layout as default."""
    try:
        success = set_default_layout(user_id=current_user.id, layout_id=layout_id)
        if not success:
            raise HTTPException(status_code=404, detail="Layout not found")
        return {"message": "Default layout set successfully"}
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error setting default layout: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/presets")
async def get_dashboard_presets():
    """Get predefined dashboard layout presets."""
    return {"presets": DASHBOARD_PRESETS}
