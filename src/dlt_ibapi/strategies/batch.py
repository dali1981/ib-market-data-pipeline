"""
Batch backtest utilities for running strategies across multiple events.

This module provides functions to run backtests across multiple earnings
events efficiently with progress tracking.
"""

import pandas as pd
from datetime import date, timedelta
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


def _find_best_strike_with_sufficient_expirations(
    option_reader: OptionBarsReader,
    underlying: str,
    target_strike: float,
    option_type: str,
    bar_size: str,
    earnings_date: date,
    min_expirations: int = 2,
) -> Optional[Tuple[float, str]]:
    """
    Find the best strike with sufficient expirations for calendar spread.

    Strategy:
    1. Try target strike (ATM) first - if it has ≥2 expirations after earnings, use it
    2. Otherwise, find strike closest to ATM that has ≥2 expirations
    3. If no strike has ≥2 expirations, return None

    Args:
        option_reader: OptionBarsReader for querying available strikes
        underlying: Underlying symbol
        target_strike: Ideal strike (e.g., ATM)
        option_type: 'C' or 'P'
        bar_size: Preferred bar size (tries to match, falls back to any bar_size)
        earnings_date: Earnings date (need expirations AFTER this)
        min_expirations: Minimum required expirations (default 2)

    Returns:
        Tuple of (best_strike, actual_bar_size), or None if no strike has sufficient expirations
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

    # For each strike, count expirations after earnings
    strike_expiration_counts = {}
    for strike in available_strikes:
        expirations = option_reader.get_expirations_for_contract(
            underlying=underlying,
            strike=strike,
            option_type=option_type,
            bar_size=actual_bar_size
        )
        # Filter to expirations after earnings
        future_exps = [exp for exp in expirations if exp > earnings_date]
        strike_expiration_counts[strike] = len(future_exps)

    # Filter to strikes with sufficient expirations
    valid_strikes = [
        strike for strike, count in strike_expiration_counts.items()
        if count >= min_expirations
    ]

    if not valid_strikes:
        return None

    # Prefer target strike if it has sufficient expirations
    if target_strike in valid_strikes:
        return (target_strike, actual_bar_size)

    # Otherwise, find nearest strike with sufficient expirations
    best_strike = min(valid_strikes, key=lambda s: abs(s - target_strike))
    return (float(best_strike), actual_bar_size)


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
    progress: bool = True,
    calculate_iv: bool = False,
    entry_hour: int = 15,
    entry_minute: int = 0,
    exit_hour_after_hours: int = 10,
    exit_minute_after_hours: int = 0,
    exit_hour_pre_market: int = 16,
    exit_minute_pre_market: int = 0,
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

            # Find best strike with sufficient expirations (≥2 after earnings)
            strike_result = _find_best_strike_with_sufficient_expirations(
                option_reader=option_reader,
                underlying=symbol,
                target_strike=target_strike,
                option_type=option_type,
                bar_size=bar_size,
                earnings_date=earnings_date,
                min_expirations=2,
            )

            if strike_result is None:
                if progress:
                    _log_progress(f"  Spot: ${spot_price:.2f}, ATM Strike: ${target_strike}")
                    _log_progress(f"  ⚠️  No strike with ≥2 expirations after earnings")
                continue

            actual_strike, actual_bar_size = strike_result

            if progress:
                strike_msg = f"  Spot: ${spot_price:.2f}, ATM Strike: ${target_strike}"
                if actual_strike != target_strike:
                    strike_msg += f" → Using ${actual_strike} (best with ≥2 expirations)"
                else:
                    strike_msg += f" ✓"
                if actual_bar_size != bar_size:
                    strike_msg += f", bar_size: {actual_bar_size}"
                _log_progress(strike_msg)

            # Get available expirations for the selected strike (already validated to have ≥2)
            expirations = option_reader.get_expirations_for_contract(
                underlying=symbol,
                strike=actual_strike,
                option_type=option_type,
                bar_size=actual_bar_size
            )

            # Select expirations (should always succeed since we validated ≥2 exist)
            exp_result = select_calendar_expirations(expirations, earnings_date)
            if exp_result is None:
                # This should never happen since we already checked ≥2 expirations
                if progress:
                    _log_progress(f"  ⚠️  Unexpected: Failed to select expirations")
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
                spot_price=spot_price if calculate_iv else None,
                calculate_iv=calculate_iv,
                entry_hour=entry_hour,
                entry_minute=entry_minute,
                exit_hour_after_hours=exit_hour_after_hours,
                exit_minute_after_hours=exit_minute_after_hours,
                exit_hour_pre_market=exit_hour_pre_market,
                exit_minute_pre_market=exit_minute_pre_market,
            )

            if result.success:
                results.append(result.to_dict())
                if progress:
                    _log_progress(
                        f"  ✓ Calendar spread (Spot: ${spot_price:.2f}, Strike: ${actual_strike}): "
                        f"Entry=${result.to_dict()['entry_cost_per_contract']:.2f}, "
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
