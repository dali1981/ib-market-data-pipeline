"""
Download planner for optimizing IB API historical data requests.

Replaces "gap detection" concept with more general "download planning":
- Works for fresh downloads (no existing data)
- Works for incremental updates (has existing data, finds gaps)
- Respects IB API duration limits
- Aware of trading calendars (market hours)
- Reusable across all asset types (stocks, options, futures, etc.)

Key improvement over gap_detection.py:
- Batches are optimized for IB API (not split by weekends/holidays)
- Terminology is clearer ("plan" vs "gaps")
- Single source of truth for IB API limits
"""

from dataclasses import dataclass
from datetime import date, timedelta
from typing import List, Set, Optional, Tuple
import pandas as pd
from pandas_market_calendars import get_calendar

from dlt_ibapi.utils.logging import get_logger

logger = get_logger(__name__)


@dataclass
class IBDurationLimit:
    """
    IB API duration limit for a specific bar size.

    Attributes:
        duration_str: IB API duration string (e.g., "1 Y", "10 D")
        max_days: Maximum calendar days per request
        bar_size: Bar size this limit applies to
    """
    duration_str: str
    max_days: int
    bar_size: str


@dataclass
class DownloadPlan:
    """
    Optimized plan for downloading historical data from IB API.

    Attributes:
        batches: List of (start_date, end_date) tuples for API calls
        total_trading_days: Total number of trading days to download
        api_calls_required: Number of IB API calls needed
        strategy: Human-readable description of batching strategy
        bar_size: Bar size for this plan
        exchange: Exchange/calendar used for trading days
    """
    batches: List[Tuple[date, date]]
    total_trading_days: int
    api_calls_required: int
    strategy: str
    bar_size: str
    exchange: str

    def __str__(self) -> str:
        """Pretty print download plan."""
        return (
            f"Download Plan:\n"
            f"  Bar Size: {self.bar_size}\n"
            f"  Exchange: {self.exchange}\n"
            f"  Trading Days: {self.total_trading_days}\n"
            f"  API Calls: {self.api_calls_required}\n"
            f"  Strategy: {self.strategy}\n"
            f"  Batches: {len(self.batches)}"
        )


# IB API duration limits by bar size
# Source: https://interactivebrokers.github.io/tws-api/historical_bars.html
IB_DURATION_LIMITS = {
    "1 secs": IBDurationLimit("10 D", 10, "1 secs"),
    "5 secs": IBDurationLimit("10 D", 10, "5 secs"),
    "10 secs": IBDurationLimit("30 D", 30, "10 secs"),
    "15 secs": IBDurationLimit("30 D", 30, "15 secs"),
    "30 secs": IBDurationLimit("60 D", 60, "30 secs"),
    "1 min": IBDurationLimit("1 Y", 365, "1 min"),
    "2 mins": IBDurationLimit("1 Y", 365, "2 mins"),
    "3 mins": IBDurationLimit("1 Y", 365, "3 mins"),
    "5 mins": IBDurationLimit("1 Y", 365, "5 mins"),
    "10 mins": IBDurationLimit("1 Y", 365, "10 mins"),
    "15 mins": IBDurationLimit("1 Y", 365, "15 mins"),
    "20 mins": IBDurationLimit("1 Y", 365, "20 mins"),
    "30 mins": IBDurationLimit("1 Y", 365, "30 mins"),
    "1 hour": IBDurationLimit("1 Y", 365, "1 hour"),
    "2 hours": IBDurationLimit("1 Y", 365, "2 hours"),
    "3 hours": IBDurationLimit("1 Y", 365, "3 hours"),
    "4 hours": IBDurationLimit("1 Y", 365, "4 hours"),
    "8 hours": IBDurationLimit("1 Y", 365, "8 hours"),
    "1 day": IBDurationLimit("1 Y", 365, "1 day"),
    "1 week": IBDurationLimit("10 Y", 3650, "1 week"),
    "1 month": IBDurationLimit("10 Y", 3650, "1 month"),
}


class DownloadPlanner:
    """
    Creates optimal download plans for IB API historical data.

    Handles:
    - Trading calendar awareness (respects market hours, excludes weekends/holidays)
    - IB API duration limits (bar size dependent)
    - Existing data detection (gap analysis)
    - Batch optimization (minimize API calls)

    Reusable across all asset types (stocks, options, futures, etc.)

    Example (fresh download):
        >>> planner = DownloadPlanner(exchange="NYSE", bar_size="1 day")
        >>> plan = planner.create_plan(
        ...     start_date=date(2025, 1, 1),
        ...     end_date=date(2025, 11, 13),
        ...     existing_dates=None,
        ... )
        >>> print(plan.api_calls_required)
        1  # 317 days < 365-day limit

    Example (incremental update):
        >>> planner = DownloadPlanner(exchange="NYSE", bar_size="1 day")
        >>> plan = planner.create_plan(
        ...     start_date=date(2025, 1, 1),
        ...     end_date=date(2025, 11, 13),
        ...     existing_dates={date(2025, 1, 2), date(2025, 1, 3), ...},
        ... )
        >>> print(plan.api_calls_required)
        2  # Only download missing dates
    """

    def __init__(self, exchange: str = "NYSE", bar_size: str = "1 day"):
        """
        Initialize download planner.

        Args:
            exchange: Exchange code for trading calendar (e.g., "NYSE", "NASDAQ")
            bar_size: IB API bar size (e.g., "1 day", "1 hour", "1 min")
        """
        self.exchange = exchange
        self.bar_size = bar_size
        self.duration_limit = self._get_ib_duration_limit(bar_size)

        # Cache trading calendar for this exchange
        try:
            self._calendar = get_calendar(exchange)
        except Exception as e:
            logger.warning(
                f"Could not load calendar for {exchange}, using NYSE as fallback: {e}"
            )
            self._calendar = get_calendar("NYSE")

    def create_plan(
        self,
        start_date: date,
        end_date: date,
        existing_dates: Optional[Set[date]] = None,
    ) -> DownloadPlan:
        """
        Create optimized download plan.

        Args:
            start_date: Desired start date for data
            end_date: Desired end date for data
            existing_dates: Set of dates already in database (None = fresh download)

        Returns:
            DownloadPlan with batches optimized for IB API
        """
        # Get all trading days in range
        all_trading_days = self._get_trading_days(start_date, end_date)

        # Determine which days need to be downloaded
        if existing_dates is None:
            # Fresh download: get all trading days
            needed_dates = all_trading_days
            strategy = "fresh_download"
        else:
            # Incremental: only download missing dates
            needed_dates = [d for d in all_trading_days if d not in existing_dates]
            strategy = f"incremental_update ({len(existing_dates)} existing)"

        if not needed_dates:
            # No data needed
            return DownloadPlan(
                batches=[],
                total_trading_days=0,
                api_calls_required=0,
                strategy="no_data_needed",
                bar_size=self.bar_size,
                exchange=self.exchange,
            )

        # Create optimal batches respecting IB API limits
        batches = self._create_batches(needed_dates)

        return DownloadPlan(
            batches=batches,
            total_trading_days=len(needed_dates),
            api_calls_required=len(batches),
            strategy=strategy,
            bar_size=self.bar_size,
            exchange=self.exchange,
        )

    def _get_trading_days(self, start_date: date, end_date: date) -> List[date]:
        """
        Get list of valid trading days between start and end dates.

        Uses market calendar to exclude weekends and holidays.

        Args:
            start_date: Start date (inclusive)
            end_date: End date (inclusive)

        Returns:
            List of trading days (sorted)
        """
        # Get trading schedule from market calendar
        schedule = self._calendar.schedule(
            start_date=start_date,
            end_date=end_date,
        )

        # Extract dates
        trading_days = [d.date() for d in schedule.index]

        return sorted(trading_days)

    def _create_batches(self, needed_dates: List[date]) -> List[Tuple[date, date]]:
        """
        Create optimal batches from needed dates.

        Strategy:
        1. Group consecutive trading days together
        2. Split batches that exceed IB API duration limit
        3. Return list of (start, end) tuples

        Args:
            needed_dates: Sorted list of dates to download

        Returns:
            List of (start_date, end_date) tuples for batches
        """
        if not needed_dates:
            return []

        # First, group consecutive trading days into contiguous windows
        windows = self._group_consecutive_trading_days(needed_dates)

        # Then, split windows that exceed IB API duration limit
        batches = []
        for window_start, window_end in windows:
            window_batches = self._split_by_duration_limit(window_start, window_end)
            batches.extend(window_batches)

        return batches

    def _group_consecutive_trading_days(
        self, dates: List[date]
    ) -> List[Tuple[date, date]]:
        """
        Group consecutive trading days into windows.

        Key insight: Check if dates are consecutive in the TRADING calendar,
        not the regular calendar. This prevents splitting at weekends/holidays.

        Args:
            dates: Sorted list of dates

        Returns:
            List of (start, end) tuples for contiguous windows
        """
        if not dates:
            return []

        # Create lookup set for O(1) membership checks
        date_set = set(dates)

        windows = []
        window_start = dates[0]
        prev_date = dates[0]

        for curr_date in dates[1:]:
            # Check if curr_date is the immediate next trading day after prev_date
            if self._is_next_trading_day(prev_date, curr_date, date_set):
                # Continue current window
                prev_date = curr_date
            else:
                # Gap detected, close current window and start new one
                windows.append((window_start, prev_date))
                window_start = curr_date
                prev_date = curr_date

        # Add final window
        windows.append((window_start, prev_date))

        return windows

    def _is_next_trading_day(
        self, prev: date, curr: date, trading_days: Set[date]
    ) -> bool:
        """
        Check if curr is the immediate next trading day after prev.

        Args:
            prev: Previous date
            curr: Current date
            trading_days: Set of all trading days in the range

        Returns:
            True if curr is the next trading day, False otherwise
        """
        # Find the next trading day after prev
        temp = prev + timedelta(days=1)
        while temp <= curr:
            if temp in trading_days:
                # Found the next trading day
                return temp == curr
            temp += timedelta(days=1)

        return False

    def _split_by_duration_limit(
        self, start_date: date, end_date: date
    ) -> List[Tuple[date, date]]:
        """
        Split a date range into batches respecting IB API duration limit.

        Args:
            start_date: Window start date
            end_date: Window end date

        Returns:
            List of (start, end) tuples for batches (may be multiple if window is large)
        """
        max_days = self.duration_limit.max_days
        total_days = (end_date - start_date).days + 1

        if total_days <= max_days:
            # Window fits in one batch
            return [(start_date, end_date)]

        # Split window into multiple batches
        batches = []
        current_start = start_date

        while current_start <= end_date:
            # Calculate end of this batch (max_days from start or end_date, whichever is earlier)
            current_end = min(
                current_start + timedelta(days=max_days - 1),
                end_date,
            )

            batches.append((current_start, current_end))

            # Move to next batch
            current_start = current_end + timedelta(days=1)

        return batches

    def _get_ib_duration_limit(self, bar_size: str) -> IBDurationLimit:
        """
        Get IB API duration limit for bar size.

        Args:
            bar_size: IB API bar size (e.g., "1 day", "1 hour")

        Returns:
            IBDurationLimit for this bar size

        Raises:
            ValueError: If bar size is not recognized
        """
        limit = IB_DURATION_LIMITS.get(bar_size)

        if limit is None:
            raise ValueError(
                f"Unrecognized bar size: {bar_size}. "
                f"Valid options: {', '.join(IB_DURATION_LIMITS.keys())}"
            )

        return limit
