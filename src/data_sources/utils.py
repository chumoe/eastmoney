"""
Utility functions for data source operations.
Includes stock code normalization, date formatting, and data transformation utilities.
"""

import re
from datetime import datetime, timedelta
from typing import Optional


# Chinese A-share public holidays 2025-2026 (approximate, update as needed)
# Format: set of "YYYYMMDD" strings
_CHINA_HOLIDAYS = {
    # 2025
    "20250101", "20250128", "20250129", "20250130", "20250131",
    "20250203", "20250204", "20250404", "20250405", "20250501",
    "20250502", "20250505", "20250602", "20251001", "20251002",
    "20251003", "20251006", "20251007", "20251008",
    # 2026
    "20260101", "20260102", "20260216", "20260217", "20260218",
    "20260219", "20260220", "20260406", "20260501", "20260504",
    "20260619", "20261001", "20261002", "20261005", "20261006",
    "20261007",
}


def is_trading_day(date_str: str) -> bool:
    """
    Check if a date is a trading day (weekday, not a public holiday).

    Args:
        date_str: Date in YYYYMMDD format

    Returns:
        True if trading day, False otherwise
    """
    try:
        dt = datetime.strptime(str(date_str), '%Y%m%d')
    except ValueError:
        return False

    # Weekend check
    if dt.weekday() >= 5:  # 5=Saturday, 6=Sunday
        return False

    # Holiday check
    date_key = dt.strftime('%Y%m%d')
    if date_key in _CHINA_HOLIDAYS:
        return False

    return True


def get_latest_trade_date_local(max_days_back: int = 30, offset: int = 0) -> Optional[str]:
    """
    Get the most recent trading day using local calendar (no API dependency).

    Args:
        max_days_back: Maximum days to look back
        offset: Number of trading days to offset from the latest (0 = latest)

    Returns:
        Trade date in YYYYMMDD format, or None if not found
    """
    today = datetime.now()
    trading_days = []

    for i in range(max_days_back + 10):
        check_date = today - timedelta(days=i)
        date_str = check_date.strftime('%Y%m%d')
        if is_trading_day(date_str):
            trading_days.append(date_str)
            if len(trading_days) > offset + 5:
                break

    if len(trading_days) > offset:
        return trading_days[offset]
    return None


def normalize_stock_code(stock_code: str) -> str:
    """
    Extract and normalize a 6-digit A-share stock code from various input formats.

    Handles formats like:
    - "600000" -> "600000"
    - "600000.SH" -> "600000"
    - "SH600000" -> "600000"
    - "sz000001" -> "000001"

    Args:
        stock_code: Stock code in any format

    Returns:
        Normalized 6-digit stock code, or original if invalid
    """
    if not stock_code:
        return ""

    stock_code = str(stock_code).strip().upper()

    # Extract 6 consecutive digits
    for part in (stock_code.split(".")[0], stock_code):
        digits = "".join(ch for ch in part if ch.isdigit())
        if len(digits) == 6:
            return digits

    return stock_code


def add_exchange_suffix(stock_code: str) -> str:
    """
    Add exchange suffix to stock code for TuShare format.

    Rules:
    - 6xxxxx -> .SH (Shanghai Stock Exchange)
    - 0xxxxx, 3xxxxx -> .SZ (Shenzhen Stock Exchange, including ChiNext)
    - 688xxx -> .SH (STAR Market - 科创板)
    - 4xxxxx, 8xxxxx -> .BJ (Beijing Stock Exchange)

    Args:
        stock_code: 6-digit stock code

    Returns:
        Stock code with exchange suffix (e.g., "600000.SH")
    """
    code = normalize_stock_code(stock_code)

    if len(code) != 6:
        # Already has suffix or invalid
        if '.' in stock_code:
            return stock_code
        return code

    # Determine exchange
    if code.startswith('6'):
        return f"{code}.SH"  # Shanghai Stock Exchange
    elif code.startswith(('0', '3')):
        return f"{code}.SZ"  # Shenzhen Stock Exchange (including ChiNext)
    elif code.startswith('8') or code.startswith('4'):
        return f"{code}.BJ"  # Beijing Stock Exchange
    else:
        return code


def remove_exchange_suffix(ts_code: str) -> str:
    """
    Remove exchange suffix from TuShare format code.

    Args:
        ts_code: Code with suffix (e.g., "600000.SH")

    Returns:
        Plain 6-digit code (e.g., "600000")
    """
    return ts_code.split('.')[0] if '.' in ts_code else ts_code


def format_date_yyyymmdd(date_obj: Optional[datetime] = None) -> str:
    """
    Format datetime to YYYYMMDD string for TuShare API.

    Args:
        date_obj: datetime object, defaults to today

    Returns:
        Date string in YYYYMMDD format
    """
    if date_obj is None:
        date_obj = datetime.now()

    return date_obj.strftime('%Y%m%d')


def parse_date_yyyymmdd(date_str: str) -> Optional[datetime]:
    """
    Parse YYYYMMDD string to datetime object.

    Args:
        date_str: Date string in YYYYMMDD format

    Returns:
        datetime object or None if invalid
    """
    try:
        return datetime.strptime(str(date_str), '%Y%m%d')
    except:
        return None


def get_trading_date_range(days: int = 100) -> tuple[str, str]:
    """
    Get trading date range for API calls.

    Args:
        days: Number of calendar days to look back (will be adjusted for trading days)

    Returns:
        Tuple of (start_date, end_date) in YYYYMMDD format
    """
    end_date = datetime.now()
    # Add buffer for non-trading days (weekends, holidays)
    start_date = end_date - timedelta(days=int(days * 1.6))

    return (
        format_date_yyyymmdd(start_date),
        format_date_yyyymmdd(end_date)
    )


def normalize_fund_code(fund_code: str) -> str:
    """
    Normalize fund code (usually 6 digits).

    Args:
        fund_code: Fund code in any format

    Returns:
        Normalized fund code
    """
    code = str(fund_code).strip()
    # Remove any non-digit characters
    digits = "".join(ch for ch in code if ch.isdigit())
    return digits if digits else code


def is_valid_stock_code(stock_code: str) -> bool:
    """
    Check if a stock code is valid (6 digits).

    Args:
        stock_code: Stock code to validate

    Returns:
        True if valid, False otherwise
    """
    code = normalize_stock_code(stock_code)
    return len(code) == 6 and code.isdigit()


def is_valid_fund_code(fund_code: str) -> bool:
    """
    Check if a fund code is valid (6 digits).

    Args:
        fund_code: Fund code to validate

    Returns:
        True if valid, False otherwise
    """
    code = normalize_fund_code(fund_code)
    return len(code) == 6 and code.isdigit()


def get_exchange_from_code(stock_code: str) -> Optional[str]:
    """
    Determine exchange from stock code.

    Args:
        stock_code: 6-digit stock code

    Returns:
        Exchange code ('SH', 'SZ', 'BJ') or None
    """
    code = normalize_stock_code(stock_code)

    if len(code) != 6:
        return None

    if code.startswith('6'):
        return 'SH'  # Shanghai
    elif code.startswith(('0', '3')):
        return 'SZ'  # Shenzhen
    elif code.startswith(('4', '8')):
        return 'BJ'  # Beijing
    else:
        return None


def format_percentage(value: float, decimal_places: int = 2) -> str:
    """
    Format a number as percentage string.

    Args:
        value: Numeric value
        decimal_places: Number of decimal places

    Returns:
        Formatted percentage string (e.g., "3.45%")
    """
    try:
        return f"{float(value):.{decimal_places}f}%"
    except:
        return "N/A"


def format_amount(value: float, unit: str = "亿") -> str:
    """
    Format amount with unit.

    Args:
        value: Numeric value
        unit: Unit string (default: "亿")

    Returns:
        Formatted amount string (e.g., "123.45亿")
    """
    try:
        return f"{float(value):.2f}{unit}"
    except:
        return "N/A"


def safe_float(value, default: float = 0.0) -> float:
    """
    Safely convert value to float.

    Args:
        value: Value to convert
        default: Default value if conversion fails

    Returns:
        Float value or default
    """
    try:
        return float(value)
    except:
        return default


def safe_int(value, default: int = 0) -> int:
    """
    Safely convert value to int.

    Args:
        value: Value to convert
        default: Default value if conversion fails

    Returns:
        Int value or default
    """
    try:
        return int(value)
    except:
        return default


if __name__ == "__main__":
    # Test utilities
    print("Testing stock code normalization...")

    test_codes = [
        "600000",
        "600000.SH",
        "SH600000",
        "sz000001",
        "000001.SZ",
        "300750",
        "688001",
        "430001",
    ]

    for code in test_codes:
        normalized = normalize_stock_code(code)
        with_suffix = add_exchange_suffix(code)
        exchange = get_exchange_from_code(code)
        is_valid = is_valid_stock_code(code)

        print(f"\n{code}:")
        print(f"  Normalized: {normalized}")
        print(f"  With suffix: {with_suffix}")
        print(f"  Exchange: {exchange}")
        print(f"  Valid: {is_valid}")

    # Test date formatting
    print("\n\nTesting date formatting...")
    start, end = get_trading_date_range(100)
    print(f"100-day range: {start} to {end}")
