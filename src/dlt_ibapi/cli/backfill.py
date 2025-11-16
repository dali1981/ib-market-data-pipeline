"""Backfill business logic - testable, framework-independent.

Extracts backfill logic from CLI for easy testing without Typer.
Uses Pydantic models for type safety and dependency injection for I/O.
"""

import time
from typing import Optional, Callable, Any
from pathlib import Path

import dlt
from delta_lake_storage import get_config as get_storage_config, StorageBackend
from delta_lake_storage.dlt import create_pipeline, run_pipeline

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


def _create_pipeline_with_storage(params, pipeline_factory: Optional[Callable] = None):
    """
    Create DLT pipeline using delta-lake-storage configuration.

    Handles both test (injected factory) and production paths.
    Automatically configures Delta Lake if params.use_delta is True.

    Args:
        params: CLI parameters with pipeline_name, dataset_name, use_delta
        pipeline_factory: Optional test factory

    Returns:
        Configured DLT pipeline
    """
    if pipeline_factory:
        logger.debug("using_injected_pipeline_factory")
        return pipeline_factory(params)

    # Production path: use delta-lake-storage
    storage_config = get_storage_config()

    # Override config with params
    storage_config.storage.base_path = str(params.database_path)
    if params.use_delta:
        storage_config.storage.use_delta = True
        storage_config.storage.backend = StorageBackend.DELTA_LAKE
        logger.info("delta_lake_enabled", backend="delta_lake")

    logger.info(
        "creating_dlt_pipeline",
        name=params.pipeline_name,
        backend=storage_config.storage.backend.value,
        use_delta=storage_config.storage.use_delta,
    )

    return create_pipeline(
        params.pipeline_name,
        params.dataset_name,
        storage_config
    )


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
        # Resolve symbols from earnings if needed
        symbols_to_backfill = params.symbols
        if params.earnings_date:
            logger.info("loading_symbols_from_earnings", earnings_date=str(params.earnings_date))
            from dlt_ibapi.repositories import EarningsCalendarReader

            earnings_reader = EarningsCalendarReader(
                database_path=str(params.database_path),
                dataset_name=params.earnings_dataset_name,
            )

            earnings_df = earnings_reader.get_earnings_on_date(params.earnings_date)

            if earnings_df.empty:
                logger.warning("no_earnings_found", earnings_date=str(params.earnings_date))
                warnings.append(f"No earnings found on {params.earnings_date}")
                symbols_to_backfill = []
            else:
                symbols_to_backfill = sorted(earnings_df["symbol"].unique().tolist())
                logger.info("loaded_earnings_symbols", count=len(symbols_to_backfill))

        logger.info(
            "starting_equity_backfill",
            symbols=symbols_to_backfill,
            start_date=str(params.start_date),
            end_date=str(params.end_date),
            bar_size=params.bar_size,
        )

        # Create configs if not provided
        if connection_config is None:
            connection_config = get_connection_config()
            logger.debug("loaded_connection_config")

        # Override client_id if provided in params
        if params.client_id is not None:
            connection_config = connection_config.model_copy(
                update={"client_id": params.client_id}
            )
            logger.info("using_custom_client_id", client_id=params.client_id)

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

        # Create pipeline with delta-lake-storage
        pipeline = _create_pipeline_with_storage(params, pipeline_factory)
        storage_config = get_storage_config()

        # Process each symbol
        for symbol in symbols_to_backfill:
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
                    what_to_show=hist_config.what_to_show,
                    use_rth=hist_config.use_rth,
                )

                # Run pipeline
                logger.debug("running_pipeline", symbol=symbol)
                info = run_pipeline(pipeline, source, storage_config, write_disposition="append")

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

    Supports two modes:
    1. Single symbol mode: underlying + spot_price provided
    2. Earnings batch mode: earnings_date provided (auto-loads symbols, spot prices, expirations)

    Pure business logic with no CLI dependencies. All I/O is injectable.

    Args:
        params: Validated backfill parameters (Pydantic model)
        connection_config: IB connection config (optional, auto-loads if None)
        pipeline_factory: Optional factory for creating pipelines (for testing)

    Returns:
        BackfillOptionsResult with structured response

    Example (single symbol):
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

    Example (earnings batch):
        >>> params = BackfillOptionsParams(
        ...     earnings_date=date(2025, 11, 13),
        ...     start_date=date(2025, 1, 1),
        ...     end_date=date(2025, 11, 13),
        ...     pipeline_name="ib_options",
        ... )
        >>> result = execute_backfill_options(params)
        >>> assert result.success
    """
    # Branch based on mode
    if params.earnings_date:
        return _execute_backfill_options_earnings(params, connection_config, pipeline_factory)
    else:
        return _execute_backfill_options_single(params, connection_config, pipeline_factory)


def _execute_backfill_options_single(
    params: BackfillOptionsParams,
    connection_config: Optional[IBConnectionConfig] = None,
    pipeline_factory: Optional[Callable[[BackfillOptionsParams], Any]] = None,
) -> BackfillOptionsResult:
    """Execute options backfill for single symbol (original logic)."""
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

        # Override client_id if provided in params
        if params.client_id is not None:
            connection_config = connection_config.model_copy(
                update={"client_id": params.client_id}
            )
            logger.info("using_custom_client_id", client_id=params.client_id)

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
            k_expirations=params.k_expirations,
        )

        # Create pipeline with delta-lake-storage
        pipeline = _create_pipeline_with_storage(params, pipeline_factory)
        storage_config = get_storage_config()

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
        info = run_pipeline(pipeline, data, storage_config, write_disposition="append")

        # Debug: Extract LoadInfo details
        logger.info(
            "pipeline_load_info",
            has_failed_jobs=info.has_failed_jobs,
            load_packages_count=len(info.load_packages) if info.load_packages else 0,
            metrics=dict(info.metrics) if hasattr(info, 'metrics') and info.metrics else None,
        )

        if info.load_packages:
            for idx, pkg in enumerate(info.load_packages):
                logger.info(
                    "load_package_details",
                    package_index=idx,
                    state=pkg.state if hasattr(pkg, 'state') else None,
                    jobs_count=len(pkg.jobs['completed_jobs']) if hasattr(pkg, 'jobs') and pkg.jobs else 0,
                    failed_jobs_count=len(pkg.jobs['failed_jobs']) if hasattr(pkg, 'jobs') and pkg.jobs else 0,
                )
                if hasattr(pkg, 'jobs') and pkg.jobs:
                    for job_idx, job in enumerate(pkg.jobs.get('failed_jobs', [])):
                        logger.error(
                            "failed_job",
                            job_index=job_idx,
                            file_name=job.file_name if hasattr(job, 'file_name') else None,
                            failed_message=job.failed_message if hasattr(job, 'failed_message') else None,
                        )

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
        logger.error(f"Options backfill failed: {e}", exc_info=True)

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

def _execute_backfill_options_earnings(
    params: BackfillOptionsParams,
    connection_config: Optional[IBConnectionConfig] = None,
    pipeline_factory: Optional[Callable[[BackfillOptionsParams], Any]] = None,
) -> BackfillOptionsResult:
    """Execute options backfill for earnings batch mode.

    This function:
    1. Loads symbols from earnings calendar
    2. Extracts spot prices from equity bars
    3. Discovers expirations from option chain snapshots
    4. Filters expirations beyond earnings date
    5. Backfills option bars for all valid (symbol, expiration) pairs
    """
    from datetime import timedelta
    from dlt_ibapi.repositories import EarningsCalendarReader, EquityBarsReader, OptionChainSnapshotReader

    start_time = time.time()
    warnings = []
    contracts_processed = 0
    total_bars = 0

    try:
        logger.info(
            "starting_options_backfill_earnings",
            earnings_date=str(params.earnings_date),
            start_date=str(params.start_date),
            end_date=str(params.end_date),
        )

        # Step 1: Load earnings symbols
        logger.info("loading_symbols_from_earnings")
        earnings_reader = EarningsCalendarReader(
            database_path=str(params.database_path),
            dataset_name=params.earnings_dataset_name,
        )

        earnings_df = earnings_reader.get_earnings_on_date(params.earnings_date)

        if earnings_df.empty:
            logger.warning("no_earnings_found", earnings_date=str(params.earnings_date))
            warnings.append(f"No earnings found on {params.earnings_date}")

            return BackfillOptionsResult(
                success=False,
                contracts_processed=0,
                total_bars=0,
                gaps_filled=0,
                pipeline_name=params.pipeline_name,
                output_path=params.database_path / params.dataset_name,
                duration_seconds=time.time() - start_time,
                error=f"No earnings found on {params.earnings_date}",
                warnings=warnings,
            )

        symbols = sorted(earnings_df["symbol"].unique().tolist())
        logger.info("loaded_earnings_symbols", count=len(symbols))

        # Step 2: Initialize readers
        equity_reader = EquityBarsReader(
            database_path=str(params.database_path),
            dataset_name=params.stocks_dataset_name,
        )

        snapshot_date_to_use = params.snapshot_date or params.earnings_date
        chain_reader = OptionChainSnapshotReader(
            database_path=str(params.database_path),
            dataset_name=params.option_chains_dataset_name,  # Now correctly defaults to 'option_chains'
        )

        # Step 3: Filter symbols to only those with snapshots
        logger.info("filtering_symbols_with_snapshots")
        symbols_with_snapshots = []
        for symbol in symbols:
            snapshots = chain_reader.get_available_snapshots(symbol)
            if snapshots:
                symbols_with_snapshots.append(symbol)

        if not symbols_with_snapshots:
            logger.warning(
                "no_symbols_with_snapshots",
                earnings_symbols=len(symbols),
                snapshot_date=str(snapshot_date_to_use),
            )
            return BackfillOptionsResult(
                success=False,
                contracts_processed=0,
                total_bars=0,
                gaps_filled=0,
                pipeline_name=params.pipeline_name,
                output_path=params.database_path / params.dataset_name,
                duration_seconds=time.time() - start_time,
                error=f"No symbols have snapshot data for {snapshot_date_to_use}",
                warnings=warnings,
            )

        logger.info(
            "filtered_to_symbols_with_snapshots",
            total_earnings=len(symbols),
            with_snapshots=len(symbols_with_snapshots),
            without_snapshots=len(symbols) - len(symbols_with_snapshots),
        )
        symbols = symbols_with_snapshots  # Replace list with filtered version

        # Step 4: Create config if not provided
        if connection_config is None:
            connection_config = get_connection_config()
            logger.debug("loaded_connection_config")

        # Override client_id if provided in params
        if params.client_id is not None:
            connection_config = connection_config.model_copy(
                update={"client_id": params.client_id}
            )
            logger.info("using_custom_client_id", client_id=params.client_id)

        # Map selection mode to enum
        mode_map = {
            "atm": ContractSelectionMode.K_AROUND_ATM,
            "moneyness": ContractSelectionMode.MONEYNESS,
            "delta": ContractSelectionMode.DELTA,
            "all": ContractSelectionMode.ALL,
        }
        selection_mode_enum = mode_map[params.selection_mode]

        # Step 5: Create pipeline with delta-lake-storage
        pipeline = _create_pipeline_with_storage(params, pipeline_factory)
        storage_config = get_storage_config()

        # Step 6: Process each symbol
        for symbol in symbols:
            logger.info("processing_symbol_earnings", symbol=symbol)

            try:
                # Get spot price from equity bars (always use "1 day" for spot price, not option bar_size)
                logger.debug("extracting_spot_price", symbol=symbol)
                equity_bars = equity_reader.get_bars(
                    symbol=symbol,
                    bar_size="1 day",  # Always use daily bars for spot price extraction
                    start_date=params.earnings_date - timedelta(days=7),
                    end_date=params.earnings_date,
                )

                if equity_bars.empty:
                    warnings.append(f"No equity data for {symbol} - skipping")
                    logger.warning("no_equity_data", symbol=symbol)
                    continue

                spot_price = float(equity_bars.iloc[-1]["close"])
                logger.debug("spot_price_extracted", symbol=symbol, spot_price=spot_price)

                # Get expirations from snapshot
                logger.debug("loading_expirations", symbol=symbol)
                expirations = chain_reader.get_available_expirations(
                    underlying=symbol,
                    as_of=snapshot_date_to_use,
                )

                if not expirations:
                    warnings.append(f"No snapshot data for {symbol} - skipping")
                    logger.warning("no_snapshot_data", symbol=symbol)
                    continue

                # Filter to k closest expirations if requested
                if params.k_expirations is not None and len(expirations) > params.k_expirations:
                    # Sort by expiration date (ascending = soonest first)
                    expirations_sorted = sorted(expirations)
                    expirations = expirations_sorted[:params.k_expirations]
                    logger.info(
                        "filtered_expirations",
                        symbol=symbol,
                        k_expirations=params.k_expirations,
                        selected=len(expirations),
                    )

                # Backfill all expirations for this symbol in one call
                logger.debug("backfilling_symbol", symbol=symbol, expirations=len(expirations))

                backfill_config = OptionBackfillConfig(
                    start_date=params.start_date,
                    end_date=params.end_date,
                    bar_size=params.bar_size,
                    selection_mode=selection_mode_enum,
                    k_strikes=params.k_strikes,
                    min_dte=0,      # Use all expirations from snapshot
                    max_dte=365,
                )

                # Create backfill resource
                data = backfill_option_bars(
                    underlying=symbol,
                    spot_price=spot_price,
                    database_path=str(params.database_path),
                    dataset_name=params.dataset_name,
                    connection_config=connection_config,
                    backfill_config=backfill_config,
                )

                # Run pipeline
                info = run_pipeline(pipeline, data, storage_config, write_disposition="append")

                if info.has_failed_jobs:
                    warnings.append(f"Failed to backfill {symbol}")
                    logger.warning("symbol_backfill_failed", symbol=symbol)
                else:
                    contracts_processed += 1
                    logger.info("symbol_backfill_complete", symbol=symbol)

            except Exception as e:
                warnings.append(f"Error processing {symbol}: {str(e)}")
                logger.error(f"Error processing {symbol}: {e}", exc_info=True)

        # Calculate metrics
        duration = time.time() - start_time

        logger.info(
            "options_backfill_earnings_complete",
            symbols_processed=len(symbols),
            contracts_processed=contracts_processed,
            duration=duration,
        )

        return BackfillOptionsResult(
            success=contracts_processed > 0,
            contracts_processed=contracts_processed,
            total_bars=total_bars,
            gaps_filled=0,
            pipeline_name=params.pipeline_name,
            output_path=params.database_path / params.dataset_name,
            duration_seconds=duration,
            warnings=warnings,
        )

    except Exception as e:
        duration = time.time() - start_time
        logger.error(f"Options backfill earnings failed: {e}", exc_info=True)

        return BackfillOptionsResult(
            success=False,
            contracts_processed=contracts_processed,
            total_bars=0,
            gaps_filled=0,
            pipeline_name=params.pipeline_name,
            output_path=params.database_path,
            duration_seconds=duration,
            error=str(e),
            warnings=warnings,
        )
