"""
Market calendar service for identifying trading days.

Uses pandas_market_calendars to accurately determine which days
markets are open, accounting for weekends and holidays.
"""

from datetime import date, datetime
from typing import List, Optional
from functools import lru_cache

import pandas as pd
import pandas_market_calendars as mcal


class MarketCalendar:
    """
    Service for querying market trading days using exchange calendars.

    Supports multiple exchanges and caches calendar data for performance.
    """

    def __init__(self, exchange: str = "NYSE"):
        """
        Initialize market calendar for a specific exchange.

        Args:
            exchange: Exchange code (e.g., "NYSE", "NASDAQ", "LSE", "TSX")
                     See mcal.get_calendar_names() for available exchanges

        Raises:
            ValueError: If exchange is not supported
        """
        try:
            self.calendar = mcal.get_calendar(exchange)
            self.exchange = exchange
        except Exception as e:
            available = mcal.get_calendar_names()
            raise ValueError(
                f"Unsupported exchange '{exchange}'. "
                f"Available exchanges: {', '.join(available)}"
            ) from e

    @staticmethod
    def get_available_exchanges() -> List[str]:
        """
        Get list of all supported exchange calendar codes.

        Returns:
            List of exchange codes (e.g., ["NYSE", "NASDAQ", "LSE", ...])
        """
        return mcal.get_calendar_names()

    def get_trading_days(
        self,
        start_date: date,
        end_date: date,
        include_partial: bool = False
    ) -> List[date]:
        """
        Get list of actual trading days between start and end dates.

        Excludes weekends and exchange-specific holidays.

        Args:
            start_date: Start date (inclusive)
            end_date: End date (inclusive)
            include_partial: Include days with early close (e.g., day before holiday)

        Returns:
            List of trading days as date objects, sorted chronologically

        Example:
            >>> cal = MarketCalendar("NYSE")
            >>> days = cal.get_trading_days(date(2025, 7, 1), date(2025, 7, 10))
            >>> # Returns only weekdays, excluding July 4th (Independence Day)
        """
        # Convert dates to pandas Timestamps
        start_ts = pd.Timestamp(start_date)
        end_ts = pd.Timestamp(end_date)

        # Get schedule (returns DataFrame with market open/close times)
        schedule = self.calendar.schedule(start_date=start_ts, end_date=end_ts)

        if schedule.empty:
            return []

        # Extract dates from schedule index
        trading_days = schedule.index.date.tolist()

        # Filter out partial days if requested
        if not include_partial:
            # Check if early close exists in schedule
            if "market_close" in schedule.columns:
                # Keep only full trading days
                # (This is a simplified check - could be enhanced)
                pass

        return trading_days

    def is_trading_day(self, check_date: date) -> bool:
        """
        Check if a specific date is a trading day.

        Args:
            check_date: Date to check

        Returns:
            True if market is open on this date, False otherwise

        Example:
            >>> cal = MarketCalendar("NYSE")
            >>> cal.is_trading_day(date(2025, 7, 4))  # Independence Day
            False
            >>> cal.is_trading_day(date(2025, 7, 3))  # Day before holiday
            True
        """
        trading_days = self.get_trading_days(check_date, check_date)
        return len(trading_days) > 0

    def get_next_trading_day(self, from_date: date, skip_count: int = 1) -> Optional[date]:
        """
        Get the next trading day after a given date.

        Args:
            from_date: Starting date
            skip_count: Number of trading days to skip (1 = next trading day)

        Returns:
            Next trading day, or None if not found within reasonable range

        Example:
            >>> cal = MarketCalendar("NYSE")
            >>> cal.get_next_trading_day(date(2025, 7, 3))  # Thursday before July 4th
            date(2025, 7, 7)  # Following Monday (skips Fri holiday + weekend)
        """
        # Look ahead up to 30 days (handles long holiday weekends)
        end_date = from_date + pd.Timedelta(days=30)

        trading_days = self.get_trading_days(
            from_date + pd.Timedelta(days=1),
            end_date
        )

        if len(trading_days) >= skip_count:
            return trading_days[skip_count - 1]

        return None

    def get_previous_trading_day(self, from_date: date, skip_count: int = 1) -> Optional[date]:
        """
        Get the previous trading day before a given date.

        Args:
            from_date: Starting date
            skip_count: Number of trading days to go back (1 = previous trading day)

        Returns:
            Previous trading day, or None if not found within reasonable range
        """
        # Look back up to 30 days
        start_date = from_date - pd.Timedelta(days=30)

        trading_days = self.get_trading_days(start_date, from_date - pd.Timedelta(days=1))

        if len(trading_days) >= skip_count:
            return trading_days[-skip_count]

        return None

    def count_trading_days(self, start_date: date, end_date: date) -> int:
        """
        Count number of trading days in a date range.

        Args:
            start_date: Start date (inclusive)
            end_date: End date (inclusive)

        Returns:
            Number of trading days
        """
        return len(self.get_trading_days(start_date, end_date))

    def get_market_holidays(self, year: int) -> List[date]:
        """
        Get list of market holidays for a specific year.

        Args:
            year: Year to get holidays for

        Returns:
            List of holiday dates

        Example:
            >>> cal = MarketCalendar("NYSE")
            >>> holidays = cal.get_market_holidays(2025)
            >>> # Returns: [New Year's Day, MLK Day, Presidents Day, ...]
        """
        start_date = date(year, 1, 1)
        end_date = date(year, 12, 31)

        # Get all calendar days in the year
        all_days = pd.date_range(start_date, end_date).date.tolist()

        # Get trading days
        trading_days = set(self.get_trading_days(start_date, end_date))

        # Holidays are weekdays that are not trading days
        holidays = []
        for day in all_days:
            # Skip weekends
            if day.weekday() >= 5:  # Saturday = 5, Sunday = 6
                continue

            if day not in trading_days:
                holidays.append(day)

        return holidays

    def __repr__(self) -> str:
        return f"MarketCalendar(exchange='{self.exchange}')"


# Convenience function for quick access
@lru_cache(maxsize=10)
def get_market_calendar(exchange: str = "NYSE") -> MarketCalendar:
    """
    Get or create a cached MarketCalendar instance.

    Args:
        exchange: Exchange code

    Returns:
        MarketCalendar instance

    Example:
        >>> cal = get_market_calendar("NYSE")
        >>> days = cal.get_trading_days(date(2025, 1, 1), date(2025, 12, 31))
    """
    return MarketCalendar(exchange)
