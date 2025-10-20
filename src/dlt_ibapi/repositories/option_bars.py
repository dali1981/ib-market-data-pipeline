"""
Option bars reader for querying option historical data from DLT.

Queries data written by backfill_option_bars DLT resource.
"""

from datetime import date
from typing import List, Optional, Set

import pandas as pd

from .base import BaseReader


class OptionBarsReader(BaseReader):
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
    ) -> pd.DataFrame:
        """
        Get historical bars for specific option contract.

        Args:
            underlying: Underlying symbol
            expiry: Option expiration date
            strike: Strike price
            right: "C" or "P"
            bar_size: Bar size (e.g., "1 min")
            start_date: Filter start date (optional)
            end_date: Filter end date (optional)
            limit: Maximum rows to return

        Returns:
            DataFrame with OHLCV bars
        """
        table_name = self._get_table_name()
        full_table = f"{self.dataset_name}.{table_name}"

        where_clauses = [
            "underlying = $underlying",
            "expiry = $expiry",
            "strike = $strike",
            "right = $right",
            "bar_size = $bar_size"
        ]

        params = {
            "underlying": underlying.upper(),
            "expiry": expiry,
            "strike": strike,
            "right": right.upper(),
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

    def get_contracts_for_underlying(
        self,
        underlying: str,
        bar_size: Optional[str] = None,
        min_expiry: Optional[date] = None,
        max_expiry: Optional[date] = None,
    ) -> pd.DataFrame:
        """
        Get list of option contracts available for an underlying.

        Args:
            underlying: Underlying symbol
            bar_size: Filter by bar size (optional)
            min_expiry: Minimum expiration date (optional)
            max_expiry: Maximum expiration date (optional)

        Returns:
            DataFrame with unique contracts (expiry, strike, right)
        """
        table_name = self._get_table_name()
        full_table = f"{self.dataset_name}.{table_name}"

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
            FROM {full_table}
            WHERE {where_sql}
            GROUP BY underlying, expiry, strike, right, bar_size
            ORDER BY expiry, strike, right
        """

        return self._execute_query(query, params)

    def get_available_expirations(
        self,
        underlying: str,
        bar_size: Optional[str] = None,
    ) -> List[date]:
        """
        Get available expiration dates for an underlying.

        Args:
            underlying: Underlying symbol
            bar_size: Filter by bar size (optional)

        Returns:
            List of expiration dates
        """
        table_name = self._get_table_name()
        full_table = f"{self.dataset_name}.{table_name}"

        where_clauses = ["underlying = $underlying"]
        params = {"underlying": underlying.upper()}

        if bar_size:
            where_clauses.append("bar_size = $bar_size")
            params["bar_size"] = bar_size

        where_sql = " AND ".join(where_clauses)

        query = f"""
            SELECT DISTINCT expiry
            FROM {full_table}
            WHERE {where_sql}
            ORDER BY expiry
        """

        df = self._execute_query(query, params)
        return df["expiry"].tolist() if not df.empty else []
