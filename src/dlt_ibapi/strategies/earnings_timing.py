"""
Earnings timing calculator for determining entry/exit windows for option strategies.

This module provides utilities for calculating entry and exit times for calendar spreads
based on earnings announcement timing (PRE_MARKET, AFTER_HOURS, UNKNOWN).
"""

from datetime import date, datetime, time, timedelta
from typing import Tuple, Literal
from dataclasses import dataclass

from ..backfill.market_calendar import get_previous_trading_day, get_market_calendar

EarningsTime = Literal["PRE_MARKET", "AFTER_HOURS", "UNKNOWN"]


@dataclass
class TradingWindow:
    """Represents a trading window with start and end times."""

    start: datetime
    end: datetime

    def __str__(self) -> str:
        return f"{self.start.strftime('%Y-%m-%d %H:%M')} to {self.end.strftime('%Y-%m-%d %H:%M')}"

    def to_dict(self) -> dict:
        """Convert to dictionary format."""
        return {
            'start': self.start,
            'end': self.end,
            'start_str': self.start.strftime('%Y-%m-%d %H:%M'),
            'end_str': self.end.strftime('%Y-%m-%d %H:%M'),
        }


@dataclass
class EarningsTradeWindows:
    """Entry and exit windows for an earnings trade."""

    entry: TradingWindow
    exit: TradingWindow
    earnings_date: date
    earnings_time: EarningsTime

    def __str__(self) -> str:
        return (
            f"Earnings: {self.earnings_date} ({self.earnings_time})\n"
            f"Entry: {self.entry}\n"
            f"Exit: {self.exit}"
        )

    def to_dict(self) -> dict:
        """Convert to dictionary format."""
        return {
            'earnings_date': self.earnings_date,
            'earnings_time': self.earnings_time,
            'entry': self.entry.to_dict(),
            'exit': self.exit.to_dict(),
        }


class EarningsTimingCalculator:
    """
    Calculate entry and exit windows for option strategies based on earnings timing.

    This class encapsulates the logic for determining when to enter and exit calendar spreads
    around earnings announcements. The timing depends on whether earnings are announced
    pre-market or after-hours.

    Default Strategy:
    - Entry: 3:00 PM - 4:00 PM day before earnings
    - Exit: 9:00 AM - 10:00 AM day after earnings announcement

    Timing Rules:
    - PRE_MARKET earnings: Enter previous day 3-4pm, exit same day 9-10am
    - AFTER_HOURS earnings: Enter same day 3-4pm, exit next day 9-10am
    - UNKNOWN earnings: Should be resolved to PRE_MARKET or AFTER_HOURS before use
    """

    def __init__(
        self,
        entry_start_time: time = time(15, 0),  # 3:00 PM
        entry_end_time: time = time(16, 0),     # 4:00 PM
        exit_start_time: time = time(9, 0),     # 9:00 AM
        exit_end_time: time = time(10, 0),      # 10:00 AM
    ):
        """
        Initialize calculator with custom entry/exit times.

        Args:
            entry_start_time: Start of entry window (default: 3:00 PM)
            entry_end_time: End of entry window (default: 4:00 PM)
            exit_start_time: Start of exit window (default: 9:00 AM)
            exit_end_time: End of exit window (default: 10:00 AM)
        """
        self.entry_start_time = entry_start_time
        self.entry_end_time = entry_end_time
        self.exit_start_time = exit_start_time
        self.exit_end_time = exit_end_time

    def calculate_windows(
        self,
        earnings_date: date,
        earnings_time: EarningsTime,
    ) -> EarningsTradeWindows:
        """
        Calculate entry and exit windows for an earnings trade.

        Uses market calendar to respect trading days (skips weekends/holidays).

        Args:
            earnings_date: Date of earnings announcement
            earnings_time: Timing of earnings (PRE_MARKET, AFTER_HOURS, or UNKNOWN)

        Returns:
            EarningsTradeWindows with entry and exit windows

        Examples:
            >>> calc = EarningsTimingCalculator()
            >>> # Monday Nov 17 PRE_MARKET -> Entry: Friday Nov 15
            >>> windows = calc.calculate_windows(date(2025, 11, 17), "PRE_MARKET")
            >>> print(windows.entry)
            2025-11-15 15:00 to 2025-11-15 16:00
            >>> print(windows.exit)
            2025-11-17 09:00 to 2025-11-17 10:00
        """
        if earnings_time == "PRE_MARKET":
            # PRE_MARKET: Enter previous trading day, exit same day
            entry_date = get_previous_trading_day(earnings_date, exchange="NYSE")
            exit_date = earnings_date
        elif earnings_time == "AFTER_HOURS":
            # AFTER_HOURS: Enter same day, exit next trading day
            cal = get_market_calendar("NYSE")
            entry_date = earnings_date
            next_day = cal.get_next_trading_day(earnings_date, skip_count=1)
            if next_day is None:
                raise ValueError(
                    f"Cannot find next trading day after {earnings_date}. "
                    f"This may indicate a market closure or data issue."
                )
            exit_date = next_day
        else:
            # UNKNOWN: Should not be used - resolve timing first
            raise ValueError(
                f"Cannot calculate windows for UNKNOWN earnings timing. "
                f"Please resolve to PRE_MARKET or AFTER_HOURS first for {earnings_date}"
            )

        # Create entry window
        entry_window = TradingWindow(
            start=datetime.combine(entry_date, self.entry_start_time),
            end=datetime.combine(entry_date, self.entry_end_time),
        )

        # Create exit window
        exit_window = TradingWindow(
            start=datetime.combine(exit_date, self.exit_start_time),
            end=datetime.combine(exit_date, self.exit_end_time),
        )

        return EarningsTradeWindows(
            entry=entry_window,
            exit=exit_window,
            earnings_date=earnings_date,
            earnings_time=earnings_time,
        )

    def calculate_tick_windows(
        self,
        earnings_date: date,
        earnings_time: EarningsTime,
    ) -> Tuple[Tuple[datetime, datetime], Tuple[datetime, datetime]]:
        """
        Calculate tick data windows (convenience method returning tuples).

        Returns:
            ((entry_start, entry_end), (exit_start, exit_end))

        Examples:
            >>> calc = EarningsTimingCalculator()
            >>> (entry_start, entry_end), (exit_start, exit_end) = calc.calculate_tick_windows(
            ...     date(2025, 11, 17), "PRE_MARKET"
            ... )
            >>> print(entry_start)
            2025-11-16 15:00:00
        """
        windows = self.calculate_windows(earnings_date, earnings_time)
        return (
            (windows.entry.start, windows.entry.end),
            (windows.exit.start, windows.exit.end),
        )

    @staticmethod
    def format_datetime_for_ib(dt: datetime) -> str:
        """
        Format datetime for IB API commands.

        Args:
            dt: Datetime to format

        Returns:
            Formatted string like "20251116 15:00:00"

        Examples:
            >>> dt = datetime(2025, 11, 16, 15, 0)
            >>> EarningsTimingCalculator.format_datetime_for_ib(dt)
            '20251116 15:00:00'
        """
        return dt.strftime('%Y%m%d %H:%M:%S')

    @staticmethod
    def format_datetime_for_cli(dt: datetime) -> str:
        """
        Format datetime for CLI arguments.

        Args:
            dt: Datetime to format

        Returns:
            Formatted string like "2025-11-16 15:00"

        Examples:
            >>> dt = datetime(2025, 11, 16, 15, 0)
            >>> EarningsTimingCalculator.format_datetime_for_cli(dt)
            '2025-11-16 15:00'
        """
        return dt.strftime('%Y-%m-%d %H:%M')
