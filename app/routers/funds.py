"""
Fund management endpoints.
"""
import json
from typing import List
from fastapi import APIRouter, HTTPException, Depends

from app.models.funds import FundItem, FundCompareRequest
from app.models.auth import User
from app.core.dependencies import get_current_user
from app.core.utils import sanitize_for_json
from app.core.helpers import get_fund_nav_history, get_fund_basic_info, get_fund_holdings_list
from src.storage.db import (
    get_all_funds, upsert_fund, delete_fund, get_diagnosis_cache, save_diagnosis_cache
)
from src.scheduler.manager import scheduler_manager
from src.analysis.fund import FundDiagnosis, RiskMetricsCalculator, DrawdownAnalyzer, FundComparison
from src.analysis.widget_service import widget_service

import asyncio

router = APIRouter(prefix="/api/funds", tags=["Funds"])


@router.get("", response_model=List[FundItem])
async def get_funds_endpoint(current_user: User = Depends(get_current_user)):
    """Get all funds for current user."""
    try:
        funds = get_all_funds(user_id=current_user.id)
        result = []
        for f in funds:
            item = dict(f)
            if isinstance(item.get('focus'), str):
                try:
                    item['focus'] = json.loads(item['focus'])
                except:
                    item['focus'] = []

            result.append(FundItem(
                code=item['code'],
                name=item['name'],
                style=item.get('style'),
                focus=item['focus'],
                pre_market_time=item.get('pre_market_time'),
                post_market_time=item.get('post_market_time'),
                is_active=bool(item.get('is_active', True))
            ))
        return result
    except Exception as e:
        print(f"Error reading funds: {e}")
        return []


@router.post("")
async def save_funds(funds: List[FundItem], current_user: User = Depends(get_current_user)):
    """Save multiple funds."""
    try:
        for fund in funds:
            fund_dict = fund.model_dump()
            upsert_fund(fund_dict, user_id=current_user.id)
        return {"status": "success"}
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/{code}")
async def upsert_fund_endpoint(code: str, fund: FundItem, current_user: User = Depends(get_current_user)):
    """Create or update a fund."""
    try:
        fund_dict = fund.model_dump()
        upsert_fund(fund_dict, user_id=current_user.id)
        scheduler_manager.add_fund_jobs(fund_dict)
        return {"status": "success"}
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/{code}")
async def delete_fund_endpoint(code: str, current_user: User = Depends(get_current_user)):
    """Delete a fund."""
    try:
        delete_fund(code, user_id=current_user.id)
        scheduler_manager.remove_fund_jobs(code)
        return {"status": "success"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{code}/diagnosis")
async def get_fund_diagnosis(
    code: str,
    force_refresh: bool = False,
    current_user: User = Depends(get_current_user)
):
    """Get fund diagnosis with five-dimension scoring and radar chart data."""
    try:
        # Check cache first
        if not force_refresh:
            cached = get_diagnosis_cache(code)
            if cached and cached.get('diagnosis'):
                return cached['diagnosis']

        # Fetch NAV history
        loop = asyncio.get_running_loop()
        nav_history = await loop.run_in_executor(None, get_fund_nav_history, code, 500)

        if not nav_history:
            raise HTTPException(status_code=404, detail=f"No NAV history found for fund {code}")

        # Calculate diagnosis
        diagnoser = FundDiagnosis()
        diagnosis = diagnoser.diagnose(code, nav_history)

        # Cache result (6 hours TTL)
        if diagnosis.get('score', 0) > 0:
            save_diagnosis_cache(code, diagnosis, int(diagnosis['score']), ttl_hours=6)

        return sanitize_for_json(diagnosis)
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error calculating fund diagnosis for {code}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{code}/risk-metrics")
async def get_fund_risk_metrics(
    code: str,
    current_user: User = Depends(get_current_user)
):
    """Get comprehensive risk metrics for a fund."""
    try:
        loop = asyncio.get_running_loop()
        nav_history = await loop.run_in_executor(None, get_fund_nav_history, code, 500)

        if not nav_history:
            raise HTTPException(status_code=404, detail=f"No NAV history found for fund {code}")

        calculator = RiskMetricsCalculator()
        metrics = calculator.calculate_all_metrics(nav_history)

        return sanitize_for_json(metrics)
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error calculating risk metrics for {code}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{code}/drawdown-history")
async def get_fund_drawdown_history(
    code: str,
    threshold: float = 0.05,
    current_user: User = Depends(get_current_user)
):
    """Get detailed drawdown history analysis for a fund."""
    try:
        loop = asyncio.get_running_loop()
        nav_history = await loop.run_in_executor(None, get_fund_nav_history, code, 500)

        if not nav_history:
            raise HTTPException(status_code=404, detail=f"No NAV history found for fund {code}")

        analyzer = DrawdownAnalyzer(threshold=threshold)
        analysis = analyzer.analyze_drawdowns(nav_history)

        return sanitize_for_json(analysis)
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error analyzing drawdowns for {code}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/compare")
async def compare_funds_advanced(
    request: FundCompareRequest,
    current_user: User = Depends(get_current_user)
):
    """
    Compare multiple funds (up to 10) with comprehensive analysis.
    Includes NAV curves, returns, risk metrics, and holdings overlap.
    """
    try:
        codes = request.codes

        if len(codes) < 2:
            raise HTTPException(status_code=400, detail="Please select at least 2 funds to compare")
        if len(codes) > 10:
            raise HTTPException(status_code=400, detail="Maximum 10 funds allowed for comparison")

        loop = asyncio.get_running_loop()

        async def fetch_fund_data(code: str):
            nav_history = await loop.run_in_executor(None, get_fund_nav_history, code, 500)
            fund_info = await loop.run_in_executor(None, get_fund_basic_info, code)
            holdings = await loop.run_in_executor(None, get_fund_holdings_list, code)
            return {
                'code': code,
                'name': fund_info.get('name', code) if fund_info else code,
                'nav_history': nav_history,
                'holdings': holdings,
            }

        tasks = [fetch_fund_data(code) for code in codes]
        funds_data = await asyncio.gather(*tasks)

        # Filter out funds with insufficient data
        valid_funds = [f for f in funds_data if f.get('nav_history') and len(f['nav_history']) >= 20]

        if len(valid_funds) < 2:
            raise HTTPException(status_code=400, detail="Not enough funds with valid data for comparison")

        comparator = FundComparison()
        result = comparator.compare(valid_funds)

        return sanitize_for_json(result)
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error comparing funds: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ==================== Enhanced Fund Page Endpoints ====================

import akshare as ak
import time
import threading
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache
from datetime import datetime, timedelta
from dotenv import load_dotenv

# ==================== Batch Estimation Cache ====================
# Cache for fund estimation data (shared across requests)
_estimation_cache_lock = threading.Lock()
_estimation_cache_data: dict = {}  # {code: {...estimation_data...}}
_estimation_cache_timestamp: float = 0.0
_ESTIMATION_CACHE_TTL = 60  # 60 seconds for trading hours, longer for non-trading

# Load .env file first
load_dotenv()

# TuShare for fund manager data
try:
    import tushare as ts
    import os
    TUSHARE_TOKEN = os.environ.get('TUSHARE_API_TOKEN', '')
    if TUSHARE_TOKEN:
        ts.set_token(TUSHARE_TOKEN)
        TS_PRO = ts.pro_api()
        print(f"TuShare initialized with token")
    else:
        TS_PRO = None
        print("TUSHARE_API_TOKEN not configured. Fund manager data will be limited.")
except ImportError:
    ts = None
    TS_PRO = None
    print("TuShare not installed. Fund manager data will be limited.")


def _safe_float(val, default=0.0):
    """Safely convert value to float."""
    try:
        if val is None or (isinstance(val, float) and pd.isna(val)):
            return default
        return float(val)
    except:
        return default


def _safe_str(val, default=""):
    """Safely convert value to string."""
    try:
        if val is None or (isinstance(val, float) and pd.isna(val)):
            return default
        return str(val)
    except:
        return default


import pandas as pd


def _is_trading_hours() -> bool:
    """Check if current time is within A-share trading hours (9:30-15:00 Beijing time)."""
    now = datetime.now()
    # A-share trading hours: 9:30-11:30, 13:00-15:00
    current_time = now.hour * 60 + now.minute
    morning_start = 9 * 60 + 30
    morning_end = 11 * 60 + 30
    afternoon_start = 13 * 60
    afternoon_end = 15 * 60
    
    # Also check if it's a weekday
    if now.weekday() >= 5:  # Saturday=5, Sunday=6
        return False
    
    return (morning_start <= current_time <= morning_end) or (afternoon_start <= current_time <= afternoon_end)


def _get_estimation_cache_ttl() -> int:
    """Return appropriate cache TTL based on trading hours."""
    if _is_trading_hours():
        return 60  # 1 minute during trading
    else:
        return 3600  # 1 hour after market close (use 15:00 data)


def _fetch_all_estimations() -> dict:
    """
    Fetch all fund estimations from AkShare and return as dict keyed by code.
    This is called with caching to avoid repeated API calls.
    """
    global _estimation_cache_data, _estimation_cache_timestamp
    
    now = time.time()
    ttl = _get_estimation_cache_ttl()
    
    with _estimation_cache_lock:
        # Check if cache is still valid
        if _estimation_cache_data and (now - _estimation_cache_timestamp) < ttl:
            return _estimation_cache_data
        
        try:
            df = ak.fund_value_estimation_em()
            if df is None or df.empty:
                return _estimation_cache_data  # Return old cache if fetch fails
            
            # AkShare returns dynamic column names with dates like:
            # '2026-01-30-估算数据-估算值', '2026-01-30-估算数据-估算增长率', etc.
            # We need to find columns by pattern matching
            columns = df.columns.tolist()
            
            # Find the estimation columns dynamically
            est_nav_col = None
            est_change_col = None
            prev_nav_col = None
            
            for col in columns:
                if '估算数据-估算值' in col:
                    est_nav_col = col
                elif '估算数据-估算增长率' in col:
                    est_change_col = col
                elif col.endswith('-单位净值') and '公布数据' not in col:
                    prev_nav_col = col
            
            # Extract date from column name (e.g., '2026-01-30-估算数据-估算值' -> '2026-01-30')
            estimation_date = ''
            if est_nav_col:
                parts = est_nav_col.split('-估算数据')
                if parts:
                    estimation_date = parts[0]
            
            # Build dict keyed by fund code
            result = {}
            for _, row in df.iterrows():
                code = str(row.get('基金代码', '')).strip()
                if code:
                    # Parse estimated change percentage (remove % sign)
                    est_change_str = str(row.get(est_change_col, '0')) if est_change_col else '0'
                    est_change = _safe_float(est_change_str.replace('%', '').strip())
                    
                    result[code] = {
                        'code': code,
                        'name': _safe_str(row.get('基金名称')),
                        'estimated_nav': _safe_float(row.get(est_nav_col)) if est_nav_col else 0.0,
                        'estimated_change_pct': est_change,
                        'prev_nav': _safe_float(row.get(prev_nav_col)) if prev_nav_col else 0.0,
                        'prev_nav_date': estimation_date,
                        'estimation_time': estimation_date,
                    }
            
            _estimation_cache_data = result
            _estimation_cache_timestamp = now
            print(f"[Estimation] Loaded {len(result)} funds, columns: est_nav={est_nav_col}, est_change={est_change_col}")
            return result
        except Exception as e:
            print(f"Error fetching fund estimations: {e}")
            import traceback
            traceback.print_exc()
            return _estimation_cache_data  # Return old cache on error


@router.get("/batch-estimation")
async def get_batch_fund_estimation(
    codes: str = "",  # Comma-separated fund codes
    current_user: User = Depends(get_current_user)
):
    """
    Get batch intraday fund NAV estimation for multiple funds.
    
    Args:
        codes: Comma-separated fund codes (e.g., "000001,000002,000003")
               If empty, returns estimation for all user's funds.
    
    Returns:
        List of estimation data with trading status.
    """
    try:
        loop = asyncio.get_running_loop()
        
        # Get fund codes to query
        if codes:
            code_list = [c.strip() for c in codes.split(',') if c.strip()]
        else:
            # Get all user's funds
            user_funds = get_all_funds(user_id=current_user.id)
            code_list = [f['code'] for f in user_funds]
        
        if not code_list:
            return {
                'estimations': [],
                'is_trading': _is_trading_hours(),
                'timestamp': datetime.now().isoformat(),
            }
        
        # Fetch all estimations (cached)
        all_estimations = await loop.run_in_executor(None, _fetch_all_estimations)
        
        # Filter for requested codes
        result = []
        for code in code_list:
            if code in all_estimations:
                result.append(all_estimations[code])
            else:
                # Fund not found in estimation data (may be ETF or money market fund)
                result.append({
                    'code': code,
                    'name': None,
                    'estimated_nav': None,
                    'estimated_change_pct': None,
                    'prev_nav': None,
                    'prev_nav_date': None,
                    'estimation_time': None,
                    'not_available': True,
                })
        
        return {
            'estimations': result,
            'is_trading': _is_trading_hours(),
            'cache_ttl': _get_estimation_cache_ttl(),
            'timestamp': datetime.now().isoformat(),
        }
    except Exception as e:
        print(f"Error in batch fund estimation: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/market/overview")
async def get_fund_market_overview(current_user: User = Depends(get_current_user)):
    """
    Get fund market overview statistics.
    Returns aggregated data about different fund categories.
    """
    try:
        loop = asyncio.get_running_loop()
        
        async def fetch_category_stats(fund_type: str, display_name: str):
            """Fetch stats for a specific fund category."""
            try:
                df = await loop.run_in_executor(None, lambda: ak.fund_open_fund_rank_em(symbol=fund_type))
                if df is None or df.empty:
                    return None
                    
                total_count = len(df)
                avg_return_1m = _safe_float(df['近1月'].astype(float).mean())
                avg_return_3m = _safe_float(df['近3月'].astype(float).mean())
                avg_return_1y = _safe_float(df['近1年'].astype(float).mean())
                
                # Top performers
                df_sorted = df.sort_values('近1月', ascending=False)
                top_funds = []
                for _, row in df_sorted.head(3).iterrows():
                    top_funds.append({
                        'code': _safe_str(row.get('基金代码')),
                        'name': _safe_str(row.get('基金简称')),
                        'return_1m': _safe_float(row.get('近1月')),
                    })
                
                return {
                    'category': display_name,
                    'type_key': fund_type,
                    'total_count': total_count,
                    'avg_return_1m': round(avg_return_1m, 2),
                    'avg_return_3m': round(avg_return_3m, 2),
                    'avg_return_1y': round(avg_return_1y, 2),
                    'top_performers': top_funds,
                }
            except Exception as e:
                print(f"Error fetching {fund_type}: {e}")
                return None
        
        categories = [
            ("股票型", "股票型基金"),
            ("混合型", "混合型基金"),
            ("债券型", "债券型基金"),
            ("指数型", "指数型基金"),
            ("QDII", "QDII基金"),
            ("FOF", "FOF基金"),
        ]
        
        tasks = [fetch_category_stats(t, n) for t, n in categories]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        overview = []
        for r in results:
            if isinstance(r, dict):
                overview.append(r)
        
        return {
            'timestamp': datetime.now().isoformat(),
            'categories': overview,
        }
    except Exception as e:
        print(f"Error in fund market overview: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/market/ranking")
async def get_fund_ranking(
    fund_type: str = "股票型",
    sort_by: str = "近1月",
    limit: int = 50,
    current_user: User = Depends(get_current_user)
):
    """
    Get fund ranking by category and time period.
    
    Args:
        fund_type: Fund category (股票型, 混合型, 债券型, 指数型, QDII, FOF)
        sort_by: Sort column (近1周, 近1月, 近3月, 近6月, 近1年, 近3年)
        limit: Number of results to return
    """
    try:
        loop = asyncio.get_running_loop()
        df = await loop.run_in_executor(None, lambda: ak.fund_open_fund_rank_em(symbol=fund_type))
        
        if df is None or df.empty:
            return {'funds': [], 'total': 0}
        
        # Validate sort column
        valid_sort_cols = ['近1周', '近1月', '近3月', '近6月', '近1年', '近3年']
        if sort_by not in valid_sort_cols:
            sort_by = '近1月'
        
        # Convert sort column to numeric and sort
        df[sort_by] = pd.to_numeric(df[sort_by], errors='coerce')
        df_sorted = df.dropna(subset=[sort_by]).sort_values(sort_by, ascending=False)
        
        funds = []
        for idx, row in df_sorted.head(limit).iterrows():
            funds.append({
                'rank': len(funds) + 1,
                'code': _safe_str(row.get('基金代码')),
                'name': _safe_str(row.get('基金简称')),
                'nav': _safe_float(row.get('单位净值')),
                'acc_nav': _safe_float(row.get('累计净值')),
                'return_1w': _safe_float(row.get('近1周')),
                'return_1m': _safe_float(row.get('近1月')),
                'return_3m': _safe_float(row.get('近3月')),
                'return_6m': _safe_float(row.get('近6月')),
                'return_1y': _safe_float(row.get('近1年')),
                'return_3y': _safe_float(row.get('近3年')),
                'fee': _safe_str(row.get('手续费')),
            })
        
        return {
            'fund_type': fund_type,
            'sort_by': sort_by,
            'funds': funds,
            'total': len(df),
        }
    except Exception as e:
        print(f"Error in fund ranking: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/etf/realtime")
async def get_etf_realtime(
    limit: int = 50,
    current_user: User = Depends(get_current_user)
):
    """
    Get real-time ETF quotes and trading data.
    """
    try:
        loop = asyncio.get_running_loop()
        df = await loop.run_in_executor(None, ak.fund_etf_spot_em)
        
        if df is None or df.empty:
            return {'etfs': [], 'timestamp': datetime.now().isoformat()}
        
        # Sort by trading volume
        df['成交额'] = pd.to_numeric(df['成交额'], errors='coerce')
        df_sorted = df.sort_values('成交额', ascending=False)
        
        etfs = []
        for _, row in df_sorted.head(limit).iterrows():
            etfs.append({
                'code': _safe_str(row.get('代码')),
                'name': _safe_str(row.get('名称')),
                'price': _safe_float(row.get('最新价')),
                'change_pct': _safe_float(row.get('涨跌幅')),
                'change_val': _safe_float(row.get('涨跌额')),
                'volume': _safe_float(row.get('成交量')),
                'amount': _safe_float(row.get('成交额')),
                'open': _safe_float(row.get('开盘价')),
                'high': _safe_float(row.get('最高价')),
                'low': _safe_float(row.get('最低价')),
                'prev_close': _safe_float(row.get('昨收')),
                'turnover_rate': _safe_float(row.get('换手率')),
            })
        
        return {
            'etfs': etfs,
            'timestamp': datetime.now().isoformat(),
        }
    except Exception as e:
        print(f"Error in ETF realtime: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{code}/estimation")
async def get_fund_estimation(
    code: str,
    current_user: User = Depends(get_current_user)
):
    """
    Get intraday fund NAV estimation.
    """
    try:
        loop = asyncio.get_running_loop()
        df = await loop.run_in_executor(None, ak.fund_value_estimation_em)
        
        if df is None or df.empty:
            raise HTTPException(status_code=404, detail="Estimation data not available")
        
        # Find the specific fund
        fund_row = df[df['基金代码'] == code]
        
        if fund_row.empty:
            raise HTTPException(status_code=404, detail=f"Estimation not found for fund {code}")
        
        row = fund_row.iloc[0]
        
        # AkShare returns dynamic column names with dates
        columns = df.columns.tolist()
        est_nav_col = None
        est_change_col = None
        prev_nav_col = None
        
        for col in columns:
            if '估算数据-估算值' in col:
                est_nav_col = col
            elif '估算数据-估算增长率' in col:
                est_change_col = col
            elif col.endswith('-单位净值') and '公布数据' not in col:
                prev_nav_col = col
        
        # Extract date from column name
        estimation_date = ''
        if est_nav_col:
            parts = est_nav_col.split('-估算数据')
            if parts:
                estimation_date = parts[0]
        
        # Parse estimated change percentage (remove % sign)
        est_change_str = str(row.get(est_change_col, '0')) if est_change_col else '0'
        est_change = _safe_float(est_change_str.replace('%', '').strip())
        
        return {
            'code': code,
            'name': _safe_str(row.get('基金名称')),
            'estimated_nav': _safe_float(row.get(est_nav_col)) if est_nav_col else 0.0,
            'estimated_change_pct': est_change,
            'prev_nav': _safe_float(row.get(prev_nav_col)) if prev_nav_col else 0.0,
            'prev_nav_date': estimation_date,
            'estimation_time': estimation_date,
            'timestamp': datetime.now().isoformat(),
        }
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error in fund estimation for {code}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{code}/industry-allocation")
async def get_fund_industry_allocation(
    code: str,
    current_user: User = Depends(get_current_user)
):
    """
    Get fund industry allocation breakdown.
    """
    try:
        loop = asyncio.get_running_loop()
        
        try:
            df = await loop.run_in_executor(
                None, 
                lambda: ak.fund_portfolio_industry_allocation_em(symbol=code)
            )
        except Exception as e:
            print(f"AkShare industry allocation failed for {code}: {e}")
            # Return empty allocation if data not available
            return {
                'code': code,
                'allocations': [],
                'report_date': None,
                'message': 'Industry allocation data not available for this fund',
            }
        
        if df is None or df.empty:
            return {
                'code': code,
                'allocations': [],
                'report_date': None,
            }
        
        # Get the most recent report period
        if '截止时间' in df.columns:
            latest_date = df['截止时间'].max()
            df_latest = df[df['截止时间'] == latest_date]
        else:
            df_latest = df
            latest_date = None
        
        allocations = []
        for _, row in df_latest.iterrows():
            allocations.append({
                'industry': _safe_str(row.get('行业类别')),
                'weight': _safe_float(row.get('占净值比例')),
                'market_value': _safe_float(row.get('市值')),
            })
        
        # Sort by weight descending
        allocations.sort(key=lambda x: x['weight'], reverse=True)
        
        return {
            'code': code,
            'allocations': allocations,
            'report_date': _safe_str(latest_date) if latest_date else None,
        }
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error in industry allocation for {code}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{code}/manager-detail")
async def get_fund_manager_detail(
    code: str,
    current_user: User = Depends(get_current_user)
):
    """
    Get detailed fund manager information.
    """
    try:
        loop = asyncio.get_running_loop()
        
        # Get fund basic info first
        fund_info = await loop.run_in_executor(None, get_fund_basic_info, code)
        
        manager_detail = {
            'code': code,
            'fund_name': fund_info.get('name', code) if fund_info else code,
            'managers': [],
            'company': fund_info.get('company', '') if fund_info else '',
        }
        
        try:
            # Try to get manager info from AkShare
            df = await loop.run_in_executor(
                None,
                lambda: ak.fund_manager_em(symbol=code)
            )
            
            if df is not None and not df.empty:
                for _, row in df.iterrows():
                    manager_detail['managers'].append({
                        'name': _safe_str(row.get('基金经理')),
                        'start_date': _safe_str(row.get('任职起始日期')),
                        'end_date': _safe_str(row.get('任职终止日期', '至今')),
                        'tenure_days': _safe_float(row.get('任职天数')),
                        'tenure_return': _safe_float(row.get('任期回报')),
                        'best_return': _safe_float(row.get('最佳回报')),
                    })
        except Exception as e:
            print(f"Error getting manager info for {code}: {e}")
            # Continue with empty managers list
        
        return manager_detail
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error in manager detail for {code}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ==================== Market Overview Endpoints ====================

@router.get("/market/indices")
async def get_market_indices(current_user: User = Depends(get_current_user)):
    """
    Get major market indices (上证、深证、创业板、科创50等).
    """
    try:
        loop = asyncio.get_running_loop()
        df = await loop.run_in_executor(None, ak.stock_zh_index_spot_em)
        
        if df is None or df.empty:
            return {'indices': [], 'timestamp': datetime.now().isoformat()}
        
        # Filter for major indices
        major_codes = ['000001', '399001', '399006', '000688', '000300', '000016', '000905']
        indices = []
        
        for _, row in df.iterrows():
            code = _safe_str(row.get('代码'))
            if code in major_codes:
                indices.append({
                    'code': code,
                    'name': _safe_str(row.get('名称')),
                    'price': _safe_float(row.get('最新价')),
                    'change_pct': _safe_float(row.get('涨跌幅')),
                    'change_val': _safe_float(row.get('涨跌额')),
                    'volume': _safe_float(row.get('成交量')),
                    'amount': _safe_float(row.get('成交额')),
                    'high': _safe_float(row.get('最高')),
                    'low': _safe_float(row.get('最低')),
                    'open': _safe_float(row.get('今开')),
                    'prev_close': _safe_float(row.get('昨收')),
                })
        
        # Sort by predefined order
        order = {c: i for i, c in enumerate(major_codes)}
        indices.sort(key=lambda x: order.get(x['code'], 999))
        
        return {
            'indices': indices,
            'timestamp': datetime.now().isoformat(),
        }
    except Exception as e:
        print(f"Error fetching market indices: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/market/sectors")
async def get_market_sectors(
    limit: int = 10,
    current_user: User = Depends(get_current_user)
):
    """
    Get industry sector performance ranking.
    """
    try:
        loop = asyncio.get_running_loop()
        df = await loop.run_in_executor(None, ak.stock_board_industry_name_em)
        
        if df is None or df.empty:
            return {'sectors': [], 'timestamp': datetime.now().isoformat()}
        
        # Sort by change percentage
        df['涨跌幅'] = pd.to_numeric(df['涨跌幅'], errors='coerce')
        df_sorted = df.sort_values('涨跌幅', ascending=False)
        
        # Get top gainers and losers
        top_gainers = []
        for _, row in df_sorted.head(limit).iterrows():
            top_gainers.append({
                'name': _safe_str(row.get('板块名称')),
                'change_pct': _safe_float(row.get('涨跌幅')),
                'turnover_rate': _safe_float(row.get('换手率')),
                'leading_stock': _safe_str(row.get('领涨股票')),
                'leading_change': _safe_float(row.get('领涨股票-涨跌幅')),
                'total_amount': _safe_float(row.get('总成交额')),
            })
        
        top_losers = []
        for _, row in df_sorted.tail(limit).iloc[::-1].iterrows():
            top_losers.append({
                'name': _safe_str(row.get('板块名称')),
                'change_pct': _safe_float(row.get('涨跌幅')),
                'turnover_rate': _safe_float(row.get('换手率')),
                'leading_stock': _safe_str(row.get('领涨股票')),
                'leading_change': _safe_float(row.get('领涨股票-涨跌幅')),
                'total_amount': _safe_float(row.get('总成交额')),
            })
        
        return {
            'top_gainers': top_gainers,
            'top_losers': top_losers,
            'timestamp': datetime.now().isoformat(),
        }
    except Exception as e:
        print(f"Error fetching market sectors: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/market/southbound")
async def get_southbound_flow(current_user: User = Depends(get_current_user)):
    """
    Get southbound capital flow (港股通南向资金).
    """
    try:
        data = await asyncio.to_thread(widget_service.get_southbound_flow, 10)

        # 转换为市场概览页面需要的格式
        today = {
            'south_money': 0.0,
            'hk_sh_net': 0.0,
            'hk_sz_net': 0.0,
        }
        if data.get('latest'):
            today['south_money'] = data['latest'].get('south_money', 0.0)
            today['hk_sh_net'] = data['latest'].get('hk_sh_net', 0.0)
            today['hk_sz_net'] = data['latest'].get('hk_sz_net', 0.0)

        # 历史数据转换，单位统一为亿元
        recent = []
        for item in data.get('history', []):
            recent.append({
                'date': item.get('date', ''),
                'south_money': item.get('south_money', 0.0),
            })

        return {
            'today': today,
            'recent': recent,
            'timestamp': data.get('updated_at', datetime.now().isoformat()),
            'source': data.get('source', 'akshare'),
        }
    except Exception as e:
        print(f"Error fetching southbound flow: {e}")
        return {
            'today': {'south_money': 0, 'hk_sh_net': 0, 'hk_sz_net': 0},
            'recent': [],
            'timestamp': datetime.now().isoformat(),
            'message': 'Southbound data unavailable',
        }


@router.get("/market/sentiment")
async def get_market_sentiment(current_user: User = Depends(get_current_user)):
    """
    Get market sentiment indicators (涨跌家数、涨停跌停).
    """
    try:
        loop = asyncio.get_running_loop()
        
        sentiment = {
            'up_count': 0,
            'down_count': 0,
            'flat_count': 0,
            'limit_up': 0,
            'limit_down': 0,
            'timestamp': datetime.now().isoformat(),
        }
        
        try:
            # Get stock spot data to calculate up/down counts
            df = await loop.run_in_executor(None, ak.stock_zh_a_spot_em)
            
            if df is not None and not df.empty:
                df['涨跌幅'] = pd.to_numeric(df['涨跌幅'], errors='coerce')
                
                sentiment['up_count'] = int((df['涨跌幅'] > 0).sum())
                sentiment['down_count'] = int((df['涨跌幅'] < 0).sum())
                sentiment['flat_count'] = int((df['涨跌幅'] == 0).sum())
                sentiment['limit_up'] = int((df['涨跌幅'] >= 9.9).sum())
                sentiment['limit_down'] = int((df['涨跌幅'] <= -9.9).sum())
        except Exception as e:
            print(f"Error calculating sentiment: {e}")
        
        return sentiment
    except Exception as e:
        print(f"Error fetching market sentiment: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ==================== Enhanced Fund Detail Endpoints ====================

@router.get("/{code}/full-detail")
async def get_fund_full_detail(
    code: str,
    current_user: User = Depends(get_current_user)
):
    """
    Get comprehensive fund details including basic info, performance, holdings, manager.
    """
    try:
        loop = asyncio.get_running_loop()
        
        # Parallel fetch all data
        async def fetch_basic_info():
            """Get detailed basic info from xueqiu."""
            try:
                df = await loop.run_in_executor(
                    None,
                    lambda: ak.fund_individual_basic_info_xq(symbol=code)
                )
                if df is not None and not df.empty:
                    # Convert to dict
                    info_dict = dict(zip(df['item'], df['value']))
                    return {
                        'name': _safe_str(info_dict.get('基金名称', code)),
                        'company': _safe_str(info_dict.get('基金公司', '')),
                        'fund_type': _safe_str(info_dict.get('基金类型', '')),
                        'inception_date': _safe_str(info_dict.get('成立时间', '')),
                        'size': _safe_str(info_dict.get('最新规模', '')),
                        'manager': _safe_str(info_dict.get('基金经理', '')),
                    }
            except Exception as e:
                print(f"Error fetching basic info from xueqiu: {e}")
            # Fallback to simple lookup
            return await loop.run_in_executor(None, get_fund_basic_info, code)
        
        async def fetch_nav_history():
            return await loop.run_in_executor(None, get_fund_nav_history, code, 365)
        
        async def fetch_holdings():
            return await loop.run_in_executor(None, get_fund_holdings_list, code)
        
        async def fetch_ranking_data():
            """Get fund ranking data from market."""
            try:
                for fund_type in ["股票型", "混合型", "指数型", "债券型", "QDII", "FOF"]:
                    df = await loop.run_in_executor(
                        None, 
                        lambda ft=fund_type: ak.fund_open_fund_rank_em(symbol=ft)
                    )
                    if df is not None and not df.empty:
                        fund_row = df[df['基金代码'] == code]
                        if not fund_row.empty:
                            row = fund_row.iloc[0]
                            return {
                                'fund_type': fund_type,
                                'nav': _safe_float(row.get('单位净值')),
                                'acc_nav': _safe_float(row.get('累计净值')),
                                'return_1w': _safe_float(row.get('近1周')),
                                'return_1m': _safe_float(row.get('近1月')),
                                'return_3m': _safe_float(row.get('近3月')),
                                'return_6m': _safe_float(row.get('近6月')),
                                'return_1y': _safe_float(row.get('近1年')),
                                'return_2y': _safe_float(row.get('近2年')),
                                'return_3y': _safe_float(row.get('近3年')),
                                'return_ytd': _safe_float(row.get('今年来')),
                                'return_since_inception': _safe_float(row.get('成立来')),
                                'fee': _safe_str(row.get('手续费')),
                            }
            except Exception as e:
                print(f"Error fetching ranking data: {e}")
            return None
        
        async def fetch_manager():
            """Get fund manager info from TuShare (more detailed) or fallback to xueqiu."""
            managers = []
            
            # Try TuShare first for detailed manager info
            if TS_PRO:
                try:
                    # Convert fund code to TuShare format (e.g., 000001 -> 000001.OF)
                    ts_code = f"{code}.OF"
                    df = await loop.run_in_executor(
                        None,
                        lambda: TS_PRO.fund_manager(ts_code=ts_code)
                    )
                    if df is not None and not df.empty:
                        # Filter to current managers (end_date is None or empty)
                        current_managers = df[(df['end_date'].isna()) | (df['end_date'] == '')]
                        if current_managers.empty:
                            # If no current managers, use most recent ones
                            current_managers = df.sort_values('begin_date', ascending=False).head(3)
                        
                        for _, row in current_managers.iterrows():
                            name = _safe_str(row.get('name', ''))
                            if not name:
                                continue
                            
                            begin_date = _safe_str(row.get('begin_date', ''))
                            end_date = _safe_str(row.get('end_date', ''))
                            resume = _safe_str(row.get('resume', ''))
                            edu = _safe_str(row.get('edu', ''))
                            gender = _safe_str(row.get('gender', ''))
                            birth_year = _safe_str(row.get('birth_year', ''))
                            
                            # Calculate tenure days
                            tenure_days = 0
                            if begin_date:
                                try:
                                    start = datetime.strptime(begin_date, '%Y%m%d')
                                    end = datetime.now() if not end_date else datetime.strptime(end_date, '%Y%m%d')
                                    tenure_days = (end - start).days
                                except:
                                    pass
                            
                            # Format dates for display
                            display_begin = f"{begin_date[:4]}-{begin_date[4:6]}-{begin_date[6:]}" if len(begin_date) == 8 else begin_date
                            display_end = '至今' if not end_date else f"{end_date[:4]}-{end_date[4:6]}-{end_date[6:]}"
                            
                            managers.append({
                                'name': name,
                                'start_date': display_begin,
                                'end_date': display_end,
                                'tenure_days': tenure_days,
                                'tenure_return': 0,  # Would need additional calculation
                                'education': edu,
                                'gender': '男' if gender == 'M' else ('女' if gender == 'F' else ''),
                                'birth_year': birth_year,
                                'resume': resume[:500] if resume else '',  # Truncate long resumes
                            })
                        
                        if managers:
                            return managers
                except Exception as e:
                    print(f"TuShare fund_manager failed for {code}: {e}")
            
            # Fallback to xueqiu for basic info
            try:
                df = await loop.run_in_executor(
                    None,
                    lambda: ak.fund_individual_basic_info_xq(symbol=code)
                )
                if df is not None and not df.empty:
                    # Extract manager names from the basic info
                    manager_row = df[df['item'] == '基金经理']
                    if not manager_row.empty:
                        manager_names = _safe_str(manager_row.iloc[0]['value'])
                        if manager_names and manager_names != '<NA>':
                            # Split multiple managers
                            names = [n.strip() for n in manager_names.replace('、', ' ').split()]
                            for name in names:
                                if name:
                                    managers.append({
                                        'name': name,
                                        'start_date': '',
                                        'end_date': '至今',
                                        'tenure_days': 0,
                                        'tenure_return': 0,
                                        'education': '',
                                        'gender': '',
                                        'birth_year': '',
                                        'resume': '',
                                    })
            except Exception as e:
                print(f"Error fetching manager from xueqiu: {e}")
            
            return managers
        
        async def fetch_industry_allocation():
            """Get industry allocation."""
            try:
                # Use current year as date parameter
                current_year = str(datetime.now().year)
                try:
                    df = await loop.run_in_executor(
                        None,
                        lambda: ak.fund_portfolio_industry_allocation_em(symbol=code, date=current_year)
                    )
                except ValueError as ve:
                    # AkShare bug: some funds have malformed data
                    print(f"AkShare ValueError for {code} industry allocation: {ve}")
                    # Try previous year
                    try:
                        df = await loop.run_in_executor(
                            None,
                            lambda: ak.fund_portfolio_industry_allocation_em(symbol=code, date=str(int(current_year) - 1))
                        )
                    except Exception:
                        return []
                
                if df is not None and not df.empty:
                    allocations = []
                    for _, row in df.iterrows():
                        industry = _safe_str(row.get('行业类别'))
                        weight = _safe_float(row.get('占净值比例'))
                        if industry and weight > 0:
                            allocations.append({
                                'industry': industry,
                                'weight': weight,
                            })
                    allocations.sort(key=lambda x: x['weight'], reverse=True)
                    return allocations[:10]  # Top 10
            except Exception as e:
                print(f"Error fetching industry allocation: {e}")
            return []
        
        # Execute all fetches in parallel
        results = await asyncio.gather(
            fetch_basic_info(),
            fetch_nav_history(),
            fetch_holdings(),
            fetch_ranking_data(),
            fetch_manager(),
            fetch_industry_allocation(),
            return_exceptions=True
        )
        
        basic_info = results[0] if not isinstance(results[0], Exception) else {}
        nav_history = results[1] if not isinstance(results[1], Exception) else []
        holdings = results[2] if not isinstance(results[2], Exception) else []
        ranking_data = results[3] if not isinstance(results[3], Exception) else None
        managers = results[4] if not isinstance(results[4], Exception) else []
        industry_allocation = results[5] if not isinstance(results[5], Exception) else []
        
        # Calculate risk metrics from NAV history
        risk_metrics = {}
        if nav_history and len(nav_history) >= 20:
            try:
                calculator = RiskMetricsCalculator()
                risk_metrics = calculator.calculate_all_metrics(nav_history)
            except Exception as e:
                print(f"Error calculating risk metrics: {e}")
        
        return sanitize_for_json({
            'code': code,
            'basic_info': {
                'name': basic_info.get('name', code) if basic_info else code,
                'company': basic_info.get('company', '') if basic_info else '',
                'fund_type': basic_info.get('fund_type', '') or (ranking_data.get('fund_type', '') if ranking_data else ''),
                'inception_date': basic_info.get('inception_date', '') if basic_info else '',
                'size': basic_info.get('size', '') if basic_info else '',
            },
            'nav': {
                'current': ranking_data.get('nav', 0) if ranking_data else 0,
                'accumulated': ranking_data.get('acc_nav', 0) if ranking_data else 0,
                'history': nav_history[-90:] if nav_history else [],  # Last 90 days
            },
            'performance': ranking_data if ranking_data else {},
            'risk_metrics': risk_metrics,
            'holdings': holdings[:10] if holdings else [],  # Top 10 holdings
            'industry_allocation': industry_allocation,
            'managers': managers if managers else (
                # Use manager from basic_info as fallback
                [{'name': n.strip(), 'start_date': '', 'end_date': '至今', 'tenure_days': 0, 'tenure_return': 0}
                 for n in basic_info.get('manager', '').replace('、', ' ').split() if n.strip()]
                if basic_info and basic_info.get('manager') else []
            ),
            'timestamp': datetime.now().isoformat(),
        })
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error fetching full fund detail for {code}: {e}")
        raise HTTPException(status_code=500, detail=str(e))

