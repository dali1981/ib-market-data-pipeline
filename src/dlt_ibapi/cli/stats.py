"""Stats business logic - testable, framework-independent.

Extracts stats logic from CLI for easy testing without Typer.
Uses Pydantic models for type safety and dependency injection for I/O.
"""

import time
from typing import Optional, List
from pathlib import Path
import duckdb

from dlt_ibapi.cli.models import StatsParams, StatsResult, TableStats
from dlt_ibapi.utils.logging import get_logger

logger = get_logger(__name__)


def execute_stats(
    params: StatsParams,
    duckdb_conn: Optional[duckdb.DuckDBPyConnection] = None,
) -> StatsResult:
    """Execute stats operation on Parquet data.

    Pure business logic with no CLI dependencies. All I/O is injectable.

    Args:
        params: Validated stats parameters (Pydantic model)
        duckdb_conn: Optional DuckDB connection (for testing with mocks)

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
    tables = []

    try:
        logger.info(
            "gathering_stats",
            database_path=str(params.database_path),
            dataset_name=params.dataset_name,
        )

        # Create DuckDB connection if not provided
        if duckdb_conn is None:
            duckdb_conn = duckdb.connect(":memory:")
            logger.debug("created_duckdb_connection")

        # Build path to Parquet files
        parquet_path = params.database_path / params.dataset_name
        if not parquet_path.exists():
            logger.warning("dataset_path_not_found", path=str(parquet_path))
            return StatsResult(
                success=False,
                database_path=params.database_path,
                dataset_name=params.dataset_name,
                tables=[],
                total_tables=0,
                duration_seconds=time.time() - start_time,
                error=f"Dataset path not found: {parquet_path}",
            )

        # Find all Parquet files
        parquet_files = list(parquet_path.rglob("*.parquet"))
        logger.debug("found_parquet_files", count=len(parquet_files))

        if not parquet_files:
            logger.warning("no_parquet_files_found", path=str(parquet_path))
            return StatsResult(
                success=True,
                database_path=params.database_path,
                dataset_name=params.dataset_name,
                tables=[],
                total_tables=0,
                duration_seconds=time.time() - start_time,
            )

        # Group files by table name (subdirectory name)
        table_files = {}
        for file in parquet_files:
            # Get table name from parent directory
            table_name = file.parent.name
            if table_name not in table_files:
                table_files[table_name] = []
            table_files[table_name].append(file)

        # Analyze each table
        for table_name, files in table_files.items():
            if params.table_name and table_name != params.table_name:
                continue

            logger.debug("analyzing_table", table=table_name, files=len(files))

            try:
                # Query table using parquet_scan with hive partitioning
                file_pattern = str(files[0].parent / "*.parquet")
                query = f"""
                    SELECT COUNT(*) as row_count
                    FROM parquet_scan('{file_pattern}', hive_partitioning=true)
                """
                result = duckdb_conn.execute(query).fetchone()
                row_count = result[0] if result else 0

                # Get column names
                query = f"""
                    DESCRIBE SELECT * FROM parquet_scan('{file_pattern}', hive_partitioning=true) LIMIT 0
                """
                columns_result = duckdb_conn.execute(query).fetchall()
                columns = [row[0] for row in columns_result]

                # Try to get date range if applicable
                date_range = None
                if "time" in columns or "date" in columns:
                    date_col = "time" if "time" in columns else "date"
                    query = f"""
                        SELECT
                            MIN({date_col})::VARCHAR as min_date,
                            MAX({date_col})::VARCHAR as max_date
                        FROM parquet_scan('{file_pattern}', hive_partitioning=true)
                    """
                    try:
                        date_result = duckdb_conn.execute(query).fetchone()
                        if date_result:
                            date_range = f"{date_result[0]} to {date_result[1]}"
                    except Exception as e:
                        logger.debug("could_not_get_date_range", table=table_name, error=str(e))

                # Try to get symbols if applicable
                symbols = None
                if "symbol" in columns or "underlying" in columns:
                    symbol_col = "symbol" if "symbol" in columns else "underlying"
                    query = f"""
                        SELECT DISTINCT {symbol_col}
                        FROM parquet_scan('{file_pattern}', hive_partitioning=true)
                        ORDER BY {symbol_col}
                    """
                    try:
                        symbols_result = duckdb_conn.execute(query).fetchall()
                        symbols = [row[0] for row in symbols_result]
                    except Exception as e:
                        logger.debug("could_not_get_symbols", table=table_name, error=str(e))

                table_stats = TableStats(
                    table_name=table_name,
                    row_count=row_count,
                    columns=columns,
                    date_range=date_range,
                    symbols=symbols,
                )
                tables.append(table_stats)

                logger.info(
                    "table_analyzed",
                    table=table_name,
                    rows=row_count,
                    columns=len(columns),
                )

            except Exception as e:
                logger.error("table_analysis_failed", table=table_name, error=str(e))

        duration = time.time() - start_time

        logger.info(
            "stats_complete",
            tables=len(tables),
            duration=duration,
        )

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
        logger.error("stats_failed", error=str(e), duration=duration)

        return StatsResult(
            success=False,
            database_path=params.database_path,
            dataset_name=params.dataset_name,
            tables=[],
            total_tables=0,
            duration_seconds=duration,
            error=str(e),
        )
