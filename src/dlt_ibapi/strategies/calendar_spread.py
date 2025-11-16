"""
Calendar spread strategy components.

This module provides reusable, testable functions for backtesting
calendar spreads (horizontal time spreads) around earnings events.

A calendar spread involves:
- Selling a near-term option (short leg)
- Buying a far-term option (long leg)
- Same strike price
- Profits from time decay differential and IV crush
"""

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import List, Optional, Tuple, Literal
import pandas as pd


@dataclass
class CalendarSpreadPosition:
    """
    Represents a calendar spread position.

    Attributes:
        symbol: Underlying symbol
        strike: Strike price for both legs
        option_type: 'C' for calls, 'P' for puts
        short_expiry: Expiration date of short leg (sold)
        long_expiry: Expiration date of long leg (bought)
        entry_time: When position was entered
        entry_cost: Net debit paid to enter (per share)
    """
    symbol: str
    strike: float
    option_type: Literal['C', 'P']
    short_expiry: date
    long_expiry: date
    entry_time: datetime
    entry_cost: float

    def __post_init__(self):
        """Validate position parameters."""
        if self.long_expiry <= self.short_expiry:
            raise ValueError(
                f"Long expiry ({self.long_expiry}) must be after short expiry ({self.short_expiry})"
            )
        if self.entry_cost <= 0:
            raise ValueError(f"Entry cost must be positive, got {self.entry_cost}")


@dataclass
class CalendarSpreadResult:
    """
    Backtest result for a single calendar spread.

    Attributes:
        position: The spread position
        pnl: P&L when exited after earnings (per share)
        pnl_per_contract: P&L after earnings (per contract = x100)
        exit_time: When position was exited (after earnings)
        success: Whether backtest completed successfully
        failure_reason: Reason for failure if success=False
    """
    position: CalendarSpreadPosition
    pnl: float
    pnl_per_contract: float
    exit_time: datetime
    success: bool
    failure_reason: Optional[str] = None

    @property
    def pnl_pct(self) -> float:
        """P&L as percentage of entry cost."""
        if self.position and self.position.entry_cost > 0:
            return (self.pnl / self.position.entry_cost) * 100
        return 0.0

    def to_dict(self) -> dict:
        """Convert result to dictionary for DataFrame creation."""
        return {
            'symbol': self.position.symbol if self.position else None,
            'strike': self.position.strike if self.position else None,
            'option_type': self.position.option_type if self.position else None,
            'short_expiry': self.position.short_expiry if self.position else None,
            'long_expiry': self.position.long_expiry if self.position else None,
            'entry_time': self.position.entry_time if self.position else None,
            'entry_cost': self.position.entry_cost if self.position else None,
            'entry_cost_per_contract': self.position.entry_cost * 100 if self.position else None,
            'pnl': self.pnl,
            'pnl_pct': self.pnl_pct,
            'pnl_per_contract': self.pnl_per_contract,
            'exit_time': self.exit_time,
            'success': self.success,
            'failure_reason': self.failure_reason,
        }


def select_calendar_expirations(
    available_expirations: List[date],
    earnings_date: date,
    min_expirations: int = 2
) -> Optional[Tuple[date, date]]:
    """
    Select short and long expirations for calendar spread.

    Strategy:
    - Both expirations must be after earnings
    - Short = first expiration after earnings
    - Long = second expiration after earnings

    Args:
        available_expirations: List of available expiration dates
        earnings_date: Earnings announcement date
        min_expirations: Minimum required expirations (default 2)

    Returns:
        Tuple of (short_expiry, long_expiry) or None if insufficient expirations

    Example:
        >>> expirations = [date(2025, 11, 21), date(2025, 11, 28), date(2025, 12, 5)]
        >>> earnings = date(2025, 11, 13)
        >>> select_calendar_expirations(expirations, earnings)
        (date(2025, 11, 21), date(2025, 11, 28))
    """
    # Filter to expirations after earnings
    future_exps = [exp for exp in available_expirations if exp > earnings_date]

    # Sort by date
    future_exps.sort()

    # Need at least min_expirations
    if len(future_exps) < min_expirations:
        return None

    return (future_exps[0], future_exps[1])


def calculate_entry_exit_times(
    earnings_date: date,
    earnings_time: Literal['PRE_MARKET', 'AFTER_HOURS', 'UNKNOWN']
) -> Tuple[datetime, datetime]:
    """
    Calculate entry and exit datetimes for calendar spread.

    Entry Strategy:
    - Always enter at 3pm the day before earnings

    Exit Strategy (after earnings to capture IV crush):
    - AFTER_HOURS or UNKNOWN: Exit at 10am next day (after IV crush overnight)
    - PRE_MARKET: Exit at 4pm on earnings day (after IV crush during day)

    Args:
        earnings_date: Date of earnings announcement
        earnings_time: When earnings will be announced

    Returns:
        Tuple of (entry_dt, exit_dt)

    Example:
        >>> calculate_entry_exit_times(date(2025, 11, 13), 'AFTER_HOURS')
        (datetime(2025, 11, 12, 15, 0, 0), datetime(2025, 11, 14, 10, 0, 0))
    """
    # Entry: 3pm day before earnings
    entry_dt = datetime.combine(earnings_date, datetime.min.time()) - timedelta(days=1) + timedelta(hours=15)

    if earnings_time == 'PRE_MARKET':
        # Exit after PRE_MARKET earnings: Market close on earnings day (4pm)
        exit_dt = datetime.combine(earnings_date, datetime.min.time()) + timedelta(hours=16)
    else:  # AFTER_HOURS or UNKNOWN
        # Exit after AFTER_HOURS earnings: Next trading day 10am
        exit_dt = datetime.combine(earnings_date, datetime.min.time()) + timedelta(days=1, hours=10)

    return (entry_dt, exit_dt)


def get_option_price_at_time(
    option_bars: pd.DataFrame,
    target_time: datetime,
    price_column: str = 'close'
) -> Optional[float]:
    """
    Get option price at or just before target time.

    Uses the most recent bar at or before the target time.
    This handles gaps in hourly data (e.g., no 3pm bar, use 2pm).

    Args:
        option_bars: DataFrame with 'datetime' index or column and price columns
        target_time: Target datetime
        price_column: Which price column to extract (default 'close')

    Returns:
        Price at target time or None if no data available

    Example:
        >>> bars = pd.DataFrame({
        ...     'datetime': pd.to_datetime(['2025-11-12 14:00', '2025-11-12 15:00']),
        ...     'close': [1.0, 1.5]
        ... })
        >>> get_option_price_at_time(bars, datetime(2025, 11, 12, 15, 0))
        1.5
        >>> get_option_price_at_time(bars, datetime(2025, 11, 12, 15, 30))
        1.5  # Uses most recent (15:00)
    """
    # Ensure datetime column exists
    if 'datetime' not in option_bars.columns:
        if not isinstance(option_bars.index, pd.DatetimeIndex):
            raise ValueError("option_bars must have 'datetime' column or DatetimeIndex")
        df = option_bars.reset_index()
        df.columns = ['datetime'] + list(option_bars.columns)
    else:
        df = option_bars

    # Filter to bars at or before target time
    valid_bars = df[df['datetime'] <= target_time]

    if valid_bars.empty:
        return None

    # Get most recent bar
    return valid_bars.iloc[-1][price_column]


def backtest_single_calendar_spread(
    symbol: str,
    earnings_date: date,
    earnings_time: Literal['PRE_MARKET', 'AFTER_HOURS', 'UNKNOWN'],
    strike: float,
    option_type: Literal['C', 'P'],
    short_leg_bars: pd.DataFrame,
    long_leg_bars: pd.DataFrame,
    short_expiry: date,
    long_expiry: date,
) -> CalendarSpreadResult:
    """
    Backtest a single calendar spread for one earnings event.

    This is the core backtest function with all business logic.
    Data loading is handled by caller (dependency injection).

    Args:
        symbol: Underlying symbol
        earnings_date: Date of earnings announcement
        earnings_time: When earnings will be announced
        strike: Strike price for both legs
        option_type: 'C' for calls, 'P' for puts
        short_leg_bars: DataFrame with 'datetime' and 'close' columns for short leg
        long_leg_bars: DataFrame with 'datetime' and 'close' columns for long leg
        short_expiry: Expiration date of short leg
        long_expiry: Expiration date of long leg

    Returns:
        CalendarSpreadResult with P&L and metadata

    Example:
        >>> result = backtest_single_calendar_spread(
        ...     symbol='AAPL',
        ...     earnings_date=date(2025, 11, 13),
        ...     earnings_time='AFTER_HOURS',
        ...     strike=150.0,
        ...     option_type='C',
        ...     short_leg_bars=short_bars_df,
        ...     long_leg_bars=long_bars_df,
        ...     short_expiry=date(2025, 11, 21),
        ...     long_expiry=date(2025, 11, 28),
        ... )
        >>> result.pnl_per_contract_after
        25.0
    """
    # Calculate entry/exit times
    entry_dt, exit_dt = calculate_entry_exit_times(
        earnings_date, earnings_time
    )

    # Get entry prices
    short_entry = get_option_price_at_time(short_leg_bars, entry_dt)
    long_entry = get_option_price_at_time(long_leg_bars, entry_dt)

    if short_entry is None or long_entry is None:
        return CalendarSpreadResult(
            position=None,  # type: ignore
            pnl=0.0,
            pnl_per_contract=0.0,
            exit_time=exit_dt,
            success=False,
            failure_reason="Missing entry prices"
        )

    # Calculate entry cost (debit paid)
    entry_cost = long_entry - short_entry

    # Skip degenerate spreads
    if entry_cost <= 0.001:
        return CalendarSpreadResult(
            position=None,  # type: ignore
            pnl=0.0,
            pnl_per_contract=0.0,
            exit_time=exit_dt,
            success=False,
            failure_reason=f"Degenerate spread (entry_cost={entry_cost:.4f})"
        )

    # Get exit prices (after earnings)
    short_exit = get_option_price_at_time(short_leg_bars, exit_dt)
    long_exit = get_option_price_at_time(long_leg_bars, exit_dt)

    if short_exit is None or long_exit is None:
        return CalendarSpreadResult(
            position=None,  # type: ignore
            pnl=0.0,
            pnl_per_contract=0.0,
            exit_time=exit_dt,
            success=False,
            failure_reason="Missing exit prices"
        )

    # Create position
    position = CalendarSpreadPosition(
        symbol=symbol,
        strike=strike,
        option_type=option_type,
        short_expiry=short_expiry,
        long_expiry=long_expiry,
        entry_time=entry_dt,
        entry_cost=entry_cost
    )

    # Calculate P&L (exit after earnings)
    spread_value = long_exit - short_exit
    pnl = spread_value - entry_cost
    pnl_per_contract = pnl * 100

    return CalendarSpreadResult(
        position=position,
        pnl=pnl,
        pnl_per_contract=pnl_per_contract,
        exit_time=exit_dt,
        success=True,
        failure_reason=None
    )
