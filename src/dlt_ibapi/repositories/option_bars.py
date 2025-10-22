"""
Option bars reader for querying option historical data from DLT.

Queries data written by backfill_option_bars DLT resource.
Now supports Parquet files with hybrid query routing (DuckDB + PyArrow).
"""

from datetime import date
from typing import List, Optional, Set

import pandas as pd
import pyarrow as pa
import pyarrow.compute as pc

from .parquet_reader import ParquetReaderBase


class OptionBarsReader(ParquetReaderBase):
    """
    Reader for option bars data written by DLT.

    Table: option_bars_backfill
    Primary key: [underlying, expiry, strike, right, bar_size, time]
    """

    def _get_table_name(self) -> str:
        """Table name for option bars."""
        return "option_bars_backfill"

    def get_present_dates_for_contract(
        self,
        underlying: str,
        expiry: date,
        strike: float,
        right: str,
        bar_size: str,
        start_date: date,
        end_date: date,
    ) -> Set[date]:
        """
        Get dates with data for a specific option contract.

        Args:
            underlying: Underlying symbol
            expiry: Option expiration date
            strike: Strike price
            right: "C" or "P"
            bar_size: Bar size (e.g., "1 min")
            start_date: Start of date range
            end_date: End of date range

        Returns:
            Set of dates with available bars
        """
        return self.get_present_dates(
            start_date=start_date,
            end_date=end_date,
            underlying=underlying.upper(),
            expiry=expiry,
            strike=strike,
            right=right.upper(),
            bar_size=bar_size,
        )

    def get_bars(
        self,
        underlying: str,
        expiry: date,
        strike: float,
        right: str,
        bar_size: str,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
        limit: Optional[int] = None,
        use_pyarrow: bool = True,  # Default to PyArrow for large scans
    ) -> pd.DataFrame:
        """
        Get historical bars for specific option contract.

        Uses PyArrow by default for efficient large scans with predicate pushdown.
        Falls back to DuckDB for small queries or custom SQL needs.

        Args:
            underlying: Underlying symbol
            expiry: Option expiration date
            strike: Strike price
            right: "C" or "P"
            bar_size: Bar size (e.g., "1 min")
            start_date: Filter start date (optional)
            end_date: Filter end date (optional)
            limit: Maximum rows to return
            use_pyarrow: Use PyArrow for query (default True)

        Returns:
            DataFrame with OHLCV bars, sorted by time
        """
        underlying_upper = underlying.upper()
        right_upper = right.upper()

        if use_pyarrow:
            # Use PyArrow with predicate pushdown
            # Note: Use pa.scalar() to ensure proper type matching for date fields
            filter_expr = (
                (pc.field("underlying") == underlying_upper) &
                (pc.field("expiry") == pa.scalar(expiry)) &
                (pc.field("strike") == strike) &
                (pc.field("right") == right_upper) &
                (pc.field("bar_size") == bar_size)
            )

            if start_date:
                filter_expr = filter_expr & (pc.field("date") >= pa.scalar(start_date))

            if end_date:
                filter_expr = filter_expr & (pc.field("date") <= pa.scalar(end_date))

            df = self._query_with_pyarrow(
                columns=None,  # Select all columns
                filters=filter_expr,
                limit=limit
            )

            # Sort by time (PyArrow doesn't guarantee order)
            if not df.empty:
                df = df.sort_values("time").reset_index(drop=True)

            return df
        else:
            # Use DuckDB for custom queries
            table_name = self._get_table_name()

            where_clauses = [
                "underlying = $underlying",
                "expiry = $expiry",
                "strike = $strike",
                "right = $right",
                "bar_size = $bar_size"
            ]

            params = {
                "underlying": underlying_upper,
                "expiry": expiry,
                "strike": strike,
                "right": right_upper,
                "bar_size": bar_size,
            }

            if start_date:
                where_clauses.append("DATE(time) >= $start_date")
                params["start_date"] = start_date

            if end_date:
                where_clauses.append("DATE(time) <= $end_date")
                params["end_date"] = end_date

            where_sql = " AND ".join(where_clauses)

            query = f"""
                SELECT *
                FROM {table_name}
                WHERE {where_sql}
                ORDER BY time
            """

            if limit:
                query += f" LIMIT {limit}"

            return self._query_with_duckdb(query, params)

    def get_contracts_for_underlying(
        self,
        underlying: str,
        bar_size: Optional[str] = None,
        min_expiry: Optional[date] = None,
        max_expiry: Optional[date] = None,
    ) -> pd.DataFrame:
        """
        Get list of option contracts available for an underlying.
        Uses DuckDB for efficient aggregation.

        Args:
            underlying: Underlying symbol
            bar_size: Filter by bar size (optional)
            min_expiry: Minimum expiration date (optional)
            max_expiry: Maximum expiration date (optional)

        Returns:
            DataFrame with unique contracts (expiry, strike, right)
        """
        table_name = self._get_table_name()

        where_clauses = ["underlying = $underlying"]
        params = {"underlying": underlying.upper()}

        if bar_size:
            where_clauses.append("bar_size = $bar_size")
            params["bar_size"] = bar_size

        if min_expiry:
            where_clauses.append("expiry >= $min_expiry")
            params["min_expiry"] = min_expiry

        if max_expiry:
            where_clauses.append("expiry <= $max_expiry")
            params["max_expiry"] = max_expiry

        where_sql = " AND ".join(where_clauses)

        query = f"""
            SELECT DISTINCT
                underlying,
                expiry,
                strike,
                right,
                bar_size,
                MIN(time) as first_bar,
                MAX(time) as last_bar,
                COUNT(*) as bar_count
            FROM {table_name}
            WHERE {where_sql}
            GROUP BY underlying, expiry, strike, right, bar_size
            ORDER BY expiry, strike, right
        """

        return self._query_with_duckdb(query, params)

    def get_available_expirations(
        self,
        underlying: str,
        bar_size: Optional[str] = None,
    ) -> List[date]:
        """
        Get available expiration dates for an underlying.
        Uses DuckDB for efficient metadata query.

        Args:
            underlying: Underlying symbol
            bar_size: Filter by bar size (optional)

        Returns:
            List of expiration dates
        """
        table_name = self._get_table_name()

        where_clauses = ["underlying = $underlying"]
        params = {"underlying": underlying.upper()}

        if bar_size:
            where_clauses.append("bar_size = $bar_size")
            params["bar_size"] = bar_size

        where_sql = " AND ".join(where_clauses)

        query = f"""
            SELECT DISTINCT expiry
            FROM {table_name}
            WHERE {where_sql}
            ORDER BY expiry
        """

        df = self._query_with_duckdb(query, params)
        return df["expiry"].tolist() if not df.empty else []
