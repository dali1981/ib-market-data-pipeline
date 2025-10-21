"""
Parquet reader base class with hybrid query routing.

This module provides a base class for reading Parquet files written by DLT's
filesystem destination. It uses a hybrid approach:
- DuckDB in-memory for small queries (metadata, aggregations, snapshots)
- PyArrow for large queries (historical bars with predicate pushdown)

The reader automatically routes queries to the appropriate engine based on
query type and data size.
"""

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Union
from datetime import date
import os

import duckdb
import pandas as pd
import pyarrow.dataset as ds
import pyarrow.compute as pc


class ParquetReaderBase(ABC):
    """
    Abstract base class for reading Parquet files written by DLT filesystem destination.

    Provides hybrid query routing:
    - DuckDB in-memory: Small queries, aggregations, metadata
    - PyArrow: Large scans with predicate pushdown

    Subclasses must implement:
    - _get_table_name(): Return the table name (e.g., "equity_bars")
    - _should_use_duckdb(): Decide which engine to use for a query
    """

    def __init__(
        self,
        database_path: Union[str, Path],
        dataset_name: str = "stocks",
    ):
        """
        Initialize Parquet reader.

        Args:
            database_path: Path to Parquet data directory (e.g., "data")
            dataset_name: DLT dataset name (subdirectory, e.g., "stocks")
        """
        self.database_path = Path(database_path)
        self.dataset_name = dataset_name
        self.data_root = self.database_path / dataset_name

        if not self.data_root.exists():
            raise ValueError(f"Data directory does not exist: {self.data_root}")

    @abstractmethod
    def _get_table_name(self) -> str:
        """Get the name of the table to query (e.g., 'equity_bars')."""
        pass

    def _get_table_path(self) -> Path:
        """Get the full path to the table's Parquet files."""
        table_name = self._get_table_name()
        return self.data_root / table_name

    def _should_use_duckdb(self, query_type: str) -> bool:
        """
        Decide whether to use DuckDB or PyArrow for a query.

        Args:
            query_type: Type of query ("metadata", "aggregation", "scan", "custom")

        Returns:
            True to use DuckDB, False to use PyArrow

        Default implementation:
        - "metadata": DuckDB (DISTINCT, COUNT, MIN, MAX)
        - "aggregation": DuckDB (GROUP BY, aggregates)
        - "scan": PyArrow (full table scans, large result sets)
        - "custom": DuckDB (user-provided SQL)
        """
        return query_type in ("metadata", "aggregation", "custom")

    def _query_with_duckdb(
        self,
        query: str,
        params: Optional[Dict[str, Any]] = None
    ) -> pd.DataFrame:
        """
        Execute query using DuckDB in-memory on Parquet files.

        Args:
            query: SQL query string
            params: Optional query parameters

        Returns:
            Query results as DataFrame
        """
        import glob

        conn = duckdb.connect(":memory:")
        try:
            # Register Parquet dataset with Hive partitioning
            table_path = self._get_table_path()
            table_name = self._get_table_name()

            # Check if any Parquet files exist
            parquet_pattern = f"{table_path}/**/*.parquet"
            if not glob.glob(parquet_pattern, recursive=True):
                # No files exist - return empty DataFrame
                # This handles the first-run case for backfill
                return pd.DataFrame()

            # Create view of Parquet files
            conn.execute(f"""
                CREATE VIEW {table_name} AS
                SELECT * FROM parquet_scan('{table_path}/**/*.parquet', hive_partitioning=true)
            """)

            # Execute query
            if params:
                result = conn.execute(query, params).df()
            else:
                result = conn.execute(query).df()

            return result
        finally:
            conn.close()

    def _query_with_pyarrow(
        self,
        columns: Optional[List[str]] = None,
        filters: Optional[pc.Expression] = None,
        limit: Optional[int] = None
    ) -> pd.DataFrame:
        """
        Query Parquet files using PyArrow with predicate pushdown.

        Args:
            columns: Columns to select (None = all)
            filters: PyArrow filter expression (e.g., pc.field("symbol") == "AAPL")
            limit: Maximum rows to return (applied after filtering)

        Returns:
            Query results as DataFrame
        """
        table_path = self._get_table_path()

        # Create PyArrow dataset with Hive partitioning
        dataset = ds.dataset(
            table_path,
            format="parquet",
            partitioning="hive"
        )

        # Build scanner
        scanner_kwargs = {
            "columns": columns,
            "filter": filters,
        }

        scanner = dataset.scanner(**scanner_kwargs)

        # Convert to pandas
        table = scanner.to_table()

        # Apply limit if specified
        if limit is not None and len(table) > limit:
            table = table.slice(0, limit)

        return table.to_pandas()

    def query(self, sql: str, params: Optional[Dict[str, Any]] = None) -> pd.DataFrame:
        """
        Execute custom SQL query using DuckDB.

        Args:
            sql: SQL query string
            params: Optional query parameters

        Returns:
            Query results as DataFrame
        """
        return self._query_with_duckdb(sql, params)

    def get_present_dates(
        self,
        start_date: date,
        end_date: date,
        **filters
    ) -> Set[date]:
        """
        Get set of dates with data in the specified range.

        Used for gap detection in backfill operations.
        Uses DuckDB for efficient aggregation.

        Args:
            start_date: Start date (inclusive)
            end_date: End date (inclusive)
            **filters: Additional filters (symbol, bar_size, etc.)

        Returns:
            Set of dates with available data
        """
        table_name = self._get_table_name()

        # Build WHERE clause
        where_clauses = ["DATE(time) BETWEEN $start_date AND $end_date"]
        params = {"start_date": start_date, "end_date": end_date}

        for key, value in filters.items():
            if value is not None:
                param_name = f"filter_{key}"
                where_clauses.append(f"{key} = ${param_name}")
                params[param_name] = value

        where_sql = " AND ".join(where_clauses)

        query = f"""
            SELECT DISTINCT DATE(time) as date
            FROM {table_name}
            WHERE {where_sql}
            ORDER BY date
        """

        df = self._query_with_duckdb(query, params)
        return set(df["date"].tolist()) if not df.empty else set()

    def load(
        self,
        columns: Optional[List[str]] = None,
        limit: Optional[int] = None,
        use_pyarrow: bool = False,
        **filters
    ) -> pd.DataFrame:
        """
        Load data from table with optional filtering.

        Args:
            columns: Columns to select (None = all)
            limit: Maximum rows to return
            use_pyarrow: Force use of PyArrow (default: auto-detect)
            **filters: Column filters (e.g., symbol="AAPL")

        Returns:
            Query results as DataFrame
        """
        table_name = self._get_table_name()

        # Decide which engine to use
        if use_pyarrow or not self._should_use_duckdb("scan"):
            # Use PyArrow with predicate pushdown
            # Convert filters to PyArrow expressions
            filter_expr = None
            for key, value in filters.items():
                if value is not None:
                    expr = pc.field(key) == value
                    filter_expr = expr if filter_expr is None else filter_expr & expr

            return self._query_with_pyarrow(columns, filter_expr, limit)
        else:
            # Use DuckDB
            # Build SELECT clause
            if columns:
                select_clause = ", ".join(columns)
            else:
                select_clause = "*"

            # Build WHERE clause
            where_clauses = []
            params = {}

            for key, value in filters.items():
                if value is not None:
                    param_name = f"filter_{key}"
                    where_clauses.append(f"{key} = ${param_name}")
                    params[param_name] = value

            # Build query
            query = f"SELECT {select_clause} FROM {table_name}"

            if where_clauses:
                query += " WHERE " + " AND ".join(where_clauses)

            if limit:
                query += f" LIMIT {limit}"

            return self._query_with_duckdb(query, params)

    def count(self, **filters) -> int:
        """
        Count rows matching filters.
        Uses DuckDB for efficient aggregation.

        Args:
            **filters: Column filters

        Returns:
            Row count
        """
        table_name = self._get_table_name()

        # Build WHERE clause
        where_clauses = []
        params = {}

        for key, value in filters.items():
            if value is not None:
                param_name = f"filter_{key}"
                where_clauses.append(f"{key} = ${param_name}")
                params[param_name] = value

        query = f"SELECT COUNT(*) as count FROM {table_name}"

        if where_clauses:
            query += " WHERE " + " AND ".join(where_clauses)

        df = self._query_with_duckdb(query, params)
        return int(df.iloc[0]["count"]) if not df.empty else 0
