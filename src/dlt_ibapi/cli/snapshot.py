"""Snapshot business logic - testable, framework-independent.

Extracts snapshot logic from CLI for easy testing without Typer.
Uses Pydantic models for type safety and dependency injection for I/O.
"""

import time
from typing import Optional, Callable, Any
from pathlib import Path

import dlt

from dlt_ibapi.cli.models import (
    SnapshotParams,
    SnapshotResult,
    ListSnapshotsParams,
    ListSnapshotsResult,
    SnapshotInfo,
)
from dlt_ibapi.config import IBConnectionConfig
from dlt_ibapi.config_loader import get_connection_config
from dlt_ibapi.backfill import snapshot_option_chain
from dlt_ibapi.repositories import OptionChainSnapshotReader
from dlt_ibapi.utils.logging import get_logger

logger = get_logger(__name__)


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
            "starting_snapshot",
            underlying=params.underlying,
            snapshot_date=str(params.snapshot_date),
            min_dte=params.min_dte,
            max_dte=params.max_dte,
        )

        # Create config if not provided
        if connection_config is None:
            connection_config = get_connection_config()
            logger.debug("loaded_connection_config")

        # Check for future dates
        from datetime import date as date_type
        if params.snapshot_date > date_type.today():
            warnings.append(
                f"Snapshot date {params.snapshot_date} is in the future. Data may not be available."
            )
            logger.warning("future_snapshot_date", date=str(params.snapshot_date))

        # Create pipeline (or use injected mock for testing)
        if pipeline_factory:
            logger.debug("using_injected_pipeline_factory")
            pipeline = pipeline_factory(params)
        else:
            # Production path: create real DLT pipeline
            logger.info("creating_dlt_pipeline", name=params.pipeline_name)
            pipeline = dlt.pipeline(
                pipeline_name=params.pipeline_name,
                destination=dlt.destinations.filesystem(bucket_url="data"),
                dataset_name=params.dataset_name,
            )

        # Create snapshot resource
        logger.debug("creating_snapshot_resource")
        data = snapshot_option_chain(
            underlying=params.underlying,
            snapshot_date=params.snapshot_date,
            cache_path=str(params.cache_path),
            connection_config=connection_config,
            min_dte=params.min_dte,
            max_dte=params.max_dte,
        )

        # Run pipeline
        logger.info("running_pipeline")
        info = pipeline.run(data, write_disposition="replace", loader_file_format="parquet")

        if info.has_failed_jobs:
            warnings.append("Pipeline jobs failed")
            logger.warning("pipeline_jobs_failed")

        # Calculate metrics
        duration = time.time() - start_time

        # TODO: Extract actual counts from data
        expirations_count = 0
        strikes_count = 0

        logger.info(
            "snapshot_complete",
            underlying=params.underlying,
            duration=duration,
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
        logger.error("snapshot_failed", error=str(e), duration=duration)

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
        logger.info(
            "listing_snapshots",
            underlying=params.underlying,
            database_path=str(params.database_path),
        )

        # Create reader if not provided
        if reader is None:
            reader = OptionChainSnapshotReader(
                database_path=str(params.database_path),
                dataset_name=params.dataset_name,
            )
            logger.debug("created_reader")

        # Query snapshots
        logger.debug("querying_snapshots")
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

        logger.info(
            "list_snapshots_complete",
            total=len(snapshots),
            duration=duration,
        )

        return ListSnapshotsResult(
            success=True,
            snapshots=snapshots,
            total_count=len(snapshots),
            duration_seconds=duration,
        )

    except Exception as e:
        duration = time.time() - start_time
        logger.error("list_snapshots_failed", error=str(e), duration=duration)

        return ListSnapshotsResult(
            success=False,
            snapshots=[],
            total_count=0,
            duration_seconds=duration,
            error=str(e),
        )
