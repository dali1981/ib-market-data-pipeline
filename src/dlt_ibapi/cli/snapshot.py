"""Snapshot business logic - testable, framework-independent.

Extracts snapshot logic from CLI for easy testing without Typer.
Uses Pydantic models for type safety and dependency injection for I/O.
"""

import time
from typing import Optional, Callable, Any
from pathlib import Path

import dlt
from delta_lake_storage import get_config as get_storage_config, StorageBackend
from delta_lake_storage.dlt import create_pipeline, run_pipeline

from dlt_ibapi.cli.models import (
    SnapshotParams,
    SnapshotResult,
    BatchSnapshotResult,
    ListSnapshotsParams,
    ListSnapshotsResult,
    SnapshotInfo,
)
from dlt_ibapi.config import IBConnectionConfig
from dlt_ibapi.config_loader import get_connection_config
from dlt_ibapi.backfill import snapshot_option_chain
from dlt_ibapi.repositories import OptionChainSnapshotReader, EarningsCalendarReader
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


def execute_snapshot(
    params: SnapshotParams,
    connection_config: Optional[IBConnectionConfig] = None,
    pipeline_factory: Optional[Callable[[SnapshotParams], Any]] = None,
) -> SnapshotResult:
    """Execute option chain snapshot operation.

    Pure business logic with no CLI dependencies. All I/O is injectable.

    Args:
        params: Validated snapshot parameters (Pydantic model)
        connection_config: IB connection config (optional, auto-loads if None)
        pipeline_factory: Optional factory for creating pipelines (for testing)

    Returns:
        SnapshotResult with structured response

    Example:
        >>> params = SnapshotParams(
        ...     underlying="AAPL",
        ...     snapshot_date=date(2025, 1, 15),
        ...     min_dte=7,
        ...     max_dte=60,
        ...     pipeline_name="ib_options",
        ... )
        >>> result = execute_snapshot(params)
        >>> assert result.success
        >>> assert result.expirations_count > 0
    """
    start_time = time.time()
    warnings = []

    try:
        logger.info(
            f"Starting snapshot: underlying={params.underlying}, "
            f"snapshot_date={params.snapshot_date}, min_dte={params.min_dte}, max_dte={params.max_dte}"
        )

        # Create config if not provided
        if connection_config is None:
            connection_config = get_connection_config()
            logger.debug("Loaded connection config")

        # Check for future dates
        from datetime import date as date_type
        if params.snapshot_date > date_type.today():
            warnings.append(
                f"Snapshot date {params.snapshot_date} is in the future. Data may not be available."
            )
            logger.warning(f"Future snapshot date: {params.snapshot_date}")

        # Create pipeline (or use injected mock for testing)
        # Create pipeline with delta-lake-storage
        pipeline = _create_pipeline_with_storage(params, pipeline_factory)
        storage_config = get_storage_config()

        # Create snapshot resource
        logger.debug("Creating snapshot resource")
        data = snapshot_option_chain(
            underlying=params.underlying,
            snapshot_date=params.snapshot_date,
            cache_path=str(params.cache_path),
            connection_config=connection_config,
            min_dte=params.min_dte,
            max_dte=params.max_dte,
        )

        # Run pipeline
        # Use 'append' for Parquet, DLT's merge doesn't work well with filesystem
        # For Delta Lake, merge will work properly
        write_disp = "merge" if params.use_delta else "append"
        logger.info(f"Running pipeline with write_disposition={write_disp}")
        info = run_pipeline(pipeline, data, storage_config, write_disposition=write_disp)

        if info.has_failed_jobs:
            warnings.append("Pipeline jobs failed")
            logger.warning("Pipeline jobs failed")

        # Calculate metrics
        duration = time.time() - start_time

        # Extract counts by reading back the snapshot we just wrote
        expirations_count = 0
        strikes_count = 0

        if not info.has_failed_jobs:
            try:
                # Read back snapshot to get accurate counts
                from dlt_ibapi.repositories import OptionChainSnapshotReader

                # Get storage path from config
                storage_cfg = get_storage_config()
                database_path = storage_cfg.get("storage", {}).get("base_path", "data")

                reader = OptionChainSnapshotReader(
                    database_path=database_path,
                    dataset_name=params.dataset_name,
                )

                # Get snapshot for this underlying
                snapshot_df = reader.get_chain_for_date(
                    underlying=params.underlying,
                    as_of=params.snapshot_date,
                    min_dte=params.min_dte,
                    max_dte=params.max_dte,
                )

                if not snapshot_df.empty:
                    # DLT normalizes arrays into child tables, so use the count columns
                    # that were written to the main table during snapshot
                    first_row = snapshot_df.iloc[0]
                    if "expiration_count" in first_row:
                        expirations_count = int(first_row["expiration_count"])
                    if "strike_count" in first_row:
                        strikes_count = int(first_row["strike_count"])

            except Exception as e:
                logger.warning(f"Could not extract counts from snapshot: {e}")
                # Fallback to row count
                expirations_count = 0
                strikes_count = 0

        logger.info(
            f"Snapshot complete: underlying={params.underlying}, "
            f"expirations={expirations_count}, strikes={strikes_count}, duration={duration:.1f}s"
        )

        return SnapshotResult(
            success=not info.has_failed_jobs,
            underlying=params.underlying,
            snapshot_date=params.snapshot_date,
            expirations_count=expirations_count,
            strikes_count=strikes_count,
            pipeline_name=params.pipeline_name,
            duration_seconds=duration,
            warnings=warnings,
        )

    except Exception as e:
        duration = time.time() - start_time
        logger.error(f"Snapshot failed: {e}", exc_info=True)

        return SnapshotResult(
            success=False,
            underlying=params.underlying,
            snapshot_date=params.snapshot_date,
            expirations_count=0,
            strikes_count=0,
            pipeline_name=params.pipeline_name,
            duration_seconds=duration,
            error=str(e),
            warnings=warnings,
        )


def execute_batch_snapshot_for_earnings(
    params: SnapshotParams,
    connection_config: Optional[IBConnectionConfig] = None,
    pipeline_factory: Optional[Callable[[SnapshotParams], Any]] = None,
    earnings_reader: Optional[EarningsCalendarReader] = None,
    progress_callback: Optional[Callable[[str, int, int], None]] = None,
) -> BatchSnapshotResult:
    """Execute batch snapshot for all symbols with earnings on a specific date.

    Pure business logic with no CLI dependencies. All I/O is injectable.

    Args:
        params: Validated snapshot parameters with earnings_date set (Pydantic model)
        connection_config: IB connection config (optional, auto-loads if None)
        pipeline_factory: Optional factory for creating pipelines (for testing)
        earnings_reader: Optional earnings reader (for testing with mocks)
        progress_callback: Optional callback(symbol, current, total) for progress updates

    Returns:
        BatchSnapshotResult with aggregated results from all symbols

    Example:
        >>> params = SnapshotParams(
        ...     earnings_date=date(2025, 11, 13),
        ...     snapshot_date=date(2025, 11, 13),
        ...     min_dte=0,
        ...     max_dte=7,
        ...     pipeline_name="ib_options",
        ... )
        >>> result = execute_batch_snapshot_for_earnings(params)
        >>> assert result.success
        >>> assert result.total_symbols > 0
    """
    start_time = time.time()
    warnings = []
    individual_results = []
    failed_symbols = []

    try:
        # Validate that earnings_date is set
        if not params.earnings_date:
            raise ValueError("earnings_date must be set for batch snapshot")

        logger.info(
            f"Starting batch snapshot: earnings_date={params.earnings_date}, "
            f"snapshot_date={params.snapshot_date}, min_dte={params.min_dte}, max_dte={params.max_dte}"
        )

        # Create earnings reader if not provided
        if earnings_reader is None:
            earnings_reader = EarningsCalendarReader(
                database_path=str(params.database_path),
                dataset_name=params.earnings_dataset_name,
            )
            logger.debug("Created earnings reader")

        # Query earnings for the specific date
        logger.info(f"Querying earnings for {params.earnings_date}")
        earnings_df = earnings_reader.get_earnings_on_date(
            earnings_date=params.earnings_date,
        )

        if earnings_df.empty:
            logger.warning(f"No earnings found for {params.earnings_date}")
            duration = time.time() - start_time
            return BatchSnapshotResult(
                success=True,  # Success but no data
                earnings_date=params.earnings_date,
                snapshot_date=params.snapshot_date,
                total_symbols=0,
                successful_snapshots=0,
                failed_snapshots=0,
                failed_symbols=[],
                pipeline_name=params.pipeline_name,
                duration_seconds=duration,
                warnings=["No earnings found for the specified date"],
            )

        # Apply earnings time filter if provided
        if params.earnings_time_filter:
            logger.info(f"Applying earnings time filter: {params.earnings_time_filter}")
            earnings_df = earnings_df[earnings_df['earnings_time'] == params.earnings_time_filter]

            if earnings_df.empty:
                logger.warning(f"No earnings after time filter: {params.earnings_time_filter}")
                duration = time.time() - start_time
                return BatchSnapshotResult(
                    success=True,
                    earnings_date=params.earnings_date,
                    snapshot_date=params.snapshot_date,
                    total_symbols=0,
                    successful_snapshots=0,
                    failed_snapshots=0,
                    failed_symbols=[],
                    pipeline_name=params.pipeline_name,
                    duration_seconds=duration,
                    warnings=[f"No earnings found with time filter: {params.earnings_time_filter}"],
                )

        # Extract unique symbols
        symbols = earnings_df['symbol'].unique().tolist()
        total_symbols = len(symbols)

        logger.info(f"Found {total_symbols} symbols with earnings: {', '.join(symbols[:10])}{'...' if total_symbols > 10 else ''}")

        # Create connection config if not provided
        if connection_config is None:
            connection_config = get_connection_config()
            logger.debug("Loaded connection config")

        # Process each symbol
        for i, symbol in enumerate(symbols, 1):
            logger.info(f"Processing symbol {i}/{total_symbols}: {symbol}")

            # Call progress callback if provided
            if progress_callback:
                progress_callback(symbol, i, total_symbols)

            try:
                # Create params for this symbol
                symbol_params = SnapshotParams(
                    underlying=symbol,
                    snapshot_date=params.snapshot_date,
                    min_dte=params.min_dte,
                    max_dte=params.max_dte,
                    pipeline_name=params.pipeline_name,
                    dataset_name=params.dataset_name,
                    cache_path=params.cache_path,
                    database_path=params.database_path,
                    earnings_dataset_name=params.earnings_dataset_name,
                )

                # Execute snapshot for this symbol
                result = execute_snapshot(
                    params=symbol_params,
                    connection_config=connection_config,
                    pipeline_factory=pipeline_factory,
                )

                individual_results.append(result)

                if not result.success:
                    failed_symbols.append(symbol)
                    logger.warning(f"✗ {symbol}: {result.error}")
                else:
                    logger.info(
                        f"✓ {symbol}: {result.expirations_count} expirations, "
                        f"{result.strikes_count} strikes ({result.duration_seconds:.1f}s)"
                    )

                # Collect warnings
                if result.warnings:
                    warnings.extend([f"{symbol}: {w}" for w in result.warnings])

            except Exception as e:
                # Log error but continue with next symbol
                logger.error(f"✗ {symbol}: Exception: {e}")
                failed_symbols.append(symbol)

                # Create failed result for tracking
                failed_result = SnapshotResult(
                    success=False,
                    underlying=symbol,
                    snapshot_date=params.snapshot_date,
                    expirations_count=0,
                    strikes_count=0,
                    pipeline_name=params.pipeline_name,
                    duration_seconds=0.0,
                    error=str(e),
                )
                individual_results.append(failed_result)

        # Calculate final stats
        successful = sum(1 for r in individual_results if r.success)
        failed = len(failed_symbols)
        duration = time.time() - start_time

        logger.info(
            f"Batch snapshot complete: {successful}/{total_symbols} succeeded, "
            f"{failed} failed, duration={duration:.1f}s"
        )

        return BatchSnapshotResult(
            success=successful > 0,  # Success if at least one succeeded
            earnings_date=params.earnings_date,
            snapshot_date=params.snapshot_date,
            total_symbols=total_symbols,
            successful_snapshots=successful,
            failed_snapshots=failed,
            failed_symbols=failed_symbols,
            pipeline_name=params.pipeline_name,
            duration_seconds=duration,
            warnings=warnings,
            individual_results=individual_results,
        )

    except Exception as e:
        duration = time.time() - start_time
        logger.error(f"Batch snapshot failed: {e}", exc_info=True)

        return BatchSnapshotResult(
            success=False,
            earnings_date=params.earnings_date or params.snapshot_date,  # Fallback if earnings_date not set
            snapshot_date=params.snapshot_date,
            total_symbols=0,
            successful_snapshots=0,
            failed_snapshots=0,
            failed_symbols=[],
            pipeline_name=params.pipeline_name,
            duration_seconds=duration,
            warnings=warnings,
            individual_results=individual_results,
        )


def execute_list_snapshots(
    params: ListSnapshotsParams,
    reader: Optional[OptionChainSnapshotReader] = None,
) -> ListSnapshotsResult:
    """Execute list-snapshots operation.

    Pure business logic with no CLI dependencies. All I/O is injectable.

    Args:
        params: Validated list-snapshots parameters (Pydantic model)
        reader: Optional repository (for testing with mocks)

    Returns:
        ListSnapshotsResult with structured response

    Example:
        >>> params = ListSnapshotsParams(underlying="AAPL")
        >>> result = execute_list_snapshots(params)
        >>> assert result.success
        >>> assert len(result.snapshots) >= 0
    """
    start_time = time.time()

    try:
        logger.info(f"Listing snapshots: underlying={params.underlying}, database={params.database_path}")

        # Create reader if not provided
        if reader is None:
            reader = OptionChainSnapshotReader(
                database_path=str(params.database_path),
                dataset_name=params.dataset_name,
            )
            logger.debug("Created reader")

        # Query snapshots
        logger.debug("Querying snapshots")
        snapshots_data = reader.get_snapshots(
            underlying=params.underlying,
            start_date=params.start_date,
            end_date=params.end_date,
        )

        # Convert to SnapshotInfo objects
        snapshots = []
        for snapshot in snapshots_data:
            snapshot_info = SnapshotInfo(
                underlying=snapshot.get("underlying", ""),
                snapshot_date=snapshot.get("as_of"),
                expirations=len(snapshot.get("expirations", [])),
                strikes=len(snapshot.get("strikes", [])),
            )
            snapshots.append(snapshot_info)

        duration = time.time() - start_time

        logger.info(f"List snapshots complete: {len(snapshots)} found, duration={duration:.1f}s")

        return ListSnapshotsResult(
            success=True,
            snapshots=snapshots,
            total_count=len(snapshots),
            duration_seconds=duration,
        )

    except Exception as e:
        duration = time.time() - start_time
        logger.error(f"List snapshots failed: {e}", exc_info=True)

        return ListSnapshotsResult(
            success=False,
            snapshots=[],
            total_count=0,
            duration_seconds=duration,
            error=str(e),
        )
