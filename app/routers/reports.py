"""
Report management endpoints.
"""
import os
import glob
from typing import List
from fastapi import APIRouter, HTTPException, Depends

from app.models.reports import ReportSummary
from app.models.auth import User
from app.core.dependencies import get_current_user, get_user_report_dir
from src.storage.db import get_all_funds

router = APIRouter(prefix="/api/reports", tags=["Reports"])


@router.get("", response_model=List[ReportSummary])
async def list_reports(current_user: User = Depends(get_current_user)):
    """List all reports for current user."""
    user_report_dir = get_user_report_dir(current_user.id)
    if not os.path.exists(user_report_dir):
        return []

    fund_map = {}
    try:
        funds = get_all_funds(user_id=current_user.id)
        for f in funds:
            fund_map[f['code']] = f['name']
    except:
        pass

    reports = []
    files = glob.glob(os.path.join(user_report_dir, "*.md"))
    files.sort(key=os.path.getmtime, reverse=True)

    for f in files:
        filename = os.path.basename(f)
        try:
            name_no_ext = os.path.splitext(filename)[0]
            parts = name_no_ext.split("_")

            if len(parts) < 2:
                continue

            date_str = parts[0]
            mode = parts[1]

            if "SUMMARY" in name_no_ext or (len(parts) > 2 and parts[2] == "report"):
                reports.append(ReportSummary(
                    filename=filename,
                    date=date_str,
                    mode=mode,
                    is_summary=True,
                    fund_name="Market Overview"
                ))
            elif len(parts) >= 3:
                code = parts[2]
                extracted_name = "_".join(parts[3:]) if len(parts) > 3 else ""
                final_name = extracted_name if extracted_name else fund_map.get(code, code)

                reports.append(ReportSummary(
                    filename=filename,
                    date=date_str,
                    mode=mode,
                    fund_code=code,
                    fund_name=final_name,
                    is_summary=False
                ))
        except Exception as e:
            print(f"Error parsing filename {filename}: {e}")
            continue

    return reports


@router.get("/{filename}")
async def get_report(filename: str, current_user: User = Depends(get_current_user)):
    """Get the content of a specific report."""
    user_report_dir = get_user_report_dir(current_user.id)

    filepath = os.path.join(user_report_dir, filename)
    if not os.path.exists(filepath):
        filepath = os.path.join(user_report_dir, "sentiment", filename)

    if not os.path.exists(filepath):
        filepath = os.path.join(user_report_dir, "commodities", filename)

    if not os.path.exists(filepath):
        filepath = os.path.join(user_report_dir, "stocks", filename)

    if not os.path.exists(filepath):
        raise HTTPException(status_code=404, detail="Report not found")

    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()

    return {"content": content}


@router.delete("/{filename}")
async def delete_report(filename: str, current_user: User = Depends(get_current_user)):
    """Delete a report."""
    try:
        if not filename.endswith(".md") or ".." in filename or "/" in filename or "\\" in filename:
            raise HTTPException(status_code=400, detail="Invalid filename")

        user_report_dir = get_user_report_dir(current_user.id)
        file_path = os.path.join(user_report_dir, filename)

        if os.path.exists(file_path):
            os.remove(file_path)
            return {"status": "success", "message": f"Deleted {filename}"}
        else:
            raise HTTPException(status_code=404, detail="File not found")
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error deleting report: {e}")
        raise HTTPException(status_code=500, detail=str(e))
