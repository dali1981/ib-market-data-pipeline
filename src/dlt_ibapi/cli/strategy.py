"""Strategy selection business logic - testable, framework-independent.

Executes IV ranking and strategy selection for calendar spread candidates.
Uses Pydantic models for type safety and dependency injection for I/O.
"""

import time
from pathlib import Path
from typing import Optional

import pandas as pd

from dlt_ibapi.cli.models import (
    IVRankParams,
    IVRankResult,
    IVRankCandidate,
    StrategySelectParams,
    StrategySelectResult,
)
from dlt_ibapi.repositories import (
    EarningsCalendarReader,
    EquityBarsReader,
    OptionBarsReader,
    OptionChainSnapshotReader,
)
from dlt_ibapi.strategies.batch import run_batch_calendar_spread_backtest
from dlt_ibapi.strategies.iv_ranking import (
    assign_iv_quartiles,
    rank_and_filter_candidates,
    calculate_selection_statistics,
)
from dlt_ibapi.strategies.earnings_filter import filter_tradable_earnings
from dlt_ibapi.utils.logging import get_logger

logger = get_logger(__name__)


def execute_iv_rank(
    params: IVRankParams,
) -> IVRankResult:
    """
    Execute IV ranking for calendar spread candidates.

    Ranks all symbols with earnings on specified date by IV ratio at entry.
    Uses existing batch backtest infrastructure with calculate_iv=True.

    Args:
        params: Validated IV ranking parameters (Pydantic model)

    Returns:
        IVRankResult with ranked candidates

    Example:
        >>> params = IVRankParams(
        ...     earnings_date=date(2025, 11, 13),
        ...     option_type='C',
        ...     top_n=10,
        ... )
        >>> result = execute_iv_rank(params)
        >>> assert result.success
        >>> assert len(result.ranked_candidates) <= 10
    """
    start_time = time.time()

    try:
        logger.info(
            "iv_rank_start",
            earnings_date=str(params.earnings_date),
            symbols=params.symbols,
            earnings_time=params.earnings_time,
        )

        # Step 1: Load earnings for date
        earnings_reader = EarningsCalendarReader(
            database_path=str(params.database_path),
            dataset_name=params.earnings_dataset,
        )

        earnings_df = earnings_reader.get_earnings_on_date(params.earnings_date)

        if earnings_df.empty:
            logger.warning(
                "no_earnings_found",
                earnings_date=str(params.earnings_date),
            )
            duration = time.time() - start_time
            return IVRankResult(
                success=False,
                earnings_date=params.earnings_date,
                total_symbols=0,
                tradable_symbols=0,
                ranked_candidates=[],
                duration_seconds=duration,
                error=f"No earnings found on {params.earnings_date}",
            )

        # Filter by symbols if provided
        if params.symbols:
            symbols_upper = [s.upper() for s in params.symbols]
            earnings_df = earnings_df[earnings_df['symbol'].isin(symbols_upper)]
            logger.info("filtered_by_symbols", count=len(earnings_df))

        # Filter by earnings time if provided
        if params.earnings_time:
            earnings_df = earnings_df[earnings_df['earnings_time'] == params.earnings_time]
            logger.info(
                "filtered_by_earnings_time",
                earnings_time=params.earnings_time,
                count=len(earnings_df),
            )

        if earnings_df.empty:
            logger.warning("no_earnings_after_filters")
            duration = time.time() - start_time
            return IVRankResult(
                success=False,
                earnings_date=params.earnings_date,
                total_symbols=0,
                tradable_symbols=0,
                ranked_candidates=[],
                duration_seconds=duration,
                error="No earnings found matching filters",
            )

        total_symbols = len(earnings_df)
        logger.info("total_earnings_symbols", count=total_symbols)

        # Step 2: Filter to tradable earnings (have option data)
        equity_reader = EquityBarsReader(
            database_path=str(params.database_path),
            dataset_name=params.stocks_dataset,
        )

        option_reader = OptionBarsReader(
            database_path=str(params.database_path),
            dataset_name=params.options_dataset,
        )

        chain_reader = OptionChainSnapshotReader(
            database_path=str(params.database_path),
            dataset_name=params.option_chains_dataset,
        )

        tradable_symbols_df = filter_tradable_earnings(
            earnings_df=earnings_df,
            option_reader=option_reader,
        )

        if tradable_symbols_df.empty:
            logger.warning("no_tradable_symbols")
            duration = time.time() - start_time
            return IVRankResult(
                success=False,
                earnings_date=params.earnings_date,
                total_symbols=total_symbols,
                tradable_symbols=0,
                ranked_candidates=[],
                duration_seconds=duration,
                error="No symbols have sufficient option data for calendar spreads",
            )

        tradable_count = len(tradable_symbols_df)
        logger.info("tradable_symbols_filtered", count=tradable_count)

        # Step 3: Run batch backtest with calculate_iv=True
        logger.info("running_batch_backtest_with_iv")
        results_df = run_batch_calendar_spread_backtest(
            earnings_df=tradable_symbols_df,
            equity_reader=equity_reader,
            option_reader=option_reader,
            option_type=params.option_type,
            bar_size=params.bar_size,
            entry_hour=params.entry_hour,
            entry_minute=params.entry_minute,
            calculate_iv=True,  # Critical: enables IV calculation
        )

        if results_df.empty:
            logger.warning("backtest_no_results")
            duration = time.time() - start_time
            return IVRankResult(
                success=False,
                earnings_date=params.earnings_date,
                total_symbols=total_symbols,
                tradable_symbols=tradable_count,
                ranked_candidates=[],
                duration_seconds=duration,
                error="Backtest produced no results (missing data or calculation errors)",
            )

        logger.info("backtest_complete", results_count=len(results_df))

        # Step 3.5: Merge earnings metadata and spot prices
        # Merge earnings_date and earnings_time from earnings_df
        earnings_metadata = tradable_symbols_df[['symbol', 'earnings_date', 'earnings_time']].copy()
        results_df = results_df.merge(earnings_metadata, on='symbol', how='left')

        # Calculate spot prices for each symbol (use equity bars close price on appropriate date)
        from datetime import timedelta
        spot_prices = {}
        for symbol in results_df['symbol'].unique():
            symbol_earnings = earnings_df[earnings_df['symbol'] == symbol]
            if symbol_earnings.empty:
                continue

            earnings_time = symbol_earnings.iloc[0]['earnings_time']
            earnings_date = params.earnings_date

            # Determine spot price date based on earnings time
            if earnings_time == 'PRE_MARKET':
                # Use previous trading day's close
                spot_date = earnings_date - timedelta(days=1)
            else:
                # AFTER_HOURS or UNKNOWN: use same day's close
                spot_date = earnings_date

            # Get spot price from equity bars
            try:
                spot_data = equity_reader.get_bars(
                    symbol=symbol,
                    bar_size='1 day',
                    start_date=spot_date - timedelta(days=5),  # Buffer for weekends
                    end_date=spot_date + timedelta(days=1),
                )
                if not spot_data.empty:
                    # Get the last close price on or before spot_date
                    spot_data = spot_data[spot_data['time'].dt.date <= spot_date]
                    if not spot_data.empty:
                        spot_prices[symbol] = float(spot_data['close'].iloc[-1])
            except Exception as e:
                logger.warning(f"Could not get spot price for {symbol}: {e}")

        # Add spot_price column
        results_df['spot_price'] = results_df['symbol'].map(spot_prices)

        # Drop rows with missing spot price
        missing_spot = results_df['spot_price'].isna().sum()
        if missing_spot > 0:
            logger.warning(f"dropping_rows_with_missing_spot_price", count=missing_spot)
            results_df = results_df.dropna(subset=['spot_price'])

        # Step 4: Assign quartiles
        results_df = assign_iv_quartiles(results_df)

        # Step 5: Rank by IV ratio descending
        results_df = results_df.sort_values('iv_ratio_entry', ascending=False).reset_index(drop=True)
        results_df['rank'] = range(1, len(results_df) + 1)

        # Step 6: Limit to top N if specified
        if params.top_n:
            results_df = results_df.head(params.top_n)
            logger.info("limited_to_top_n", top_n=params.top_n)

        # Step 7: Convert to IVRankCandidate objects
        candidates = []
        for _, row in results_df.iterrows():
            candidate = IVRankCandidate(
                symbol=row['symbol'],
                earnings_date=params.earnings_date,
                earnings_time=row.get('earnings_time', 'UNKNOWN'),
                spot_price=float(row['spot_price']),
                strike=float(row['strike']),
                iv_short_entry=float(row['iv_short_entry']),
                iv_long_entry=float(row['iv_long_entry']),
                iv_ratio_entry=float(row['iv_ratio_entry']),
                short_expiry=row['short_expiry'],
                long_expiry=row['long_expiry'],
                entry_cost_per_contract=float(row['entry_cost_per_contract']),
                rank=int(row['rank']),
                iv_ratio_quartile=str(row['iv_ratio_quartile']) if pd.notna(row['iv_ratio_quartile']) else 'N/A',
            )
            candidates.append(candidate)

        duration = time.time() - start_time
        logger.info(
            "iv_rank_complete",
            total_symbols=total_symbols,
            tradable_symbols=tradable_count,
            ranked_candidates=len(candidates),
            duration=duration,
        )

        # Save to CSV if output_file specified
        if params.output_file:
            results_df.to_csv(params.output_file, index=False)
            logger.info("saved_to_csv", file=str(params.output_file))

        return IVRankResult(
            success=True,
            earnings_date=params.earnings_date,
            total_symbols=total_symbols,
            tradable_symbols=tradable_count,
            ranked_candidates=candidates,
            duration_seconds=duration,
        )

    except Exception as e:
        duration = time.time() - start_time
        logger.error("iv_rank_failed", error=str(e), exc_info=True)

        return IVRankResult(
            success=False,
            earnings_date=params.earnings_date,
            total_symbols=0,
            tradable_symbols=0,
            ranked_candidates=[],
            duration_seconds=duration,
            error=str(e),
        )


def execute_strategy_select(
    params: StrategySelectParams,
) -> StrategySelectResult:
    """
    Execute strategy selection for calendar spread candidates.

    Filters candidates by IV ratio thresholds and other criteria.
    Reuses IV ranking logic with additional filtering.

    Args:
        params: Validated strategy selection parameters (Pydantic model)

    Returns:
        StrategySelectResult with filtered candidates and statistics

    Example:
        >>> params = StrategySelectParams(
        ...     earnings_date=date(2025, 11, 13),
        ...     min_iv_ratio=1.5,
        ...     min_quartile='Q4',
        ...     top_n=10,
        ... )
        >>> result = execute_strategy_select(params)
        >>> assert result.success
        >>> assert all(c.iv_ratio_entry >= 1.5 for c in result.selected_candidates)
    """
    start_time = time.time()

    try:
        logger.info(
            "strategy_select_start",
            earnings_date=str(params.earnings_date),
            min_iv_ratio=params.min_iv_ratio,
            max_entry_cost=params.max_entry_cost,
            min_quartile=params.min_quartile,
            profitable_only=params.profitable_only,
        )

        # Step 1: Get all ranked candidates using IV rank logic
        iv_rank_params = IVRankParams(
            earnings_date=params.earnings_date,
            symbols=params.symbols,
            earnings_time=params.earnings_time,
            option_type=params.option_type,
            bar_size=params.bar_size,
            entry_hour=params.entry_hour,
            entry_minute=params.entry_minute,
            top_n=None,  # Get all candidates before filtering
            output_file=None,
            database_path=params.database_path,
            earnings_dataset=params.earnings_dataset,
            options_dataset=params.options_dataset,
            stocks_dataset=params.stocks_dataset,
            option_chains_dataset=params.option_chains_dataset,
        )

        iv_rank_result = execute_iv_rank(iv_rank_params)

        if not iv_rank_result.success:
            duration = time.time() - start_time
            return StrategySelectResult(
                success=False,
                earnings_date=params.earnings_date,
                total_evaluated=0,
                selected_count=0,
                selection_criteria={},
                selected_candidates=[],
                statistics={},
                duration_seconds=duration,
                error=iv_rank_result.error,
            )

        total_evaluated = len(iv_rank_result.ranked_candidates)
        logger.info("evaluated_candidates", count=total_evaluated)

        # Convert candidates back to DataFrame for filtering
        if not iv_rank_result.ranked_candidates:
            duration = time.time() - start_time
            return StrategySelectResult(
                success=True,
                earnings_date=params.earnings_date,
                total_evaluated=0,
                selected_count=0,
                selection_criteria={},
                selected_candidates=[],
                statistics={},
                duration_seconds=duration,
            )

        candidates_df = pd.DataFrame([c.model_dump() for c in iv_rank_result.ranked_candidates])

        # Step 2: Apply selection filters
        filtered_df = rank_and_filter_candidates(
            results_df=candidates_df,
            min_iv_ratio=params.min_iv_ratio,
            max_entry_cost=params.max_entry_cost,
            min_quartile=params.min_quartile,
            profitable_only=params.profitable_only,
            top_n=params.top_n,
        )

        selected_count = len(filtered_df)
        logger.info("selected_candidates", count=selected_count)

        # Step 3: Calculate statistics
        statistics = calculate_selection_statistics(filtered_df)

        # Step 4: Convert back to IVRankCandidate objects
        selected_candidates = []
        for _, row in filtered_df.iterrows():
            candidate = IVRankCandidate(
                symbol=row['symbol'],
                earnings_date=row['earnings_date'],
                earnings_time=row['earnings_time'],
                spot_price=float(row['spot_price']),
                strike=float(row['strike']),
                iv_short_entry=float(row['iv_short_entry']),
                iv_long_entry=float(row['iv_long_entry']),
                iv_ratio_entry=float(row['iv_ratio_entry']),
                short_expiry=row['short_expiry'],
                long_expiry=row['long_expiry'],
                entry_cost_per_contract=float(row['entry_cost_per_contract']),
                rank=int(row['rank']),
                iv_ratio_quartile=str(row['iv_ratio_quartile']) if pd.notna(row['iv_ratio_quartile']) else 'N/A',
            )
            selected_candidates.append(candidate)

        # Step 5: Build selection criteria summary
        selection_criteria = {}
        if params.min_iv_ratio:
            selection_criteria['min_iv_ratio'] = params.min_iv_ratio
        if params.max_entry_cost:
            selection_criteria['max_entry_cost'] = params.max_entry_cost
        if params.min_quartile:
            selection_criteria['min_quartile'] = params.min_quartile
        if params.profitable_only:
            selection_criteria['profitable_only'] = True
        if params.top_n:
            selection_criteria['top_n'] = params.top_n

        duration = time.time() - start_time
        logger.info(
            "strategy_select_complete",
            total_evaluated=total_evaluated,
            selected_count=selected_count,
            duration=duration,
        )

        # Save to CSV if output_file specified
        if params.output_file:
            filtered_df.to_csv(params.output_file, index=False)
            logger.info("saved_to_csv", file=str(params.output_file))

        return StrategySelectResult(
            success=True,
            earnings_date=params.earnings_date,
            total_evaluated=total_evaluated,
            selected_count=selected_count,
            selection_criteria=selection_criteria,
            selected_candidates=selected_candidates,
            statistics=statistics,
            duration_seconds=duration,
        )

    except Exception as e:
        duration = time.time() - start_time
        logger.error("strategy_select_failed", error=str(e), exc_info=True)

        return StrategySelectResult(
            success=False,
            earnings_date=params.earnings_date,
            total_evaluated=0,
            selected_count=0,
            selection_criteria={},
            selected_candidates=[],
            statistics={},
            duration_seconds=duration,
            error=str(e),
        )
