"""
Post-load deduplication for Delta Lake and Parquet tables.

This module provides utilities to deduplicate data after DLT pipeline runs,
ensuring data quality by removing duplicate rows based on primary keys.

Features:
- Delta Lake table deduplication (atomic operations via transaction log)
- Parquet file deduplication (creates new deduplicated files)
- Dry-run mode for safe preview
- Detailed reporting (before/after counts, duplicate stats)
- Backup support
- Progress tracking

Usage:
    from dlt_ibapi.maintenance import deduplicate_delta_table

    # Deduplicate single table
    result = deduplicate_delta_table(
        data_dir="./data",
        dataset="options",
        table_name="option_bars_backfill",
        primary_key=["underlying", "expiry", "strike", "right", "bar_size", "time"],
        dry_run=False
    )

    print(f"Removed {result.duplicates_removed} duplicate rows")
"""

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple
import shutil

import duckdb
import pandas as pd


@dataclass
class DeduplicationResult:
    """
    Result of a deduplication operation.

    Attributes:
        table_name: Name of table that was deduplicated
        rows_before: Total rows before deduplication
        rows_after: Total rows after deduplication
        duplicates_removed: Number of duplicate rows removed
        unique_pk_count: Number of unique primary key combinations
        execution_time_sec: Time taken to deduplicate (seconds)
        dry_run: Whether this was a dry-run (no actual changes)
        backup_path: Path to backup if created (None if no backup)
    """
    table_name: str
    rows_before: int
    rows_after: int
    duplicates_removed: int
    unique_pk_count: int
    execution_time_sec: float
    dry_run: bool = False
    backup_path: Optional[str] = None

    @property
    def duplicate_percentage(self) -> float:
        """Calculate percentage of rows that were duplicates."""
        if self.rows_before == 0:
            return 0.0
        return 100.0 * self.duplicates_removed / self.rows_before

    def __str__(self) -> str:
        """Human-readable summary of deduplication result."""
        status = "DRY RUN" if self.dry_run else "COMPLETED"
        lines = [
            f"Deduplication Result [{status}]: {self.table_name}",
            f"  Rows before:         {self.rows_before:,}",
            f"  Rows after:          {self.rows_after:,}",
            f"  Duplicates removed:  {self.duplicates_removed:,} ({self.duplicate_percentage:.2f}%)",
            f"  Unique PK count:     {self.unique_pk_count:,}",
            f"  Execution time:      {self.execution_time_sec:.2f}s",
        ]
        if self.backup_path:
            lines.append(f"  Backup saved to:     {self.backup_path}")
        return "\n".join(lines)


def get_duplicate_report(
    data_dir: str,
    dataset: str,
    table_name: str,
    primary_key: List[str],
) -> Dict[str, any]:
    """
    Analyze table for duplicates without making changes.

    Args:
        data_dir: Path to data directory (e.g., "./data" or "./data_delta")
        dataset: Dataset name (e.g., "options", "stocks")
        table_name: Table name (e.g., "option_bars_backfill")
        primary_key: List of column names forming primary key

    Returns:
        Dictionary with analysis:
        - total_rows: Total row count
        - unique_rows: Unique primary key combinations
        - duplicate_rows: Number of duplicate rows
        - duplicate_pct: Percentage duplicated
        - sample_duplicates: DataFrame with sample duplicate rows (first 10)

    Example:
        >>> report = get_duplicate_report(
        ...     data_dir="./data_delta",
        ...     dataset="options",
        ...     table_name="option_bars_backfill",
        ...     primary_key=["underlying", "expiry", "strike", "right", "bar_size", "time"]
        ... )
        >>> print(f"Duplicates: {report['duplicate_pct']:.2f}%")
    """
    table_path = Path(data_dir) / dataset / table_name

    if not table_path.exists():
        raise ValueError(f"Table does not exist: {table_path}")

    # Check if Delta table
    is_delta = (table_path / "_delta_log").exists()

    # Connect to DuckDB
    conn = duckdb.connect(":memory:")

    if is_delta:
        # Install Delta extension
        conn.execute("INSTALL delta")
        conn.execute("LOAD delta")
        scan_func = f"delta_scan('{table_path}')"
    else:
        # Use Parquet scan with hive partitioning
        scan_func = f"parquet_scan('{table_path}/**/*.parquet', hive_partitioning=true)"

    # Build primary key column list
    pk_cols = ", ".join([f'"{col}"' if col.lower() in ('right', 'left', 'order', 'group') else col for col in primary_key])

    # Get counts
    query = f"""
        SELECT
            COUNT(*) as total_rows,
            COUNT(DISTINCT ({pk_cols})) as unique_rows,
            COUNT(*) - COUNT(DISTINCT ({pk_cols})) as duplicate_rows,
            ROUND(100.0 * (COUNT(*) - COUNT(DISTINCT ({pk_cols}))) / COUNT(*), 2) as duplicate_pct
        FROM {scan_func}
    """

    stats_df = conn.execute(query).df()
    stats = stats_df.iloc[0].to_dict()

    # Get sample duplicates if any exist
    sample_duplicates = pd.DataFrame()
    if stats['duplicate_rows'] > 0:
        # Build quoted column names for JOIN and ORDER BY
        quoted_pk = [f'"{col}"' if col.lower() in ('right', 'left', 'order', 'group') else col for col in primary_key]
        join_conditions = ' AND '.join([f't.{qcol} = d.{qcol}' for qcol in quoted_pk])
        order_by_cols = ', '.join([f't.{qcol}' for qcol in quoted_pk])

        # Find primary keys with duplicates
        duplicate_query = f"""
            WITH duplicate_keys AS (
                SELECT {pk_cols}
                FROM {scan_func}
                GROUP BY {pk_cols}
                HAVING COUNT(*) > 1
                LIMIT 10
            )
            SELECT t.*
            FROM {scan_func} t
            INNER JOIN duplicate_keys d ON {join_conditions}
            ORDER BY {order_by_cols}, t._dlt_load_id DESC
            LIMIT 50
        """
        sample_duplicates = conn.execute(duplicate_query).df()

    conn.close()

    return {
        "total_rows": int(stats["total_rows"]),
        "unique_rows": int(stats["unique_rows"]),
        "duplicate_rows": int(stats["duplicate_rows"]),
        "duplicate_pct": float(stats["duplicate_pct"]),
        "sample_duplicates": sample_duplicates,
    }


def deduplicate_delta_table(
    data_dir: str,
    dataset: str,
    table_name: str,
    primary_key: List[str],
    dry_run: bool = False,
    create_backup: bool = True,
) -> DeduplicationResult:
    """
    Deduplicate a Delta Lake or Parquet table using DISTINCT ON.

    For Delta tables: Uses DuckDB to read, deduplicate, and write back atomically.
    For Parquet tables: Creates new deduplicated files.

    When duplicates exist, keeps the row with the highest _dlt_load_id (most recent).

    Args:
        data_dir: Path to data directory (e.g., "./data_delta")
        dataset: Dataset name (e.g., "options")
        table_name: Table name (e.g., "option_bars_backfill")
        primary_key: List of columns forming primary key
        dry_run: If True, only analyze without making changes (default: False)
        create_backup: If True, backup table before deduplicating (default: True)

    Returns:
        DeduplicationResult with statistics and outcome

    Raises:
        ValueError: If table doesn't exist or primary key is invalid
        RuntimeError: If deduplication fails

    Example:
        >>> result = deduplicate_delta_table(
        ...     data_dir="./data_delta",
        ...     dataset="options",
        ...     table_name="option_bars_backfill",
        ...     primary_key=["underlying", "expiry", "strike", "right", "bar_size", "time"],
        ...     dry_run=False,
        ...     create_backup=True
        ... )
        >>> print(result)
    """
    start_time = datetime.now()

    table_path = Path(data_dir) / dataset / table_name

    if not table_path.exists():
        raise ValueError(f"Table does not exist: {table_path}")

    # Check if Delta table
    is_delta = (table_path / "_delta_log").exists()

    # Connect to DuckDB
    conn = duckdb.connect(":memory:")

    if is_delta:
        conn.execute("INSTALL delta")
        conn.execute("LOAD delta")
        scan_func = f"delta_scan('{table_path}')"
    else:
        scan_func = f"parquet_scan('{table_path}/**/*.parquet', hive_partitioning=true)"

    # Get row counts before deduplication
    count_query = f"SELECT COUNT(*) as count FROM {scan_func}"
    rows_before = int(conn.execute(count_query).fetchone()[0])

    # Build primary key column list (quote reserved keywords)
    pk_cols = [f'"{col}"' if col.lower() in ('right', 'left', 'order', 'group') else col for col in primary_key]
    pk_list = ", ".join(pk_cols)

    # Count unique primary keys
    unique_query = f"SELECT COUNT(DISTINCT ({pk_list})) as count FROM {scan_func}"
    unique_pk_count = int(conn.execute(unique_query).fetchone()[0])

    duplicates_removed = rows_before - unique_pk_count

    # If dry run, return early
    if dry_run:
        conn.close()
        execution_time = (datetime.now() - start_time).total_seconds()
        return DeduplicationResult(
            table_name=table_name,
            rows_before=rows_before,
            rows_after=unique_pk_count,
            duplicates_removed=duplicates_removed,
            unique_pk_count=unique_pk_count,
            execution_time_sec=execution_time,
            dry_run=True,
            backup_path=None,
        )

    # If no duplicates, return early
    if duplicates_removed == 0:
        conn.close()
        execution_time = (datetime.now() - start_time).total_seconds()
        return DeduplicationResult(
            table_name=table_name,
            rows_before=rows_before,
            rows_after=rows_before,
            duplicates_removed=0,
            unique_pk_count=unique_pk_count,
            execution_time_sec=execution_time,
            dry_run=False,
            backup_path=None,
        )

    # Create backup if requested
    backup_path_str = None
    if create_backup:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = table_path.parent / f"{table_name}_backup_{timestamp}"
        shutil.copytree(table_path, backup_path)
        backup_path_str = str(backup_path)

    try:
        # Deduplicate using DISTINCT ON
        # Keep row with highest _dlt_load_id (most recent)
        dedup_query = f"""
            SELECT DISTINCT ON ({pk_list}) *
            FROM {scan_func}
            ORDER BY {pk_list}, _dlt_load_id DESC
        """

        deduped_arrow = conn.execute(dedup_query).arrow()

        # Convert RecordBatchReader to Table if needed
        import pyarrow as pa
        if isinstance(deduped_arrow, pa.ipc.RecordBatchReader):
            deduped_df = deduped_arrow.read_all()
        else:
            deduped_df = deduped_arrow

        # Write back to table
        if is_delta:
            # Write to Delta Lake with overwrite mode
            from deltalake import DeltaTable, write_deltalake

            # Read existing partition scheme from Delta table
            try:
                dt = DeltaTable(str(table_path))
                # Get partition columns from existing table metadata
                existing_partitions = dt.metadata().partition_columns
                partition_cols = existing_partitions if existing_partitions else None
            except Exception:
                # Fallback: infer from column names
                partition_cols = []
                column_names = [col.lower() for col in deduped_df.schema.names]
                if 'date' in column_names:
                    partition_cols.append('date')
                if 'underlying' in column_names:
                    partition_cols.append('underlying')
                elif 'symbol' in column_names:
                    partition_cols.append('symbol')
                partition_cols = partition_cols if partition_cols else None

            write_deltalake(
                str(table_path),
                deduped_df,
                mode="overwrite",
                partition_by=partition_cols,
            )
        else:
            # For Parquet: delete old files and write new ones
            # This is less ideal but necessary for non-Delta tables
            import pyarrow.parquet as pq

            # Remove old parquet files (keep metadata)
            for parquet_file in table_path.glob("**/*.parquet"):
                parquet_file.unlink()

            # Write new deduplicated file
            pq.write_to_dataset(
                deduped_df,
                root_path=str(table_path),
                partition_cols=partition_cols if partition_cols else None,
            )

        rows_after = len(deduped_df)

    except Exception as e:
        conn.close()
        # If backup exists and operation failed, we can restore
        raise RuntimeError(f"Deduplication failed: {e}") from e

    finally:
        conn.close()

    execution_time = (datetime.now() - start_time).total_seconds()

    return DeduplicationResult(
        table_name=table_name,
        rows_before=rows_before,
        rows_after=rows_after,
        duplicates_removed=duplicates_removed,
        unique_pk_count=unique_pk_count,
        execution_time_sec=execution_time,
        dry_run=False,
        backup_path=backup_path_str,
    )


def deduplicate_dataset(
    data_dir: str,
    dataset: str,
    table_configs: List[Tuple[str, List[str]]],
    dry_run: bool = False,
    create_backup: bool = True,
) -> List[DeduplicationResult]:
    """
    Deduplicate multiple tables in a dataset.

    Args:
        data_dir: Path to data directory
        dataset: Dataset name
        table_configs: List of (table_name, primary_key) tuples
        dry_run: If True, only analyze without making changes
        create_backup: If True, backup tables before deduplicating

    Returns:
        List of DeduplicationResult objects (one per table)

    Example:
        >>> results = deduplicate_dataset(
        ...     data_dir="./data_delta",
        ...     dataset="options",
        ...     table_configs=[
        ...         ("option_bars_backfill", ["underlying", "expiry", "strike", "right", "bar_size", "time"]),
        ...         ("option_chain_snapshot", ["underlying", "as_of", "exchange", "trading_class"]),
        ...     ],
        ...     dry_run=False
        ... )
        >>> for result in results:
        ...     print(result)
    """
    results = []

    for table_name, primary_key in table_configs:
        try:
            result = deduplicate_delta_table(
                data_dir=data_dir,
                dataset=dataset,
                table_name=table_name,
                primary_key=primary_key,
                dry_run=dry_run,
                create_backup=create_backup,
            )
            results.append(result)
        except Exception as e:
            # Create error result
            error_result = DeduplicationResult(
                table_name=table_name,
                rows_before=0,
                rows_after=0,
                duplicates_removed=0,
                unique_pk_count=0,
                execution_time_sec=0,
                dry_run=dry_run,
                backup_path=None,
            )
            results.append(error_result)
            print(f"ERROR deduplicating {table_name}: {e}")

    return results
