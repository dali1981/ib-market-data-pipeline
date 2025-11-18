"""Liquidity analysis business logic - testable, framework-independent.

Executes liquidity analysis for option contracts around earnings dates.
Uses Pydantic models for type safety and dependency injection for I/O.
"""

import time
from typing import List
import pandas as pd

from dlt_ibapi.cli.models import (
    LiquidityAnalysisParams,
    LiquidityAnalysisResult,
    LiquidityMetricData,
)
from dlt_ibapi.repositories import (
    EarningsCalendarReader,
    OptionBarsReader,
    OptionChainSnapshotReader,
)
from dlt_ibapi.strategies.liquidity import (
    calculate_batch_liquidity,
    filter_by_liquidity,
)
from dlt_ibapi.utils.logging import get_logger

logger = get_logger(__name__)


def execute_liquidity_analysis(
    params: LiquidityAnalysisParams,
) -> LiquidityAnalysisResult:
    """
    Execute liquidity analysis for option contracts.

    Calculates liquidity metrics for all contracts with earnings on specified date.
    Filters by liquidity criteria and returns ranked results.

    Args:
        params: Validated liquidity analysis parameters (Pydantic model)

    Returns:
        LiquidityAnalysisResult with liquidity metrics and statistics

    Example:
        >>> from datetime import date
        >>> params = LiquidityAnalysisParams(
        ...     earnings_date=date(2025, 11, 13),
        ...     min_score=70,
        ...     top_n=10,
        ... )
        >>> result = execute_liquidity_analysis(params)
        >>> assert result.success
        >>> assert len(result.metrics) <= 10
    """
    start_time = time.time()

    try:
        logger.info(
            "liquidity_analysis_start",
            earnings_date=str(params.earnings_date),
            symbols=params.symbols,
            min_score=params.min_score,
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
            return LiquidityAnalysisResult(
                success=False,
                earnings_date=params.earnings_date,
                total_contracts_evaluated=0,
                liquid_contracts_count=0,
                metrics=[],
                statistics={},
                duration_seconds=duration,
                error=f"No earnings found on {params.earnings_date}",
            )

        # Filter by symbols if provided
        if params.symbols:
            symbols_upper = [s.upper() for s in params.symbols]
            earnings_df = earnings_df[earnings_df['symbol'].isin(symbols_upper)]
            logger.info("filtered_by_symbols", count=len(earnings_df))

        if earnings_df.empty:
            logger.warning("no_earnings_after_filters")
            duration = time.time() - start_time
            return LiquidityAnalysisResult(
                success=False,
                earnings_date=params.earnings_date,
                total_contracts_evaluated=0,
                liquid_contracts_count=0,
                metrics=[],
                statistics={},
                duration_seconds=duration,
                error="No earnings found matching filters",
            )

        symbols = earnings_df['symbol'].unique().tolist()
        logger.info("earnings_symbols_loaded", count=len(symbols))

        # Step 2: Load option chain snapshots to get contracts
        chain_reader = OptionChainSnapshotReader(
            database_path=str(params.database_path),
            dataset_name=params.option_chains_dataset,
        )

        # Get symbols that have snapshots on earnings date
        symbols_with_snapshots = chain_reader.get_symbols_with_snapshots(
            snapshot_date=params.earnings_date,
            symbols=symbols,
        )

        if symbols_with_snapshots.empty:
            logger.warning("no_option_chain_snapshots")
            duration = time.time() - start_time
            return LiquidityAnalysisResult(
                success=False,
                earnings_date=params.earnings_date,
                total_contracts_evaluated=0,
                liquid_contracts_count=0,
                metrics=[],
                statistics={},
                duration_seconds=duration,
                error="No option chain snapshots found for earnings symbols",
            )

        # Get all unique expiry/strike combinations from snapshots
        all_contracts = []
        for _, row in symbols_with_snapshots.iterrows():
            symbol = row['symbol']
            try:
                # Get available expirations
                expirations = chain_reader.get_available_expirations(
                    underlying=symbol,
                    as_of=params.earnings_date,
                )

                # Get strikes
                strikes = chain_reader.get_strikes_for_expiry(
                    underlying=symbol,
                    as_of=params.earnings_date,
                    expiry=expirations[0] if expirations else params.earnings_date,
                )

                # Create contract rows for all expiry/strike/right combinations
                for expiry in expirations:
                    for strike in strikes:
                        for right in ['C', 'P']:
                            all_contracts.append({
                                'underlying': symbol,
                                'expiry': expiry,
                                'strike': strike,
                                'right': right,
                            })

            except Exception as e:
                logger.warning(
                    f"failed_to_load_snapshot",
                    symbol=symbol,
                    error=str(e),
                )
                continue

        if not all_contracts:
            logger.warning("no_option_chain_snapshots")
            duration = time.time() - start_time
            return LiquidityAnalysisResult(
                success=False,
                earnings_date=params.earnings_date,
                total_contracts_evaluated=0,
                liquid_contracts_count=0,
                metrics=[],
                statistics={},
                duration_seconds=duration,
                error="No option chain snapshots found for earnings symbols",
            )

        contracts_df = pd.DataFrame(all_contracts)
        logger.info("contracts_loaded", count=len(contracts_df))

        # Step 3: Calculate liquidity metrics for all contracts
        option_reader = OptionBarsReader(
            database_path=str(params.database_path),
            dataset_name=params.options_dataset,
        )

        liquidity_df = calculate_batch_liquidity(
            option_bars_reader=option_reader,
            contracts=contracts_df,
            bar_size=params.bar_size,
            lookback_days=params.lookback_days,
            min_days=params.min_days,
        )

        if liquidity_df.empty:
            logger.warning("no_liquidity_metrics")
            duration = time.time() - start_time
            return LiquidityAnalysisResult(
                success=False,
                earnings_date=params.earnings_date,
                total_contracts_evaluated=len(contracts_df),
                liquid_contracts_count=0,
                metrics=[],
                statistics={},
                duration_seconds=duration,
                error="Failed to calculate liquidity metrics (insufficient bar data)",
            )

        total_evaluated = len(liquidity_df)
        logger.info("liquidity_metrics_calculated", count=total_evaluated)

        # Step 4: Apply filters
        filtered_df = filter_by_liquidity(
            liquidity_df,
            min_score=params.min_score,
            min_quartile=params.min_quartile,
            min_volume=params.min_volume,
            min_open_interest=params.min_open_interest,
            max_spread_pct=params.max_spread_pct,
        )

        # Step 5: Sort by liquidity score descending
        filtered_df = filtered_df.sort_values('liquidity_score', ascending=False)

        # Step 6: Limit to top N if specified
        if params.top_n:
            filtered_df = filtered_df.head(params.top_n)
            logger.info("limited_to_top_n", top_n=params.top_n)

        liquid_count = len(filtered_df)
        logger.info("liquid_contracts_filtered", count=liquid_count)

        # Step 7: Calculate statistics
        statistics = {}
        if not filtered_df.empty:
            statistics = {
                'mean_score': float(filtered_df['liquidity_score'].mean()),
                'median_score': float(filtered_df['liquidity_score'].median()),
                'mean_volume': float(filtered_df['avg_volume'].mean()),
                'mean_open_interest': float(filtered_df['avg_open_interest'].mean()),
                'mean_spread_pct': float(filtered_df['avg_spread_pct'].mean()),
                'min_score': float(filtered_df['liquidity_score'].min()),
                'max_score': float(filtered_df['liquidity_score'].max()),
            }

        # Step 8: Convert to LiquidityMetricData objects
        metrics: List[LiquidityMetricData] = []
        for _, row in filtered_df.iterrows():
            metric = LiquidityMetricData(
                symbol=row['symbol'],
                expiry=row['expiry'],
                strike=float(row['strike']),
                right=row['right'],
                avg_volume=float(row['avg_volume']),
                avg_open_interest=float(row['avg_open_interest']),
                avg_spread=float(row['avg_spread']),
                avg_spread_pct=float(row['avg_spread_pct']),
                volume_oi_ratio=float(row['volume_oi_ratio']),
                liquidity_score=float(row['liquidity_score']),
                liquidity_quartile=str(row['liquidity_quartile']),
                days_observed=int(row['days_observed']),
            )
            metrics.append(metric)

        duration = time.time() - start_time
        logger.info(
            "liquidity_analysis_complete",
            total_evaluated=total_evaluated,
            liquid_count=liquid_count,
            duration=duration,
        )

        # Save to CSV if output_file specified
        if params.output_file:
            filtered_df.to_csv(params.output_file, index=False)
            logger.info("saved_to_csv", file=str(params.output_file))

        return LiquidityAnalysisResult(
            success=True,
            earnings_date=params.earnings_date,
            total_contracts_evaluated=total_evaluated,
            liquid_contracts_count=liquid_count,
            metrics=metrics,
            statistics=statistics,
            duration_seconds=duration,
        )

    except Exception as e:
        duration = time.time() - start_time
        logger.error("liquidity_analysis_failed", error=str(e), exc_info=True)

        return LiquidityAnalysisResult(
            success=False,
            earnings_date=params.earnings_date,
            total_contracts_evaluated=0,
            liquid_contracts_count=0,
            metrics=[],
            statistics={},
            duration_seconds=duration,
            error=str(e),
        )