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

            # Note: 'date' column is stored as string in format 'YYYYMMDD X'
            # where X is a flag (0 or 1), so we compare against 'YYYYMMDD'
            if start_date:
                date_str = start_date.strftime('%Y%m%d')
                filter_expr = filter_expr & (pc.field("date") >= date_str)

            if end_date:
                date_str = end_date.strftime('%Y%m%d')
                filter_expr = filter_expr & (pc.field("date") <= date_str)

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
                "\"right\" = $right",  # Quote 'right' as it's a SQL reserved keyword
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
                # Convert date to string for comparison with string date column
                where_clauses.append("date >= $start_date")
                params["start_date"] = start_date.strftime('%Y%m%d')

            if end_date:
                # Convert date to string for comparison with string date column
                where_clauses.append("date <= $end_date")
                params["end_date"] = end_date.strftime('%Y%m%d')

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
                "right",
                bar_size,
                MIN(time) as first_bar,
                MAX(time) as last_bar,
                COUNT(*) as bar_count
            FROM {table_name}
            WHERE {where_sql}
            GROUP BY underlying, expiry, strike, "right", bar_size
            ORDER BY expiry, strike, "right"
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

    def get_available_symbols(self) -> List[str]:
        """
        Get list of underlying symbols with option data.
        Uses DuckDB for efficient metadata query.

        Returns:
            List of underlying symbols sorted alphabetically
        """
        table_name = self._get_table_name()

        query = f"""
            SELECT DISTINCT underlying
            FROM {table_name}
            ORDER BY underlying
        """

        df = self._query_with_duckdb(query, {})
        return df["underlying"].tolist() if not df.empty else []

    def get_expirations_for_contract(
        self,
        underlying: str,
        strike: float,
        option_type: str,
        bar_size: str = "1 hour",
    ) -> List[date]:
        """
        Get available expirations for specific contract parameters.

        Args:
            underlying: Underlying symbol
            strike: Strike price
            option_type: 'C' for calls, 'P' for puts
            bar_size: Bar size to filter (default "1 hour")

        Returns:
            List of expiration dates sorted chronologically
        """
        table_name = self._get_table_name()

        query = f"""
            SELECT DISTINCT expiry
            FROM {table_name}
            WHERE underlying = $underlying
              AND strike = $strike
              AND "right" = $option_type
              AND bar_size = $bar_size
            ORDER BY expiry
        """

        params = {
            "underlying": underlying.upper(),
            "strike": strike,
            "option_type": option_type.upper(),
            "bar_size": bar_size,
        }

        df = self._query_with_duckdb(query, params)

        if df.empty:
            return []

        # Convert to date objects (in case DuckDB returns timestamps)
        expirations = []
        for exp in df["expiry"].tolist():
            if isinstance(exp, pd.Timestamp):
                expirations.append(exp.date())
            elif isinstance(exp, date):
                expirations.append(exp)
            else:
                # Try to convert to datetime then extract date
                expirations.append(pd.to_datetime(exp).date())

        return expirations

    def load_option_leg_bars(
        self,
        underlying: str,
        expiry: date,
        strike: float,
        option_type: str,
        bar_size: str = "1 hour",
    ) -> Optional[pd.DataFrame]:
        """
        Load bars for a single option leg with parsed datetime column.

        This is a convenience method that wraps get_bars() and adds
        datetime parsing for notebooks/strategies.

        Args:
            underlying: Underlying symbol
            expiry: Option expiration date
            strike: Strike price
            option_type: 'C' for calls, 'P' for puts
            bar_size: Bar size (default "1 hour")

        Returns:
            DataFrame with 'datetime' and price columns, or None if no data

        Example:
            >>> reader = OptionBarsReader(database_path='./data', dataset_name='options')
            >>> bars = reader.load_option_leg_bars('AAPL', date(2025, 11, 21), 150.0, 'C')
            >>> bars[['datetime', 'close']].head()
        """
        df = self.get_bars(
            underlying=underlying,
            expiry=expiry,
            strike=strike,
            right=option_type,
            bar_size=bar_size,
            use_pyarrow=False,  # Use DuckDB for parsing
        )

        if df.empty:
            return None

        # Parse datetime from time column (format varies by data source)
        # Typical format: "YYYYMMDD HH:MM:SS" or "YYYYMMDD HH:MM:SS US/Eastern"
        if 'time' in df.columns:
            # Strip timezone suffix if present
            time_str = df['time'].astype(str).str.replace(r' US/Eastern$', '', regex=True)
            df['datetime'] = pd.to_datetime(time_str, format='%Y%m%d %H:%M:%S')

        return df[['datetime', 'open', 'high', 'low', 'close', 'volume']].sort_values('datetime')
