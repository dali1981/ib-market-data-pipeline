"""
Dataset statistics reader for analyzing Parquet tables.

Provides generic stats collection for any table in a DLT dataset.
Uses the repository pattern but doesn't inherit from BaseReader since it's
a generic reader that works across multiple tables.
"""

from pathlib import Path
from typing import List, Optional, Dict, Any
import glob

import duckdb
import pandas as pd


class DatasetStatsReader:
    """
    Reader for collecting statistics across all tables in a dataset.

    Discovers all Parquet tables and collects metadata like:
    - Row counts
    - Column names
    - Date ranges (if time/date columns exist)
    - Symbol lists (if symbol/underlying columns exist)

    This is a generic reader that doesn't need to know specific table schemas.
    """

    def __init__(
        self,
        database_path: Path | str,
        dataset_name: str,
    ):
        """
        Initialize dataset stats reader.

        Args:
            database_path: Path to Parquet data directory (e.g., "data")
            dataset_name: DLT dataset name (subdirectory, e.g., "stocks", "options")
        """
        self.database_path = Path(database_path)
        self.dataset_name = dataset_name
        self.data_root = self.database_path / dataset_name
        self.destination_type = "filesystem"

        if not self.data_root.exists():
            raise ValueError(f"Dataset directory does not exist: {self.data_root}")

    def discover_tables(self) -> List[str]:
        """
        Discover all tables in the dataset.

        Tables are subdirectories containing Parquet files.

        Returns:
            List of table names
        """
        tables = []

        for path in self.data_root.iterdir():
            if path.is_dir():
                # Check if directory contains Parquet files (exclude _delta_log)
                parquet_pattern = str(path / "**/*.parquet")
                parquet_files = [
                    f for f in glob.glob(parquet_pattern, recursive=True)
                    if "_delta_log" not in f
                ]
                if parquet_files:
                    tables.append(path.name)

        return sorted(tables)

    def get_table_stats(self, table_name: str) -> Dict[str, Any]:
        """
        Get statistics for a specific table.

        Args:
            table_name: Name of the table to analyze

        Returns:
            Dictionary with:
            - table_name: str
            - row_count: int
            - columns: List[str]
            - date_range: Optional[str]
            - symbols: Optional[List[str]]

        Raises:
            ValueError: If table doesn't exist
        """
        table_path = self.data_root / table_name

        if not table_path.exists():
            raise ValueError(f"Table directory does not exist: {table_path}")

        # Check if any Parquet files exist (exclude _delta_log)
        parquet_pattern = str(table_path / "**/*.parquet")
        parquet_files = [
            f for f in glob.glob(parquet_pattern, recursive=True)
            if "_delta_log" not in f
        ]

        if not parquet_files:
            return {
                "table_name": table_name,
                "row_count": 0,
                "columns": [],
                "date_range": None,
                "symbols": None,
            }

        conn = duckdb.connect(":memory:")

        try:
            # Build file list query parameter (exclude _delta_log files)
            # Use explicit file list instead of glob pattern for better control
            file_list = ", ".join(f"'{f}'" for f in parquet_files)

            # Query row count
            count_query = f"""
                SELECT COUNT(*) as count
                FROM read_parquet([{file_list}], hive_partitioning=true)
            """
            row_count = int(conn.execute(count_query).fetchone()[0])

            # Get column names
            columns_query = f"""
                DESCRIBE SELECT * FROM read_parquet([{file_list}], hive_partitioning=true) LIMIT 0
            """
            columns_result = conn.execute(columns_query).fetchall()
            columns = [row[0] for row in columns_result]

            # Try to get date range if applicable
            date_range = None
            date_col = None
            if "time" in columns:
                date_col = "time"
            elif "date" in columns:
                date_col = "date"
            elif "as_of" in columns:
                date_col = "as_of"

            if date_col:
                try:
                    date_query = f"""
                        SELECT
                            MIN({date_col})::VARCHAR as min_date,
                            MAX({date_col})::VARCHAR as max_date
                        FROM read_parquet([{file_list}], hive_partitioning=true)
                    """
                    date_result = conn.execute(date_query).fetchone()
                    if date_result and date_result[0] and date_result[1]:
                        date_range = f"{date_result[0]} to {date_result[1]}"
                except Exception:
                    # Silently ignore date range errors
                    pass

            # Try to get symbols if applicable
            symbols = None
            symbol_col = None
            if "symbol" in columns:
                symbol_col = "symbol"
            elif "underlying" in columns:
                symbol_col = "underlying"

            if symbol_col:
                try:
                    symbols_query = f"""
                        SELECT DISTINCT {symbol_col}
                        FROM read_parquet([{file_list}], hive_partitioning=true)
                        ORDER BY {symbol_col}
                        LIMIT 100
                    """
                    symbols_result = conn.execute(symbols_query).fetchall()
                    symbols = [row[0] for row in symbols_result]
                except Exception:
                    # Silently ignore symbol errors
                    pass

            return {
                "table_name": table_name,
                "row_count": row_count,
                "columns": columns,
                "date_range": date_range,
                "symbols": symbols,
            }

        finally:
            conn.close()

    def get_all_stats(
        self,
        table_name: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Get statistics for all tables in the dataset.

        Args:
            table_name: Optional filter for specific table

        Returns:
            List of table statistics dictionaries
        """
        if table_name:
            # Single table
            return [self.get_table_stats(table_name)]
        else:
            # All tables
            tables = self.discover_tables()
            return [self.get_table_stats(table) for table in tables]
