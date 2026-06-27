"""
Utility functions for data processing and environment management.
"""
import os
import math
from datetime import datetime, timedelta, time
from typing import Dict, Any
import pandas as pd
import numpy as np

from .config import ENV_FILE


def get_market_cache_ttl(trading_ttl: int = 60, max_ttl: int = 86400) -> int:
    """
    根据当前时间计算市场数据缓存 TTL。
    
    - 交易时段返回 trading_ttl（默认60秒）
    - 休市时段返回到下一次开盘的秒数（午间休市→下午开盘，收盘→次日开盘）
    - 周末和法定节假日自动顺延到下一个交易日开盘
    
    Args:
        trading_ttl: 交易时段的缓存秒数，默认60秒
        max_ttl: 最大缓存秒数，默认24小时
    
    Returns:
        缓存 TTL 秒数
    """
    from src.data_sources.utils import is_trading_day
    from datetime import time as dt_time, date as dt_date

    now = datetime.now()
    current_t = now.time()
    today_str = now.strftime('%Y%m%d')

    morning_start = dt_time(9, 30)
    morning_end = dt_time(11, 30)
    afternoon_start = dt_time(13, 0)
    afternoon_end = dt_time(15, 0)

    # 今天不是交易日（周末或节假日），直接找到下一个交易日
    if not is_trading_day(today_str):
        next_trading_day = _find_next_trading_day(now.date())
        next_open = datetime.combine(next_trading_day, morning_start)
        seconds_until_open = int((next_open - now).total_seconds())
        return min(max(seconds_until_open + 60, 60), max_ttl)

    in_morning = morning_start <= current_t <= morning_end
    in_afternoon = afternoon_start <= current_t <= afternoon_end

    if in_morning or in_afternoon:
        return trading_ttl

    # 工作日休市时段
    if current_t < morning_start:
        next_open = datetime.combine(now.date(), morning_start)
    elif morning_end < current_t < afternoon_start:
        next_open = datetime.combine(now.date(), afternoon_start)
    else:
        # 收盘后，找下一个交易日
        next_trading_day = _find_next_trading_day(now.date() + timedelta(days=1))
        next_open = datetime.combine(next_trading_day, morning_start)

    seconds_until_open = int((next_open - now).total_seconds())
    return min(max(seconds_until_open + 60, 60), max_ttl)


def _find_next_trading_day(start_date) -> 'dt_date':
    """
    从 start_date 开始找下一个交易日（含当天）。
    
    Args:
        start_date: 开始日期
    
    Returns:
        下一个交易日的 date 对象
    """
    from src.data_sources.utils import is_trading_day
    from datetime import date as dt_date

    check_date = start_date
    for _ in range(30):
        if is_trading_day(check_date.strftime('%Y%m%d')):
            return check_date
        check_date += timedelta(days=1)
    return start_date + timedelta(days=1)


def sanitize_for_json(obj):
    """
    Recursively sanitize an object to ensure it's JSON-serializable.
    Converts nan/inf floats to None.
    """
    if isinstance(obj, dict):
        return {k: sanitize_for_json(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [sanitize_for_json(item) for item in obj]
    elif isinstance(obj, float):
        if math.isnan(obj) or math.isinf(obj):
            return None
        return obj
    elif isinstance(obj, (int, str, bool, type(None))):
        return obj
    else:
        # Try to convert to string for unknown types
        try:
            return str(obj)
        except:
            return None


def sanitize_data(data):
    """
    Recursively replace NaN/Inf and non-JSON types (like pd.NA) for JSON compliance.
    More comprehensive than sanitize_for_json.
    """
    if isinstance(data, dict):
        return {k: sanitize_data(v) for k, v in data.items()}
    elif isinstance(data, list):
        return [sanitize_data(v) for v in data]
    elif pd.isna(data):  # Handles None, np.nan, pd.NA, pd.NaT
        return None
    elif isinstance(data, (np.float64, np.float32, float)):
        if math.isnan(data) or math.isinf(data):
            return None
        return float(data)
    elif isinstance(data, (np.int64, np.int32, int)):
        return int(data)
    elif isinstance(data, (datetime, pd.Timestamp)):
        return data.strftime('%Y-%m-%d %H:%M:%S')
    return data


def load_env_file() -> Dict[str, str]:
    """
    Load environment variables from .env file.
    """
    env_vars = {}
    if os.path.exists(ENV_FILE):
        with open(ENV_FILE, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" in line:
                    key, value = line.split("=", 1)
                    env_vars[key.strip()] = value.strip()
    return env_vars


def save_env_file(updates: Dict[str, str]):
    """
    Update environment variables in .env file.
    Preserves existing variables and comments.
    """
    lines = []
    if os.path.exists(ENV_FILE):
        with open(ENV_FILE, "r", encoding="utf-8") as f:
            lines = f.readlines()

    key_map = {}
    for i, line in enumerate(lines):
        if line.strip() and not line.strip().startswith("#") and "=" in line:
            k = line.split("=", 1)[0].strip()
            key_map[k] = i

    for key, value in updates.items():
        if value is None:
            continue

        new_line = f"{key}={value}\n"
        if key in key_map:
            lines[key_map[key]] = new_line
        else:
            lines.append(new_line)

    with open(ENV_FILE, "w", encoding="utf-8") as f:
        f.writelines(lines)


def mask_api_key(key: str) -> str:
    """
    Mask an API key for display, showing only first and last 4 characters.
    """
    if not key:
        return ""
    if len(key) > 8:
        return key[:4] + "..." + key[-4:]
    return key
