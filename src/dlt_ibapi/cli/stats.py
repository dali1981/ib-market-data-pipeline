"""Stats business logic - testable, framework-independent.

Extracts stats logic from CLI for easy testing without Typer.
Uses Pydantic models for type safety and dependency injection for I/O.
"""

import time
from typing import Optional

from dlt_ibapi.cli.models import StatsParams, StatsResult, TableStats
from dlt_ibapi.repositories import DatasetStatsReader
from dlt_ibapi.utils.logging import get_logger

logger = get_logger(__name__)


def execute_stats(
    params: StatsParams,
    stats_reader: Optional[DatasetStatsReader] = None,
) -> StatsResult:
    """Execute stats operation on Parquet data using repository pattern.

    Pure business logic with no CLI dependencies. All I/O is injectable.

    Args:
        params: Validated stats parameters (Pydantic model)
        stats_reader: Optional DatasetStatsReader (for testing with mocks)

    Returns:
        StatsResult with structured response

    Example:
        >>> params = StatsParams(
        ...     database_path=Path("./data"),
        ...     dataset_name="stocks",
        ... )
        >>> result = execute_stats(params)
        >>> assert result.success
        >>> assert len(result.tables) >= 0
    """
    start_time = time.time()

    try:
        logger.info(f"gathering_stats: database_path={params.database_path}, dataset_name={params.dataset_name}")

        # Create stats reader if not provided (dependency injection)
        if stats_reader is None:
            try:
                stats_reader = DatasetStatsReader(
                    database_path=params.database_path,
                    dataset_name=params.dataset_name,
                )
            except ValueError as e:
                logger.warning(f"dataset_not_found: {e}")
                return StatsResult(
                    success=False,
                    database_path=params.database_path,
                    dataset_name=params.dataset_name,
                    tables=[],
                    total_tables=0,
                    duration_seconds=time.time() - start_time,
                    error=str(e),
                )

        # Get all stats using repository
        table_stats_list = stats_reader.get_all_stats(table_name=params.table_name)

        # Convert to Pydantic models
        tables = [
            TableStats(
                table_name=stats["table_name"],
                row_count=stats["row_count"],
                columns=stats["columns"],
                date_range=stats["date_range"],
                symbols=stats["symbols"],
            )
            for stats in table_stats_list
        ]

        duration = time.time() - start_time

        logger.info(f"stats_complete: tables={len(tables)}, duration={duration:.2f}s")

        return StatsResult(
            success=True,
            database_path=params.database_path,
            dataset_name=params.dataset_name,
            tables=tables,
            total_tables=len(tables),
            duration_seconds=duration,
        )

    except Exception as e:
        duration = time.time() - start_time
        logger.error(f"stats_failed: {e}, duration={duration:.2f}s")

        return StatsResult(
            success=False,
            database_path=params.database_path,
            dataset_name=params.dataset_name,
            tables=[],
            total_tables=0,
            duration_seconds=duration,
            error=str(e),
        )
