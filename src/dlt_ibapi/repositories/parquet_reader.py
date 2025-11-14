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
        self.destination_type = "filesystem"

        # Connection pooling: reuse connection across queries
        self._conn: Optional[duckdb.DuckDBPyConnection] = None
        self._delta_extension_loaded = False

        if not self.data_root.exists():
            raise ValueError(f"Data directory does not exist: {self.data_root}")

    def _is_delta_table(self, table_path: Path) -> bool:
        """Check if table is a Delta Lake table."""
        return (table_path / "_delta_log").exists()

    def _get_connection(self) -> duckdb.DuckDBPyConnection:
        """
        Get or create persistent DuckDB connection.

        Connection is reused across queries to avoid overhead of creating
        new connections and reinstalling extensions.

        Returns:
            Persistent DuckDB in-memory connection
        """
        if self._conn is None:
            self._conn = duckdb.connect(":memory:")
        return self._conn

    def _ensure_delta_extension(self, conn: duckdb.DuckDBPyConnection) -> None:
        """
        Ensure Delta Lake extension is installed and loaded.

        Only installs/loads once per connection to avoid redundant operations
        and async channel warnings from delta-rs.

        Args:
            conn: DuckDB connection to install extension on
        """
        if not self._delta_extension_loaded:
            try:
                conn.execute("INSTALL delta")
                conn.execute("LOAD delta")
                self._delta_extension_loaded = True
            except Exception:
                # Delta extension installation failed, fall back to Parquet-only
                pass

    def close(self) -> None:
        """
        Close the persistent DuckDB connection.

        Call this explicitly when done with the reader to free resources.
        Also called automatically when using reader as context manager.
        """
        if self._conn is not None:
            self._conn.close()
            self._conn = None
            self._delta_extension_loaded = False

    def __enter__(self):
        """Context manager entry."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit - automatically closes connection."""
        self.close()
        return False

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

        Uses a persistent connection that is reused across queries to avoid
        overhead of creating new connections and reinstalling extensions.
        This eliminates async channel warnings from delta-rs.

        Args:
            query: SQL query string
            params: Optional query parameters

        Returns:
            Query results as DataFrame
        """
        import glob

        # Get persistent connection (created once, reused for all queries)
        conn = self._get_connection()

        # Register dataset (Parquet or Delta Lake)
        table_path = self._get_table_path()
        table_name = self._get_table_name()

        # Helper function to register a table/view
        def register_table(name: str, path: Path):
            """Register a table as a view if it doesn't exist."""
            try:
                conn.execute(f"SELECT 1 FROM {name} LIMIT 0")
                return  # Already exists
            except Exception:
                pass

            # Check if Delta Lake table
            if self._is_delta_table(path):
                self._ensure_delta_extension(conn)
                delta_ok = False
                try:
                    conn.execute(f"""
                        CREATE VIEW {name} AS
                        SELECT * FROM delta_scan('{path}')
                    """)
                    # Check if Delta has any data
                    row_count = conn.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0]
                    delta_ok = row_count > 0
                except Exception:
                    pass

                if not delta_ok:
                    # Delta empty or failed, fall back to parquet scan (exclude _delta_log)
                    try:
                        conn.execute(f"DROP VIEW IF EXISTS {name}")
                    except:
                        pass
                    parquet_pattern = f"{path}/date=*/*.parquet"
                    conn.execute(f"""
                        CREATE VIEW {name} AS
                        SELECT * FROM parquet_scan('{parquet_pattern}', hive_partitioning=true)
                    """)
            else:
                # Check if any Parquet files exist
                parquet_pattern = f"{path}/**/*.parquet"
                if not glob.glob(parquet_pattern, recursive=True):
                    return  # Skip if no files

                conn.execute(f"""
                    CREATE VIEW {name} AS
                    SELECT * FROM parquet_scan('{path}/**/*.parquet', hive_partitioning=true)
                """)

        # Register main table
        register_table(table_name, table_path)

        # Auto-detect and register DLT child tables (pattern: tablename__childname)
        import re
        child_table_pattern = re.compile(rf'\b({re.escape(table_name)}__\w+)\b')
        child_tables = child_table_pattern.findall(query)
        for child_table in set(child_tables):
            child_path = self.database_path / self.dataset_name / child_table
            if child_path.exists():
                # Child tables don't have date partitions, use different pattern
                if self._is_delta_table(child_path):
                    # For Delta child tables, check if empty and fallback
                    self._ensure_delta_extension(conn)
                    delta_ok = False
                    try:
                        conn.execute(f"""
                            CREATE VIEW {child_table} AS
                            SELECT * FROM delta_scan('{child_path}')
                        """)
                        row_count = conn.execute(f"SELECT COUNT(*) FROM {child_table}").fetchone()[0]
                        delta_ok = row_count > 0
                    except Exception:
                        pass

                    if not delta_ok:
                        try:
                            conn.execute(f"DROP VIEW IF EXISTS {child_table}")
                        except:
                            pass
                        # Child tables are flat (no partitions)
                        conn.execute(f"""
                            CREATE VIEW {child_table} AS
                            SELECT * FROM parquet_scan('{child_path}/*.parquet', hive_partitioning=false)
                        """)
                else:
                    # Regular parquet
                    conn.execute(f"""
                        CREATE VIEW {child_table} AS
                        SELECT * FROM parquet_scan('{child_path}/*.parquet', hive_partitioning=false)
                    """)

        # Execute query
        if params:
            result = conn.execute(query, params).df()
        else:
            result = conn.execute(query).df()

        return result

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

        # Check if Delta Lake table
        if self._is_delta_table(table_path):
            # Use Delta Lake reader
            from deltalake import DeltaTable
            dt = DeltaTable(str(table_path))
            dataset = dt.to_pyarrow_dataset()
        else:
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
                # Quote column name if it's a SQL reserved keyword (e.g., 'right')
                column = f'"{key}"' if key.lower() in ('right', 'left', 'order', 'group') else key
                where_clauses.append(f"{column} = ${param_name}")
                params[param_name] = value

        where_sql = " AND ".join(where_clauses)

        query = f"""
            SELECT DISTINCT DATE(time) as date
            FROM {table_name}
            WHERE {where_sql}
            ORDER BY date
        """

        try:
            df = self._query_with_duckdb(query, params)
            return set(df["date"].tolist()) if not df.empty else set()
        except Exception:
            # Table doesn't exist yet (first backfill) - return empty set
            # This is expected for initial backfills before any data exists
            return set()

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
                # Quote column name if it's a SQL reserved keyword (e.g., 'right')
                column = f'"{key}"' if key.lower() in ('right', 'left', 'order', 'group') else key
                where_clauses.append(f"{column} = ${param_name}")
                params[param_name] = value

        query = f"SELECT COUNT(*) as count FROM {table_name}"

        if where_clauses:
            query += " WHERE " + " AND ".join(where_clauses)

        df = self._query_with_duckdb(query, params)
        return int(df.iloc[0]["count"]) if not df.empty else 0
