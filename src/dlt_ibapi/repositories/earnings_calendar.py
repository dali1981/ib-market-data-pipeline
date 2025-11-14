"""
Earnings calendar reader for querying earnings data from Parquet files.

Provides query API for earnings calendar data stored by the earnings DLT resource.
"""

from datetime import date, timedelta
from typing import List, Optional, Set
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.compute as pc

from .parquet_reader import ParquetReaderBase


class EarningsCalendarReader(ParquetReaderBase):
    """
    Reader for earnings calendar data from DLT Parquet files.

    Table: earnings_calendar
    Primary key: [symbol, earnings_date] or [symbol, earnings_date, snapshot_date]

    Example:
        >>> reader = EarningsCalendarReader(database_path="./data", dataset_name="earnings")
        >>>
        >>> # Get upcoming earnings for next 7 days
        >>> upcoming = reader.get_upcoming_earnings(days_ahead=7)
        >>> print(upcoming[['symbol', 'earnings_date', 'earnings_time']])
        >>>
        >>> # Get earnings for specific symbols
        >>> aapl_earnings = reader.get_earnings_for_symbol("AAPL")
    """

    def _get_table_name(self) -> str:
        """Table name for earnings calendar."""
        return "earnings_calendar"

    def get_upcoming_earnings(
        self,
        days_ahead: int = 7,
        from_date: Optional[date] = None,
        symbols: Optional[List[str]] = None,
        earnings_time: Optional[str] = None,
    ) -> pd.DataFrame:
        """
        Get earnings announcements in the next N days.

        Args:
            days_ahead: Number of days ahead to search (default: 7)
            from_date: Start date for search (default: today)
            symbols: Optional filter for specific symbols
            earnings_time: Optional filter ("PRE_MARKET", "AFTER_HOURS", "UNKNOWN")

        Returns:
            DataFrame with columns: symbol, earnings_date, earnings_time, company_name, etc.
            Sorted by earnings_date ascending

        Example:
            >>> # Get all earnings for next 14 days
            >>> reader.get_upcoming_earnings(days_ahead=14)
            >>>
            >>> # Get AAPL/MSFT earnings for next 30 days
            >>> reader.get_upcoming_earnings(
            ...     days_ahead=30,
            ...     symbols=["AAPL", "MSFT"]
            ... )
            >>>
            >>> # Get only pre-market earnings
            >>> reader.get_upcoming_earnings(
            ...     days_ahead=7,
            ...     earnings_time="PRE_MARKET"
            ... )
        """
        if from_date is None:
            from_date = date.today()

        end_date = from_date + timedelta(days=days_ahead)

        # Build filter expression (use pa.scalar for date comparisons)
        filter_expr = (
            (pc.field("earnings_date") >= pa.scalar(from_date, type=pa.date32())) &
            (pc.field("earnings_date") <= pa.scalar(end_date, type=pa.date32()))
        )

        if symbols:
            # Convert to uppercase for case-insensitive matching
            symbols_upper = [s.upper() for s in symbols]
            filter_expr = filter_expr & pc.field("symbol").isin(symbols_upper)

        if earnings_time:
            filter_expr = filter_expr & (pc.field("earnings_time") == earnings_time)

        # Query with PyArrow (efficient for scans)
        df = self._query_with_pyarrow(filters=filter_expr)

        if df.empty:
            return df

        # Sort by earnings_date
        df = df.sort_values("earnings_date").reset_index(drop=True)

        return df

    def get_earnings_for_symbol(
        self,
        symbol: str,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
    ) -> pd.DataFrame:
        """
        Get all earnings for a specific symbol.

        Args:
            symbol: Stock symbol
            start_date: Optional start date filter
            end_date: Optional end date filter

        Returns:
            DataFrame with earnings events for the symbol, sorted by date

        Example:
            >>> # All AAPL earnings
            >>> reader.get_earnings_for_symbol("AAPL")
            >>>
            >>> # AAPL earnings in 2025
            >>> reader.get_earnings_for_symbol(
            ...     "AAPL",
            ...     start_date=date(2025, 1, 1),
            ...     end_date=date(2025, 12, 31),
            ... )
        """
        symbol_upper = symbol.upper()

        # Build filter
        filter_expr = pc.field("symbol") == symbol_upper

        if start_date:
            filter_expr = filter_expr & (pc.field("earnings_date") >= pa.scalar(start_date, type=pa.date32()))

        if end_date:
            filter_expr = filter_expr & (pc.field("earnings_date") <= pa.scalar(end_date, type=pa.date32()))

        df = self._query_with_pyarrow(filters=filter_expr)

        if df.empty:
            return df

        df = df.sort_values("earnings_date").reset_index(drop=True)
        return df

    def get_earnings_on_date(
        self,
        earnings_date: date,
        symbols: Optional[List[str]] = None,
    ) -> pd.DataFrame:
        """
        Get all earnings announcements on a specific date.

        Args:
            earnings_date: Date to check for earnings
            symbols: Optional filter for specific symbols

        Returns:
            DataFrame with all earnings on that date

        Example:
            >>> # All earnings on November 15, 2025
            >>> reader.get_earnings_on_date(date(2025, 11, 15))
            >>>
            >>> # Check if AAPL has earnings on specific date
            >>> aapl_earnings = reader.get_earnings_on_date(
            ...     date(2025, 11, 15),
            ...     symbols=["AAPL"]
            ... )
            >>> has_earnings = not aapl_earnings.empty
        """
        filter_expr = pc.field("earnings_date") == pa.scalar(earnings_date, type=pa.date32())

        if symbols:
            symbols_upper = [s.upper() for s in symbols]
            filter_expr = filter_expr & pc.field("symbol").isin(symbols_upper)

        df = self._query_with_pyarrow(filters=filter_expr)
        return df

    def get_available_symbols(self) -> List[str]:
        """
        Get list of all symbols with earnings data.

        Returns:
            Sorted list of unique symbols

        Example:
            >>> symbols = reader.get_available_symbols()
            >>> print(f"Earnings data for {len(symbols)} symbols")
        """
        query = f"""
            SELECT DISTINCT symbol
            FROM {self._get_table_name()}
            ORDER BY symbol
        """

        df = self._query_with_duckdb(query)

        if df.empty:
            return []

        return df["symbol"].tolist()

    def get_date_range(self) -> tuple[Optional[date], Optional[date]]:
        """
        Get the date range of available earnings data.

        Returns:
            Tuple of (min_date, max_date) or (None, None) if no data

        Example:
            >>> min_date, max_date = reader.get_date_range()
            >>> print(f"Earnings data from {min_date} to {max_date}")
        """
        query = f"""
            SELECT
                MIN(earnings_date) as min_date,
                MAX(earnings_date) as max_date
            FROM {self._get_table_name()}
        """

        df = self._query_with_duckdb(query)

        if df.empty or df.iloc[0]["min_date"] is None:
            return (None, None)

        # Convert to date objects
        min_date = pd.to_datetime(df.iloc[0]["min_date"]).date()
        max_date = pd.to_datetime(df.iloc[0]["max_date"]).date()

        return (min_date, max_date)

    def count_earnings(
        self,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
    ) -> int:
        """
        Count total earnings events in date range.

        Args:
            start_date: Optional start date
            end_date: Optional end date

        Returns:
            Count of earnings events

        Example:
            >>> # Total earnings in database
            >>> total = reader.count_earnings()
            >>>
            >>> # Earnings in November 2025
            >>> count = reader.count_earnings(
            ...     start_date=date(2025, 11, 1),
            ...     end_date=date(2025, 11, 30),
            ... )
        """
        where_clauses = []
        params = {}

        if start_date:
            where_clauses.append("earnings_date >= $start_date")
            params["start_date"] = start_date

        if end_date:
            where_clauses.append("earnings_date <= $end_date")
            params["end_date"] = end_date

        where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""

        query = f"""
            SELECT COUNT(*) as count
            FROM {self._get_table_name()}
            {where_sql}
        """

        df = self._query_with_duckdb(query, params)

        if df.empty:
            return 0

        return int(df.iloc[0]["count"])
