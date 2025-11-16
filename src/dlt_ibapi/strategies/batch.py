"""
Batch backtest utilities for running strategies across multiple events.

This module provides functions to run backtests across multiple earnings
events efficiently with progress tracking.
"""

import pandas as pd
from datetime import timedelta
from typing import Literal, Optional, Tuple

try:
    from tqdm.auto import tqdm
    TQDM_AVAILABLE = True
except ImportError:
    TQDM_AVAILABLE = False

from ..repositories import OptionBarsReader, EquityBarsReader
from .calendar_spread import (
    select_calendar_expirations,
    backtest_single_calendar_spread,
)
from .strike_selection import select_atm_strike


def _find_nearest_available_strike(
    option_reader: OptionBarsReader,
    underlying: str,
    target_strike: float,
    option_type: str,
    bar_size: str,
) -> Optional[Tuple[float, str]]:
    """
    Find the nearest available strike to the target strike.

    If the exact target strike exists, returns it.
    Otherwise, returns the closest available strike.

    Args:
        option_reader: OptionBarsReader for querying available strikes
        underlying: Underlying symbol
        target_strike: Ideal strike (e.g., ATM)
        option_type: 'C' or 'P'
        bar_size: Preferred bar size (tries to match, falls back to any bar_size)

    Returns:
        Tuple of (nearest_strike, actual_bar_size), or None if no strikes available
    """
    # Try with specified bar_size first
    contracts = option_reader.get_contracts_for_underlying(
        underlying=underlying,
        bar_size=bar_size,
    )

    actual_bar_size = bar_size

    # If no data with that bar_size, try without bar_size filter
    if contracts.empty:
        contracts = option_reader.get_contracts_for_underlying(
            underlying=underlying,
            bar_size=None,
        )
        if not contracts.empty:
            # Use whatever bar_size is available (pick the first one)
            actual_bar_size = contracts['bar_size'].iloc[0]

    if contracts.empty:
        return None

    # Filter to the specific option type
    type_contracts = contracts[contracts['right'] == option_type.upper()]

    if type_contracts.empty:
        return None

    available_strikes = sorted(type_contracts['strike'].unique())

    if not available_strikes:
        return None

    # Check if exact strike exists
    if target_strike in available_strikes:
        return (target_strike, actual_bar_size)

    # Find nearest strike
    nearest = min(available_strikes, key=lambda s: abs(s - target_strike))
    return (float(nearest), actual_bar_size)


def _log_progress(message: str):
    """Helper to write progress messages (tqdm-aware if available)."""
    if TQDM_AVAILABLE:
        tqdm.write(message)
    else:
        print(message)


def run_batch_calendar_spread_backtest(
    earnings_df: pd.DataFrame,
    option_reader: OptionBarsReader,
    equity_reader: EquityBarsReader,
    option_type: Literal['C', 'P'] = 'C',
    bar_size: str = '1 hour',
    progress: bool = True
) -> pd.DataFrame:
    """
    Run calendar spread backtest across multiple earnings events.

    This function:
    1. Loads spot prices to determine ATM strikes
    2. Loads option data for each earnings event
    3. Runs calendar spread backtest
    4. Aggregates results into DataFrame

    Args:
        earnings_df: DataFrame with columns: symbol, earnings_date, earnings_time
        option_reader: OptionBarsReader for loading option data
        equity_reader: EquityBarsReader for loading spot prices
        option_type: 'C' for calls, 'P' for puts (default 'C')
        bar_size: Bar size for option data (default '1 hour')
        progress: Show progress bar (default True)

    Returns:
        DataFrame with successful backtest results

    Example:
        >>> from dlt_ibapi.repositories import (
        ...     EarningsCalendarReader,
        ...     OptionBarsReader,
        ...     EquityBarsReader
        ... )
        >>> from dlt_ibapi.strategies import filter_tradable_earnings
        >>> from dlt_ibapi.strategies.batch import run_batch_calendar_spread_backtest
        >>>
        >>> # Load data
        >>> earnings_reader = EarningsCalendarReader('./data', 'earnings')
        >>> option_reader = OptionBarsReader('./data_delta', 'options')
        >>> equity_reader = EquityBarsReader('./data_delta', 'stocks')
        >>>
        >>> # Filter to tradable earnings
        >>> all_earnings = earnings_reader.get_upcoming_earnings(days_ahead=30)
        >>> tradable = filter_tradable_earnings(all_earnings, option_reader)
        >>>
        >>> # Run backtest
        >>> results_df = run_batch_calendar_spread_backtest(
        ...     tradable, option_reader, equity_reader, option_type='C'
        ... )
        >>> print(f"Successful: {len(results_df)}/{len(tradable)} backtests")
    """
    results = []

    # Create iterator with optional progress bar
    if progress and TQDM_AVAILABLE:
        iterator = tqdm(earnings_df.iterrows(), total=len(earnings_df), desc="Backtesting")
    else:
        iterator = earnings_df.iterrows()

    for idx, row in iterator:
        symbol = row['symbol']
        earnings_date = pd.to_datetime(row['earnings_date']).date()
        earnings_time = row['earnings_time']

        if progress:
            _log_progress(f"\nProcessing {symbol} - {earnings_date} ({earnings_time})...")

        try:
            # Get spot price to determine ATM strike
            spot_data = equity_reader.get_bars(
                symbol=symbol,
                bar_size='1 day',
                start_date=earnings_date - timedelta(days=5),
                end_date=earnings_date + timedelta(days=1)
            )

            if spot_data.empty:
                if progress:
                    _log_progress(f"  ⚠️  No spot price data")
                continue

            spot_price = float(spot_data['close'].iloc[-1])
            target_strike = select_atm_strike(spot_price, 'auto')

            # Find nearest available strike (may differ from ATM) and actual bar_size
            strike_result = _find_nearest_available_strike(
                option_reader=option_reader,
                underlying=symbol,
                target_strike=target_strike,
                option_type=option_type,
                bar_size=bar_size,
            )

            if strike_result is None:
                if progress:
                    _log_progress(f"  Spot: ${spot_price:.2f}, ATM Strike: ${target_strike}")
                    _log_progress(f"  ⚠️  No option data for {option_type} options")
                continue

            actual_strike, actual_bar_size = strike_result

            if progress:
                strike_msg = f"  Spot: ${spot_price:.2f}, ATM Strike: ${target_strike}"
                if actual_strike != target_strike:
                    strike_msg += f" → Using ${actual_strike} (nearest available)"
                else:
                    strike_msg += f" ✓"
                if actual_bar_size != bar_size:
                    strike_msg += f", bar_size: {actual_bar_size}"
                _log_progress(strike_msg)

            # Get available expirations for the actual strike
            expirations = option_reader.get_expirations_for_contract(
                underlying=symbol,
                strike=actual_strike,
                option_type=option_type,
                bar_size=actual_bar_size
            )

            if not expirations:
                if progress:
                    _log_progress(f"  ⚠️  No expirations for strike {actual_strike}")
                continue

            # Select expirations
            exp_result = select_calendar_expirations(expirations, earnings_date)
            if exp_result is None:
                if progress:
                    _log_progress(f"  ⚠️  Insufficient expirations (need 2, got {len(expirations)})")
                continue

            short_exp, long_exp = exp_result

            # Load option bars
            short_leg_bars = option_reader.load_option_leg_bars(
                underlying=symbol,
                expiry=short_exp,
                strike=actual_strike,
                option_type=option_type,
                bar_size=actual_bar_size
            )

            long_leg_bars = option_reader.load_option_leg_bars(
                underlying=symbol,
                expiry=long_exp,
                strike=actual_strike,
                option_type=option_type,
                bar_size=actual_bar_size
            )

            if short_leg_bars is None or long_leg_bars is None:
                if progress:
                    _log_progress(f"  ⚠️  Missing option bars data")
                continue

            # Run backtest
            result = backtest_single_calendar_spread(
                symbol=symbol,
                earnings_date=earnings_date,
                earnings_time=earnings_time,
                strike=actual_strike,
                option_type=option_type,
                short_leg_bars=short_leg_bars,
                long_leg_bars=long_leg_bars,
                short_expiry=short_exp,
                long_expiry=long_exp,
            )

            if result.success:
                results.append(result.to_dict())
                if progress:
                    _log_progress(
                        f"  ✓ Calendar spread: Entry=${result.to_dict()['entry_cost_per_contract']:.2f}, "
                        f"P&L=${result.to_dict()['pnl_per_contract']:.2f}"
                    )
            else:
                if progress:
                    _log_progress(f"  ⚠️  Backtest failed: {result.failure_reason}")

        except Exception as e:
            if progress:
                _log_progress(f"  ❌ Error: {e}")
            continue

    return pd.DataFrame(results)
