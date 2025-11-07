"""Backfill business logic - testable, framework-independent.

Extracts backfill logic from CLI for easy testing without Typer.
Uses Pydantic models for type safety and dependency injection for I/O.
"""

import time
from typing import Optional, Callable, Any
from pathlib import Path

import dlt

from dlt_ibapi.cli.models import (
    BackfillEquityParams,
    BackfillEquityResult,
    BackfillOptionsParams,
    BackfillOptionsResult,
)
from dlt_ibapi.config import IBConnectionConfig, IBHistoricalConfig
from dlt_ibapi.config_loader import get_connection_config, get_historical_config
from dlt_ibapi.backfill import (
    equity_bars_backfill_source,
    backfill_option_bars,
    OptionBackfillConfig,
    ContractSelectionMode,
)
from dlt_ibapi.utils.logging import get_logger

logger = get_logger(__name__)


def execute_backfill_equity(
    params: BackfillEquityParams,
    connection_config: Optional[IBConnectionConfig] = None,
    hist_config: Optional[IBHistoricalConfig] = None,
    pipeline_factory: Optional[Callable[[BackfillEquityParams], Any]] = None,
) -> BackfillEquityResult:
    """Execute equity backfill operation.

    Pure business logic with no CLI dependencies. All I/O is injectable.

    Args:
        params: Validated backfill parameters (Pydantic model)
        connection_config: IB connection config (optional, auto-loads if None)
        hist_config: Historical data config (optional, auto-loads if None)
        pipeline_factory: Optional factory for creating pipelines (for testing)

    Returns:
        BackfillEquityResult with structured response

    Example:
        >>> params = BackfillEquityParams(
        ...     symbols=["AAPL", "MSFT"],
        ...     start_date=date(2025, 1, 1),
        ...     end_date=date(2025, 1, 31),
        ...     bar_size="1 day",
        ...     pipeline_name="ib_stocks",
        ... )
        >>> result = execute_backfill_equity(params)
        >>> assert result.success
        >>> assert len(result.symbols_processed) == 2
    """
    start_time = time.time()
    warnings = []
    symbols_processed = []
    total_bars = 0
    gaps_filled = 0

    try:
        logger.info(
            "starting_equity_backfill",
            symbols=params.symbols,
            start_date=str(params.start_date),
            end_date=str(params.end_date),
            bar_size=params.bar_size,
        )

        # Create configs if not provided
        if connection_config is None:
            connection_config = get_connection_config()
            logger.debug("loaded_connection_config")

        if hist_config is None:
            hist_config = get_historical_config()
            logger.debug("loaded_historical_config")

        # Check for future dates
        from datetime import date as date_type
        if params.end_date > date_type.today():
            warnings.append(
                f"End date {params.end_date} is in the future. Data may not be available."
            )
            logger.warning("future_end_date", end_date=str(params.end_date))

        # Create pipeline (or use injected mock for testing)
        if pipeline_factory:
            logger.debug("using_injected_pipeline_factory")
            pipeline = pipeline_factory(params)
        else:
            # Production path: create real DLT pipeline
            logger.info("creating_dlt_pipeline", name=params.pipeline_name)
            pipeline = dlt.pipeline(
                pipeline_name=params.pipeline_name,
                destination=dlt.destinations.filesystem(bucket_url=str(params.database_path)),
                dataset_name=params.dataset_name,
            )

        # Process each symbol
        for symbol in params.symbols:
            logger.info("processing_symbol", symbol=symbol)

            try:
                # Create backfill source
                source = equity_bars_backfill_source(
                    symbols=[symbol],
                    database_path=str(params.database_path),
                    dataset_name=params.dataset_name,
                    start_date=params.start_date,
                    end_date=params.end_date,
                    bar_size=params.bar_size,
                    connection_config=connection_config,
                    hist_config=hist_config,
                )

                # Run pipeline
                logger.debug("running_pipeline", symbol=symbol)
                info = pipeline.run(source, write_disposition="append", loader_file_format="parquet")

                if info.has_failed_jobs:
                    warnings.append(f"Failed to backfill {symbol}")
                    logger.warning("symbol_failed", symbol=symbol)
                else:
                    symbols_processed.append(symbol)
                    logger.info("symbol_completed", symbol=symbol)

            except Exception as e:
                warnings.append(f"Error backfilling {symbol}: {str(e)}")
                logger.error("symbol_error", symbol=symbol, error=str(e))

        # Calculate metrics
        duration = time.time() - start_time

        logger.info(
            "equity_backfill_complete",
            symbols_processed=len(symbols_processed),
            duration=duration,
        )

        return BackfillEquityResult(
            success=len(symbols_processed) > 0,
            symbols_processed=symbols_processed,
            total_bars=total_bars,
            gaps_filled=gaps_filled,
            pipeline_name=params.pipeline_name,
            output_path=params.database_path / params.dataset_name,
            duration_seconds=duration,
            warnings=warnings,
        )

    except Exception as e:
        duration = time.time() - start_time
        logger.error("equity_backfill_failed", error=str(e), duration=duration)

        return BackfillEquityResult(
            success=False,
            symbols_processed=symbols_processed,
            total_bars=0,
            gaps_filled=0,
            pipeline_name=params.pipeline_name,
            output_path=params.database_path,
            duration_seconds=duration,
            error=str(e),
            warnings=warnings,
        )


def execute_backfill_options(
    params: BackfillOptionsParams,
    connection_config: Optional[IBConnectionConfig] = None,
    pipeline_factory: Optional[Callable[[BackfillOptionsParams], Any]] = None,
) -> BackfillOptionsResult:
    """Execute options backfill operation.

    Pure business logic with no CLI dependencies. All I/O is injectable.

    Args:
        params: Validated backfill parameters (Pydantic model)
        connection_config: IB connection config (optional, auto-loads if None)
        pipeline_factory: Optional factory for creating pipelines (for testing)

    Returns:
        BackfillOptionsResult with structured response

    Example:
        >>> params = BackfillOptionsParams(
        ...     underlying="AAPL",
        ...     spot_price=150.0,
        ...     start_date=date(2025, 1, 1),
        ...     end_date=date(2025, 1, 31),
        ...     bar_size="1 day",
        ...     selection_mode="atm",
        ...     pipeline_name="ib_options",
        ... )
        >>> result = execute_backfill_options(params)
        >>> assert result.success
    """
    start_time = time.time()
    warnings = []

    try:
        logger.info(
            "starting_options_backfill",
            underlying=params.underlying,
            spot_price=params.spot_price,
            start_date=str(params.start_date),
            end_date=str(params.end_date),
            selection_mode=params.selection_mode,
        )

        # Create config if not provided
        if connection_config is None:
            connection_config = get_connection_config()
            logger.debug("loaded_connection_config")

        # Check for future dates
        from datetime import date as date_type
        if params.end_date > date_type.today():
            warnings.append(
                f"End date {params.end_date} is in the future. Data may not be available."
            )
            logger.warning("future_end_date", end_date=str(params.end_date))

        # Map selection mode to enum
        mode_map = {
            "atm": ContractSelectionMode.K_AROUND_ATM,
            "moneyness": ContractSelectionMode.MONEYNESS,
            "delta": ContractSelectionMode.DELTA,
            "all": ContractSelectionMode.ALL,
        }
        selection_mode_enum = mode_map[params.selection_mode]

        # Create backfill config
        backfill_config = OptionBackfillConfig(
            start_date=params.start_date,
            end_date=params.end_date,
            bar_size=params.bar_size,
            selection_mode=selection_mode_enum,
            k_strikes=params.k_strikes,
            min_dte=params.min_dte,
            max_dte=params.max_dte,
        )

        # Create pipeline (or use injected mock for testing)
        if pipeline_factory:
            logger.debug("using_injected_pipeline_factory")
            pipeline = pipeline_factory(params)
        else:
            # Production path: create real DLT pipeline
            logger.info("creating_dlt_pipeline", name=params.pipeline_name)
            pipeline = dlt.pipeline(
                pipeline_name=params.pipeline_name,
                destination=dlt.destinations.filesystem(bucket_url=str(params.database_path)),
                dataset_name=params.dataset_name,
            )

        # Create backfill resource
        logger.debug("creating_backfill_resource")
        data = backfill_option_bars(
            underlying=params.underlying,
            spot_price=params.spot_price,
            database_path=str(params.database_path),
            dataset_name=params.dataset_name,
            connection_config=connection_config,
            backfill_config=backfill_config,
        )

        # Run pipeline
        logger.info("running_pipeline")
        info = pipeline.run(data, write_disposition="append", loader_file_format="parquet")

        if info.has_failed_jobs:
            warnings.append("Some pipeline jobs failed")
            logger.warning("pipeline_jobs_failed")

        # Calculate metrics
        duration = time.time() - start_time

        logger.info(
            "options_backfill_complete",
            underlying=params.underlying,
            duration=duration,
        )

        return BackfillOptionsResult(
            success=not info.has_failed_jobs,
            contracts_processed=0,  # TODO: Extract from load_info
            total_bars=0,  # TODO: Extract from load_info
            gaps_filled=0,  # TODO: Extract from load_info
            pipeline_name=params.pipeline_name,
            output_path=params.database_path / params.dataset_name,
            duration_seconds=duration,
            warnings=warnings,
        )

    except Exception as e:
        duration = time.time() - start_time
        logger.error("options_backfill_failed", error=str(e), duration=duration)

        return BackfillOptionsResult(
            success=False,
            contracts_processed=0,
            total_bars=0,
            gaps_filled=0,
            pipeline_name=params.pipeline_name,
            output_path=params.database_path,
            duration_seconds=duration,
            error=str(e),
            warnings=warnings,
        )
