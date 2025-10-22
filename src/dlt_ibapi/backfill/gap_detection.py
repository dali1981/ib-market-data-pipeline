"""
Gap detection utilities for market data backfilling.

Identifies missing date ranges in historical data using market calendars
that account for both weekends and exchange-specific holidays.
"""

from datetime import date
from typing import List, Set, Tuple, Optional

import pandas as pd

from .market_calendar import get_market_calendar


def trading_day_range(start: date, end: date, exchange: str = "NYSE") -> List[date]:
    """
    Generate list of actual trading days between start and end dates.

    Uses market calendar to exclude weekends AND exchange-specific holidays
    (e.g., Independence Day, Thanksgiving, Christmas, etc.).

    Args:
        start: Start date (inclusive)
        end: End date (inclusive)
        exchange: Exchange code (default: "NYSE")

    Returns:
        List of trading days as date objects

    Example:
        >>> days = trading_day_range(date(2025, 7, 1), date(2025, 7, 10), "NYSE")
        >>> # Excludes July 4th (Independence Day) + weekends
    """
    calendar = get_market_calendar(exchange)
    return calendar.get_trading_days(start, end)


def business_day_range(start: date, end: date) -> List[date]:
    """
    Generate list of business days (weekdays only) between start and end dates.

    DEPRECATED: Use trading_day_range() instead for accurate market trading days.

    This function only excludes weekends, NOT market holidays.
    Kept for backward compatibility.

    Args:
        start: Start date (inclusive)
        end: End date (inclusive)

    Returns:
        List of business days as date objects

    Raises:
        ValueError: If start_date > end_date
    """
    if start > end:
        raise ValueError("start_date must be <= end_date")
    return pd.bdate_range(start, end).date.tolist()


def missing_windows(
    present_dates: Set[date],
    start: date,
    end: date,
    exchange: str = "NYSE",
) -> List[Tuple[date, date]]:
    """
    Find contiguous windows of missing dates within a date range.

    Uses market calendar to identify actual trading days (excludes weekends AND holidays).

    Args:
        present_dates: Set of dates that already have data
        start: Start of desired date range
        end: End of desired date range
        exchange: Exchange code for market calendar (default: "NYSE")

    Returns:
        List of (start_date, end_date) tuples representing missing windows

    Example:
        >>> present = {date(2024, 1, 2), date(2024, 1, 3), date(2024, 1, 8)}
        >>> missing = missing_windows(present, date(2024, 1, 1), date(2024, 1, 10))
        >>> # Returns gaps only for actual trading days
        >>> # Excludes weekends AND market holidays (e.g., New Year's Day)
    """
    # Get all desired trading days in range (excludes weekends + holidays)
    desired = trading_day_range(start, end, exchange)

    # Find missing dates
    missing = [d for d in desired if d not in present_dates]

    if not missing:
        return []

    # Group into contiguous windows
    windows = []
    window_start = missing[0]
    prev_date = window_start

    for curr_date in missing[1:]:
        # Check if current date is consecutive business day
        days_diff = (pd.Timestamp(curr_date) - pd.Timestamp(prev_date)).days

        if days_diff == 1:
            # Consecutive day, continue window
            prev_date = curr_date
        else:
            # Gap detected, close current window and start new one
            windows.append((window_start, prev_date))
            window_start = curr_date
            prev_date = curr_date

    # Close final window
    windows.append((window_start, prev_date))

    return windows


def validate_date_range(start: date, end: date) -> None:
    """
    Validate that date range is logical.

    Args:
        start: Start date
        end: End date

    Raises:
        ValueError: If start > end
    """
    if start > end:
        raise ValueError("start_date must be <= end_date")
