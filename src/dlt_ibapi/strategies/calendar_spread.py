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

from ..utils.black_scholes import implied_volatility


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
        iv_short_entry: IV of short leg at entry (optional)
        iv_long_entry: IV of long leg at entry (optional)
        iv_ratio_entry: Short IV / Long IV at entry (optional)
    """
    position: CalendarSpreadPosition
    pnl: float
    pnl_per_contract: float
    exit_time: datetime
    success: bool
    failure_reason: Optional[str] = None
    iv_short_entry: Optional[float] = None
    iv_long_entry: Optional[float] = None
    iv_ratio_entry: Optional[float] = None

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
            'iv_short_entry': self.iv_short_entry,
            'iv_long_entry': self.iv_long_entry,
            'iv_ratio_entry': self.iv_ratio_entry,
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
    earnings_time: Literal['PRE_MARKET', 'AFTER_HOURS', 'UNKNOWN'],
    entry_hour: int = 15,
    entry_minute: int = 0,
    exit_hour_after_hours: int = 10,
    exit_minute_after_hours: int = 0,
    exit_hour_pre_market: int = 16,
    exit_minute_pre_market: int = 0,
) -> Tuple[datetime, datetime]:
    """
    Calculate entry and exit datetimes for calendar spread.

    Entry Strategy:
    - Default: Enter at 3:00pm (15:00) the day before earnings
    - Customizable via entry_hour and entry_minute parameters

    Exit Strategy (after earnings to capture IV crush):
    - AFTER_HOURS or UNKNOWN: Default exit at 10:00am next day (after IV crush overnight)
    - PRE_MARKET: Default exit at 4:00pm (16:00) on earnings day (after IV crush during day)
    - Customizable via exit_hour_* and exit_minute_* parameters

    Args:
        earnings_date: Date of earnings announcement
        earnings_time: When earnings will be announced
        entry_hour: Hour of entry (0-23), default 15 (3pm)
        entry_minute: Minute of entry (0-59), default 0
        exit_hour_after_hours: Exit hour for AFTER_HOURS earnings (0-23), default 10 (10am)
        exit_minute_after_hours: Exit minute for AFTER_HOURS earnings (0-59), default 0
        exit_hour_pre_market: Exit hour for PRE_MARKET earnings (0-23), default 16 (4pm)
        exit_minute_pre_market: Exit minute for PRE_MARKET earnings (0-59), default 0

    Returns:
        Tuple of (entry_dt, exit_dt)

    Examples:
        >>> # Default times
        >>> calculate_entry_exit_times(date(2025, 11, 13), 'AFTER_HOURS')
        (datetime(2025, 11, 12, 15, 0, 0), datetime(2025, 11, 14, 10, 0, 0))

        >>> # Custom times: Enter 3:55pm, exit 9:35am
        >>> calculate_entry_exit_times(date(2025, 11, 13), 'AFTER_HOURS',
        ...                            entry_hour=15, entry_minute=55,
        ...                            exit_hour_after_hours=9, exit_minute_after_hours=35)
        (datetime(2025, 11, 12, 15, 55, 0), datetime(2025, 11, 14, 9, 35, 0))
    """
    # Entry: specified time day before earnings
    entry_dt = datetime.combine(earnings_date, datetime.min.time()) - timedelta(days=1) + \
               timedelta(hours=entry_hour, minutes=entry_minute)

    if earnings_time == 'PRE_MARKET':
        # Exit after PRE_MARKET earnings: specified time on earnings day
        exit_dt = datetime.combine(earnings_date, datetime.min.time()) + \
                 timedelta(hours=exit_hour_pre_market, minutes=exit_minute_pre_market)
    else:  # AFTER_HOURS or UNKNOWN
        # Exit after AFTER_HOURS earnings: specified time next trading day
        exit_dt = datetime.combine(earnings_date, datetime.min.time()) + \
                 timedelta(days=1, hours=exit_hour_after_hours, minutes=exit_minute_after_hours)

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


def calculate_implied_volatility_at_time(
    option_price: float,
    spot_price: float,
    strike: float,
    expiry: date,
    target_time: datetime,
    option_type: Literal['C', 'P'],
    risk_free_rate: float = 0.05
) -> Optional[float]:
    """
    Calculate implied volatility for an option at a specific time.

    Args:
        option_price: Market price of the option
        spot_price: Underlying spot price
        strike: Strike price
        expiry: Option expiration date
        target_time: Time of valuation
        option_type: 'C' for call, 'P' for put
        risk_free_rate: Annualized risk-free rate (default 5%)

    Returns:
        Implied volatility (annualized) or None if calculation fails
    """
    # Calculate time to expiry in years
    days_to_expiry = (expiry - target_time.date()).days
    if days_to_expiry <= 0:
        return None

    time_to_expiry = days_to_expiry / 365.0

    # Convert option type
    opt_type = 'call' if option_type == 'C' else 'put'

    try:
        iv = implied_volatility(
            market_price=option_price,
            S=spot_price,
            K=strike,
            T=time_to_expiry,
            r=risk_free_rate,
            option_type=opt_type
        )
        return iv if iv > 0 else None
    except Exception:
        return None


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
    spot_price: Optional[float] = None,
    calculate_iv: bool = False,
    entry_hour: int = 15,
    entry_minute: int = 0,
    exit_hour_after_hours: int = 10,
    exit_minute_after_hours: int = 0,
    exit_hour_pre_market: int = 16,
    exit_minute_pre_market: int = 0,
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
        earnings_date=earnings_date,
        earnings_time=earnings_time,
        entry_hour=entry_hour,
        entry_minute=entry_minute,
        exit_hour_after_hours=exit_hour_after_hours,
        exit_minute_after_hours=exit_minute_after_hours,
        exit_hour_pre_market=exit_hour_pre_market,
        exit_minute_pre_market=exit_minute_pre_market,
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

    # Calculate IV metrics if requested and spot price available
    iv_short = None
    iv_long = None
    iv_ratio = None

    if calculate_iv and spot_price is not None:
        iv_short = calculate_implied_volatility_at_time(
            option_price=short_entry,
            spot_price=spot_price,
            strike=strike,
            expiry=short_expiry,
            target_time=entry_dt,
            option_type=option_type
        )
        iv_long = calculate_implied_volatility_at_time(
            option_price=long_entry,
            spot_price=spot_price,
            strike=strike,
            expiry=long_expiry,
            target_time=entry_dt,
            option_type=option_type
        )

        if iv_short is not None and iv_long is not None and iv_long > 0:
            iv_ratio = iv_short / iv_long

    return CalendarSpreadResult(
        position=position,
        pnl=pnl,
        pnl_per_contract=pnl_per_contract,
        exit_time=exit_dt,
        success=True,
        failure_reason=None,
        iv_short_entry=iv_short,
        iv_long_entry=iv_long,
        iv_ratio_entry=iv_ratio,
    )
