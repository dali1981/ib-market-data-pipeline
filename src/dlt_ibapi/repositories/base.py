"""
Base reader repository for querying DLT destination databases.

Unlike earnings_ibapi which writes directly to Parquet, dlt-ibapi uses DLT for all writes.
Repositories are read-only SQL wrappers that query DLT destinations (DuckDB, Postgres, etc.).
"""

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Union
from datetime import date

import duckdb
import pandas as pd


class BaseReader(ABC):
    """
    Abstract base class for DLT destination readers.

    Provides SQL query interface for reading data written by DLT resources.
    Supports DuckDB (default), Postgres, Snowflake, or any DLT destination.
    """

    def __init__(
        self,
        database_path: Optional[Union[str, Path]] = None,
        dataset_name: str = "stocks",
        destination_type: str = "duckdb",
    ):
        """
        Initialize reader for DLT destination.

        Args:
            database_path: Path to database file (for DuckDB) or connection string
            dataset_name: DLT dataset name (schema in SQL databases)
            destination_type: Type of destination ("duckdb", "postgres", "snowflake")
        """
        self.database_path = str(database_path) if database_path else None
        self.dataset_name = dataset_name
        self.destination_type = destination_type

    @abstractmethod
    def _get_table_name(self) -> str:
        """Get the name of the table/view to query."""
        pass

    def _get_connection(self):
        """
        Get database connection based on destination type.

        Returns:
            Database connection object
        """
        if self.destination_type == "duckdb":
            if not self.database_path:
                raise ValueError("database_path required for DuckDB")
            return duckdb.connect(self.database_path, read_only=True)
        elif self.destination_type == "postgres":
            raise NotImplementedError("Postgres support coming soon")
        elif self.destination_type == "snowflake":
            raise NotImplementedError("Snowflake support coming soon")
        else:
            raise ValueError(f"Unsupported destination type: {self.destination_type}")

    def _execute_query(self, query: str, params: Optional[Dict[str, Any]] = None) -> pd.DataFrame:
        """
        Execute SQL query and return results as DataFrame.

        Args:
            query: SQL query string
            params: Optional query parameters (for parameterized queries)

        Returns:
            Query results as DataFrame
        """
        conn = self._get_connection()
        try:
            if params:
                # DuckDB supports parameterized queries
                result = conn.execute(query, params).df()
            else:
                result = conn.execute(query).df()
            return result
        finally:
            conn.close()

    def query(self, sql: str, params: Optional[Dict[str, Any]] = None) -> pd.DataFrame:
        """
        Execute custom SQL query.

        Args:
            sql: SQL query string
            params: Optional query parameters

        Returns:
            Query results as DataFrame
        """
        return self._execute_query(sql, params)

    def get_present_dates(
        self,
        start_date: date,
        end_date: date,
        **filters
    ) -> Set[date]:
        """
        Get set of dates with data in the specified range.

        Used for gap detection in backfill operations.

        Args:
            start_date: Start date (inclusive)
            end_date: End date (inclusive)
            **filters: Additional filters (symbol, bar_size, etc.)

        Returns:
            Set of dates with available data
        """
        table_name = self._get_table_name()
        full_table = f"{self.dataset_name}.{table_name}"

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
            FROM {full_table}
            WHERE {where_sql}
            ORDER BY date
        """

        df = self._execute_query(query, params)
        return set(df["date"].tolist()) if not df.empty else set()

    def load(
        self,
        columns: Optional[List[str]] = None,
        limit: Optional[int] = None,
        **filters
    ) -> pd.DataFrame:
        """
        Load data from table with optional filtering.

        Args:
            columns: Columns to select (None = all)
            limit: Maximum rows to return
            **filters: Column filters (e.g., symbol="AAPL", start_date=date(2024,1,1))

        Returns:
            Query results as DataFrame
        """
        table_name = self._get_table_name()
        full_table = f"{self.dataset_name}.{table_name}"

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
        query = f"SELECT {select_clause} FROM {full_table}"

        if where_clauses:
            query += " WHERE " + " AND ".join(where_clauses)

        if limit:
            query += f" LIMIT {limit}"

        return self._execute_query(query, params)

    def count(self, **filters) -> int:
        """
        Count rows matching filters.

        Args:
            **filters: Column filters

        Returns:
            Row count
        """
        table_name = self._get_table_name()
        full_table = f"{self.dataset_name}.{table_name}"

        # Build WHERE clause
        where_clauses = []
        params = {}

        for key, value in filters.items():
            if value is not None:
                param_name = f"filter_{key}"
                where_clauses.append(f"{key} = ${param_name}")
                params[param_name] = value

        query = f"SELECT COUNT(*) as count FROM {full_table}"

        if where_clauses:
            query += " WHERE " + " AND ".join(where_clauses)

        df = self._execute_query(query, params)
        return int(df.iloc[0]["count"]) if not df.empty else 0
