"""Business logic for batch calendar spread tick backfill."""

import time
from pathlib import Path
from datetime import date
from typing import Optional, List, Dict, Any
from structlog import get_logger
import pandas as pd

from .models import (
    BackfillBatchCalendarTicksParams,
    BackfillBatchCalendarTicksResult,
    BackfillTicksParams,
    BackfillTicksResult,
)
from .ticks import execute_backfill_ticks
from ..repositories import EarningsCalendarReader, OptionChainSnapshotReader, OptionBarsReader, EquityBarsReader
from ..strategies import (
    EarningsTimingCalculator,
    filter_tradable_earnings,
    run_batch_calendar_spread_backtest,
)
from ..config_loader import get_connection_config

logger = get_logger(__name__)


def load_top_n_from_strategy_selection(
    earnings_date: date,
    top_n: int,
    database_path: Path,
    earnings_dataset_name: str = "earnings",
    options_dataset_name: str = "options",
    stocks_dataset_name: str = "stocks",
    symbols_filter: Optional[List[str]] = None,
    earnings_timing_filter: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    Load top N calendar spread opportunities from strategy selection.

    Runs IV ratio ranking analysis and returns top N spreads.

    Args:
        earnings_date: Earnings date to analyze
        top_n: Number of top opportunities to return
        database_path: Path to data directory
        earnings_dataset_name: Earnings dataset name
        options_dataset_name: Options dataset name
        stocks_dataset_name: Stocks dataset name
        symbols_filter: Optional list of symbols to filter to (e.g., ['AAPL', 'MSFT'])
        earnings_timing_filter: Optional earnings timing filter ('PRE_MARKET' or 'AFTER_HOURS')

    Returns:
        List of spread dictionaries with keys: symbol, strike, short_expiry, long_expiry, right, earnings_timing

    Raises:
        ValueError: If insufficient data or no tradable earnings
    """
    logger.info(
        "loading_top_n_opportunities",
        earnings_date=earnings_date,
        top_n=top_n,
        symbols_filter=symbols_filter,
        earnings_timing_filter=earnings_timing_filter,
    )

    # Load earnings data for the specific date
    earnings_reader = EarningsCalendarReader(str(database_path), earnings_dataset_name)
    earnings_on_date = earnings_reader.get_earnings_on_date(earnings_date)

    if earnings_on_date.empty:
        raise ValueError(f"No earnings found for {earnings_date}")

    # Apply earnings timing filter if provided
    if earnings_timing_filter:
        earnings_on_date = earnings_on_date[earnings_on_date['earnings_time'] == earnings_timing_filter]
        if earnings_on_date.empty:
            raise ValueError(f"No {earnings_timing_filter} earnings found for {earnings_date}")

    # Apply symbols filter if provided
    if symbols_filter:
        earnings_on_date = earnings_on_date[earnings_on_date['symbol'].isin(symbols_filter)]
        if earnings_on_date.empty:
            filter_desc = f" for symbols {symbols_filter}"
            timing_desc = f" ({earnings_timing_filter})" if earnings_timing_filter else ""
            raise ValueError(f"No earnings found{timing_desc}{filter_desc} on {earnings_date}")

    logger.info(
        "found_earnings",
        count=len(earnings_on_date),
        symbols=earnings_on_date['symbol'].tolist(),
    )

    # Filter to tradable earnings (with option data)
    option_reader = OptionBarsReader(str(database_path), options_dataset_name)
    tradable_earnings = filter_tradable_earnings(earnings_on_date, option_reader)

    if tradable_earnings.empty:
        raise ValueError(f"No tradable earnings (with option data) found for {earnings_date}")

    logger.info(
        "tradable_earnings",
        count=len(tradable_earnings),
        symbols=tradable_earnings['symbol'].tolist(),
    )

    # Run batch backtest with IV calculation
    equity_reader = EquityBarsReader(str(database_path), stocks_dataset_name)
    results_df = run_batch_calendar_spread_backtest(
        earnings_df=tradable_earnings,
        option_reader=option_reader,
        equity_reader=equity_reader,
        option_type='C',
        bar_size='5 mins',
        progress=False,  # Disable progress in CLI
        calculate_iv=True,
    )

    if results_df.empty:
        raise ValueError(f"No successful backtests for {earnings_date}")

    # Filter to valid IV data
    valid_iv_df = results_df[
        results_df['iv_short_entry'].notna() &
        results_df['iv_long_entry'].notna() &
        results_df['iv_ratio_entry'].notna()
    ].copy()

    if valid_iv_df.empty:
        raise ValueError(f"No results with valid IV data for {earnings_date}")

    # Sort by IV ratio (descending) and take top N
    top_opportunities = valid_iv_df.sort_values('iv_ratio_entry', ascending=False).head(top_n)

    logger.info(
        "selected_top_opportunities",
        count=len(top_opportunities),
        mean_iv_ratio=top_opportunities['iv_ratio_entry'].mean(),
    )

    # Convert to list of dicts for batch backfill
    symbols_list = []
    for _, row in top_opportunities.iterrows():
        # Get earnings timing for this symbol
        symbol = row['symbol']
        earnings_timing = tradable_earnings[tradable_earnings['symbol'] == symbol].iloc[0]['earnings_time']

        symbols_list.append({
            'symbol': symbol,
            'strike': float(row['strike']),
            'short_expiry': pd.to_datetime(row['short_expiry']).date(),
            'long_expiry': pd.to_datetime(row['long_expiry']).date(),
            'right': row['option_type'],
            'iv_ratio': float(row['iv_ratio_entry']),
            'expected_pnl': float(row['pnl_per_contract']),
            'earnings_timing': earnings_timing,  # Add earnings timing
        })

    return symbols_list


def get_earnings_timing(
    symbol: str,
    earnings_date: date,
    database_path: Path,
    dataset_name: str = "earnings",
) -> str:
    """
    Fetch earnings timing from database.

    Args:
        symbol: Symbol to look up
        earnings_date: Date of earnings
        database_path: Path to data directory
        dataset_name: Earnings dataset name

    Returns:
        Earnings timing ('PRE_MARKET', 'AFTER_HOURS', or 'UNKNOWN')

    Raises:
        ValueError: If earnings not found
    """
    reader = EarningsCalendarReader(str(database_path), dataset_name)
    earnings = reader.get_earnings_on_date(earnings_date)

    symbol_earnings = earnings[earnings['symbol'] == symbol]
    if symbol_earnings.empty:
        raise ValueError(
            f"No earnings found for {symbol} on {earnings_date}. "
            f"Run 'dlt-ibapi load-earnings' first."
        )

    timing = symbol_earnings.iloc[0]['earnings_time']

    # Validate timing is not UNKNOWN
    if timing == 'UNKNOWN':
        raise ValueError(
            f"Earnings timing for {symbol} on {earnings_date} is UNKNOWN. "
            f"Please update earnings data with correct timing (PRE_MARKET or AFTER_HOURS)."
        )

    return timing


def execute_backfill_batch_calendar_ticks(
    params: BackfillBatchCalendarTicksParams,
    connection_config: Optional[any] = None,
) -> BackfillBatchCalendarTicksResult:
    """
    Execute batch calendar spread tick backfill.

    Downloads tick data for multiple calendar spreads based on strategy selection results.
    For each spread, downloads:
    - Short leg: entry + exit windows
    - Long leg: entry + exit windows

    Args:
        params: Batch backfill parameters
        connection_config: Optional IB connection config

    Returns:
        Result with per-symbol tick counts
    """
    from datetime import datetime as dt

    start_time = time.time()

    try:
        # Load config if not provided
        if connection_config is None:
            connection_config = get_connection_config()

        # Override client_id if provided
        if params.client_id is not None:
            connection_config.client_id = params.client_id

        # Initialize calculator
        calculator = EarningsTimingCalculator()

        # Check if any symbols have exit windows in the future (data not yet available)
        now = dt.now()
        future_symbols = []
        for symbol_data in params.symbols:
            symbol = symbol_data['symbol']
            earnings_timing = symbol_data.get('earnings_timing', 'UNKNOWN')

            if earnings_timing == 'AFTER_HOURS':
                # After-hours exit window is next day 9-10am
                exit_time = dt.combine(params.earnings_date + timedelta(days=1), time(10, 0))
                if exit_time > now:
                    future_symbols.append(symbol)

        if future_symbols:
            logger.warning(
                "future_exit_windows_detected",
                symbols=future_symbols,
                count=len(future_symbols),
                message="Some symbols have exit windows in the future - data may not be available yet",
            )

        # Results tracking
        successful_symbols: List[str] = []
        failed_symbols: List[dict] = []
        total_ticks = 0

        logger.info(
            "starting_batch_tick_backfill",
            symbols=params.symbols,
            earnings_date=params.earnings_date,
            future_symbols_count=len(future_symbols),
        )

        # Process each symbol
        for symbol_data in params.symbols:
            symbol = symbol_data['symbol']
            strike = symbol_data['strike']
            short_expiry = symbol_data['short_expiry']
            long_expiry = symbol_data['long_expiry']
            right = symbol_data.get('right', 'C')

            logger.info(
                "processing_symbol",
                symbol=symbol,
                strike=strike,
                short_expiry=short_expiry,
                long_expiry=long_expiry,
            )

            try:
                # Fetch earnings timing from database
                earnings_time = get_earnings_timing(
                    symbol=symbol,
                    earnings_date=params.earnings_date,
                    database_path=params.database_path,
                    dataset_name=params.earnings_dataset_name,
                )

                # Calculate windows
                windows = calculator.calculate_windows(
                    earnings_date=params.earnings_date,
                    earnings_time=earnings_time,
                )

                logger.info(
                    "calculated_windows",
                    symbol=symbol,
                    earnings_time=earnings_time,
                    entry_window=str(windows.entry),
                    exit_window=str(windows.exit),
                    download_entry=params.download_entry,
                    download_exit=params.download_exit,
                )

                # Download ticks for selected windows (based on --entry/--exit flags)
                scenarios = []
                if params.download_entry:
                    scenarios.extend([
                        ('short', short_expiry, 'entry', windows.entry),
                        ('long', long_expiry, 'entry', windows.entry),
                    ])
                if params.download_exit:
                    scenarios.extend([
                        ('short', short_expiry, 'exit', windows.exit),
                        ('long', long_expiry, 'exit', windows.exit),
                    ])

                symbol_ticks = 0

                for leg, expiry, window_type, window in scenarios:
                    tick_params = BackfillTicksParams(
                        symbol=symbol,
                        expiry=expiry,
                        strike=strike,
                        right=right,
                        start_time=window.start,
                        end_time=window.end,
                        database_path=params.database_path,
                        dataset_name=params.dataset_name,
                        pipeline_name=params.pipeline_name,
                        client_id=params.client_id,
                    )

                    result = execute_backfill_ticks(tick_params, connection_config)

                    if result.success:
                        symbol_ticks += result.total_ticks
                        logger.info(
                            "tick_download_success",
                            symbol=symbol,
                            leg=leg,
                            window_type=window_type,
                            ticks=result.total_ticks,
                        )
                    else:
                        logger.warning(
                            "tick_download_failed",
                            symbol=symbol,
                            leg=leg,
                            window_type=window_type,
                            error=result.error,
                        )

                successful_symbols.append(symbol)
                total_ticks += symbol_ticks

                logger.info(
                    "symbol_complete",
                    symbol=symbol,
                    symbol_ticks=symbol_ticks,
                )

            except Exception as e:
                logger.error(
                    "symbol_failed",
                    symbol=symbol,
                    error=str(e),
                )
                failed_symbols.append({
                    'symbol': symbol,
                    'error': str(e),
                })

        duration = time.time() - start_time

        logger.info(
            "batch_backfill_complete",
            successful=len(successful_symbols),
            failed=len(failed_symbols),
            total_ticks=total_ticks,
            duration=duration,
        )

        return BackfillBatchCalendarTicksResult(
            success=len(failed_symbols) == 0,
            earnings_date=params.earnings_date,
            successful_symbols=successful_symbols,
            failed_symbols=failed_symbols,
            total_ticks=total_ticks,
            pipeline_name=params.pipeline_name,
            output_path=params.database_path / params.dataset_name,
            duration_seconds=duration,
        )

    except Exception as e:
        duration = time.time() - start_time
        logger.error(
            "batch_backfill_failed",
            error=str(e),
            duration=duration,
        )

        return BackfillBatchCalendarTicksResult(
            success=False,
            earnings_date=params.earnings_date,
            successful_symbols=[],
            failed_symbols=[],
            total_ticks=0,
            pipeline_name=params.pipeline_name,
            output_path=params.database_path / params.dataset_name,
            duration_seconds=duration,
            error=str(e),
        )
