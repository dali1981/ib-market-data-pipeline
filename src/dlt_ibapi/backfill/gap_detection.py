"""
Gap detection utilities for market data backfilling.

Identifies missing date ranges in historical data using business day calendars.
"""

from datetime import date
from typing import List, Set, Tuple

import pandas as pd


def business_day_range(start: date, end: date) -> List[date]:
    """
    Generate list of business days (trading days) between start and end dates.

    Uses pandas business day calendar (excludes weekends, does NOT exclude holidays).
    For exchange-specific holidays, use a custom calendar.

    Args:
        start: Start date (inclusive)
        end: End date (inclusive)

    Returns:
        List of business days as date objects
    """
    return pd.bdate_range(start, end).date.tolist()


def missing_windows(
    present_dates: Set[date],
    start: date,
    end: date,
) -> List[Tuple[date, date]]:
    """
    Find contiguous windows of missing dates within a date range.

    Uses business day calendar (excludes weekends).

    Args:
        present_dates: Set of dates that already have data
        start: Start of desired date range
        end: End of desired date range

    Returns:
        List of (start_date, end_date) tuples representing missing windows

    Example:
        >>> present = {date(2024, 1, 2), date(2024, 1, 3), date(2024, 1, 8)}
        >>> missing = missing_windows(present, date(2024, 1, 1), date(2024, 1, 10))
        >>> # Returns: [(2024-01-04, 2024-01-05), (2024-01-09, 2024-01-10)]
        >>> # (Assuming 01-06, 01-07 are weekend)
    """
    # Get all desired business days in range
    desired = business_day_range(start, end)

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
        raise ValueError(f"Start date {start} cannot be after end date {end}")
