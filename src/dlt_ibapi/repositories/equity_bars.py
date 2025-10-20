"""
Equity bars reader for querying stock historical data from DLT.

Queries data written by backfill_equity_bars DLT resource.
"""

from datetime import date
from typing import List, Optional, Set

import pandas as pd

from .base import BaseReader


class EquityBarsReader(BaseReader):
    """
    Reader for equity bars data written by DLT.

    Table: equity_bars_backfill
    Primary key: [symbol, bar_size, time]
    """

    def _get_table_name(self) -> str:
        """Table name for equity bars."""
        return "equity_bars_backfill"

    def get_present_dates_for_symbol(
        self,
        symbol: str,
        bar_size: str,
        start_date: date,
        end_date: date,
    ) -> Set[date]:
        """
        Get dates with data for a specific symbol.

        Used for gap detection in backfill operations.

        Args:
            symbol: Stock symbol
            bar_size: Bar size (e.g., "1 min", "1 day")
            start_date: Start of date range
            end_date: End of date range

        Returns:
            Set of dates with available bars
        """
        return self.get_present_dates(
            start_date=start_date,
            end_date=end_date,
            symbol=symbol.upper(),
            bar_size=bar_size,
        )

    def get_bars(
        self,
        symbol: str,
        bar_size: str,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
        limit: Optional[int] = None,
    ) -> pd.DataFrame:
        """
        Get historical bars for a specific symbol.

        Args:
            symbol: Stock symbol
            bar_size: Bar size (e.g., "1 min", "1 day")
            start_date: Filter start date (optional)
            end_date: Filter end date (optional)
            limit: Maximum rows to return

        Returns:
            DataFrame with OHLCV bars
        """
        table_name = self._get_table_name()
        full_table = f"{self.dataset_name}.{table_name}"

        where_clauses = [
            "symbol = $symbol",
            "bar_size = $bar_size"
        ]

        params = {
            "symbol": symbol.upper(),
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
            FROM {full_table}
            WHERE {where_sql}
            ORDER BY time
        """

        if limit:
            query += f" LIMIT {limit}"

        return self._execute_query(query, params)

    def get_date_range(
        self,
        symbol: str,
        bar_size: str,
    ) -> tuple[Optional[date], Optional[date]]:
        """
        Get the date range (min, max) of available data for a symbol.

        Args:
            symbol: Stock symbol
            bar_size: Bar size

        Returns:
            Tuple of (min_date, max_date) or (None, None) if no data
        """
        table_name = self._get_table_name()
        full_table = f"{self.dataset_name}.{table_name}"

        query = f"""
            SELECT
                MIN(DATE(time)) as min_date,
                MAX(DATE(time)) as max_date
            FROM {full_table}
            WHERE symbol = $symbol AND bar_size = $bar_size
        """

        params = {"symbol": symbol.upper(), "bar_size": bar_size}
        df = self._execute_query(query, params)

        if df.empty or pd.isna(df.iloc[0]["min_date"]):
            return None, None

        return df.iloc[0]["min_date"], df.iloc[0]["max_date"]

    def get_available_symbols(
        self,
        bar_size: Optional[str] = None,
    ) -> List[str]:
        """
        Get list of symbols with available data.

        Args:
            bar_size: Filter by bar size (optional)

        Returns:
            List of symbols
        """
        table_name = self._get_table_name()
        full_table = f"{self.dataset_name}.{table_name}"

        if bar_size:
            query = f"""
                SELECT DISTINCT symbol
                FROM {full_table}
                WHERE bar_size = $bar_size
                ORDER BY symbol
            """
            params = {"bar_size": bar_size}
        else:
            query = f"""
                SELECT DISTINCT symbol
                FROM {full_table}
                ORDER BY symbol
            """
            params = {}

        df = self._execute_query(query, params)
        return df["symbol"].tolist() if not df.empty else []

    def get_symbols_summary(
        self,
        bar_size: Optional[str] = None,
    ) -> pd.DataFrame:
        """
        Get summary statistics for all symbols.

        Args:
            bar_size: Filter by bar size (optional)

        Returns:
            DataFrame with symbol, bar_size, first_bar, last_bar, bar_count
        """
        table_name = self._get_table_name()
        full_table = f"{self.dataset_name}.{table_name}"

        where_clause = ""
        params = {}

        if bar_size:
            where_clause = "WHERE bar_size = $bar_size"
            params["bar_size"] = bar_size

        query = f"""
            SELECT
                symbol,
                bar_size,
                MIN(time) as first_bar,
                MAX(time) as last_bar,
                COUNT(*) as bar_count
            FROM {full_table}
            {where_clause}
            GROUP BY symbol, bar_size
            ORDER BY symbol, bar_size
        """

        return self._execute_query(query, params)
