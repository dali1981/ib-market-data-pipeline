"""
Selected option contracts reader for querying contracts selected by delta strategies.

Queries data written by select_option_contracts_resource DLT resource.

Schema: underlying, expiry, strike, right, conid, local_symbol, exchange,
        trading_class, multiplier, strategy, delta, reason, spot_price, snapshot_date
"""

from datetime import date
from typing import List, Optional

import pandas as pd

from .parquet_reader import ParquetReaderBase


class SelectedContractsReader(ParquetReaderBase):
    """
    Reader for selected option contracts written by DLT.

    Table: selected_option_contracts
    Schema: Stores option contracts selected by delta strategies with IB resolution
    Primary key: [underlying, expiry, strike, right, strategy]
    """

    def _get_table_name(self) -> str:
        """Table name for selected contracts."""
        return "selected_option_contracts"

    def _should_use_duckdb(self, query_type: str) -> bool:
        """Always use DuckDB for selected contracts (small to medium datasets)."""
        return True

    def get_all_contracts(self, snapshot_date: Optional[date] = None) -> pd.DataFrame:
        """
        Get all selected contracts, optionally filtered by snapshot date.

        Args:
            snapshot_date: Optional snapshot date filter

        Returns:
            DataFrame with all selected contracts
        """
        table_name = self._get_table_name()

        where_clauses = []
        params = {}

        if snapshot_date:
            where_clauses.append("DATE(snapshot_date) = $snapshot_date")
            params["snapshot_date"] = snapshot_date

        where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""

        query = f"""
            SELECT *
            FROM {table_name}
            {where_sql}
            ORDER BY underlying, expiry, strike, right
        """

        return self._query_with_duckdb(query, params)

    def get_contracts_for_symbol(
        self,
        underlying: str,
        snapshot_date: Optional[date] = None,
        strategy: Optional[str] = None,
    ) -> pd.DataFrame:
        """
        Get selected contracts for a specific underlying symbol.

        Args:
            underlying: Underlying symbol
            snapshot_date: Optional snapshot date filter
            strategy: Optional strategy filter ("closest_match" or "black_scholes")

        Returns:
            DataFrame with selected contracts for the symbol
        """
        table_name = self._get_table_name()

        where_clauses = ["underlying = $underlying"]
        params = {"underlying": underlying.upper()}

        if snapshot_date:
            where_clauses.append("DATE(snapshot_date) = $snapshot_date")
            params["snapshot_date"] = snapshot_date

        if strategy:
            where_clauses.append("strategy = $strategy")
            params["strategy"] = strategy

        where_sql = " AND ".join(where_clauses)

        query = f"""
            SELECT *
            FROM {table_name}
            WHERE {where_sql}
            ORDER BY expiry, strike, right
        """

        return self._query_with_duckdb(query, params)

    def get_contracts_by_strategy(
        self,
        strategy: str,
        snapshot_date: Optional[date] = None,
    ) -> pd.DataFrame:
        """
        Get contracts selected by a specific strategy.

        Args:
            strategy: Strategy name ("closest_match" or "black_scholes")
            snapshot_date: Optional snapshot date filter

        Returns:
            DataFrame with contracts for the strategy
        """
        table_name = self._get_table_name()

        where_clauses = ["strategy = $strategy"]
        params = {"strategy": strategy}

        if snapshot_date:
            where_clauses.append("DATE(snapshot_date) = $snapshot_date")
            params["snapshot_date"] = snapshot_date

        where_sql = " AND ".join(where_clauses)

        query = f"""
            SELECT *
            FROM {table_name}
            WHERE {where_sql}
            ORDER BY underlying, expiry, strike, right
        """

        return self._query_with_duckdb(query, params)

    def get_contracts_for_expiry(
        self,
        underlying: str,
        expiry: date,
        snapshot_date: Optional[date] = None,
    ) -> pd.DataFrame:
        """
        Get selected contracts for a specific expiration.

        Args:
            underlying: Underlying symbol
            expiry: Expiration date
            snapshot_date: Optional snapshot date filter

        Returns:
            DataFrame with contracts for the expiration
        """
        table_name = self._get_table_name()

        where_clauses = [
            "underlying = $underlying",
            "DATE(expiry) = $expiry"
        ]
        params = {
            "underlying": underlying.upper(),
            "expiry": expiry
        }

        if snapshot_date:
            where_clauses.append("DATE(snapshot_date) = $snapshot_date")
            params["snapshot_date"] = snapshot_date

        where_sql = " AND ".join(where_clauses)

        query = f"""
            SELECT *
            FROM {table_name}
            WHERE {where_sql}
            ORDER BY strike, right, strategy
        """

        return self._query_with_duckdb(query, params)

    def get_available_symbols(self, snapshot_date: Optional[date] = None) -> List[str]:
        """
        Get list of available underlying symbols.

        Args:
            snapshot_date: Optional snapshot date filter

        Returns:
            List of unique underlying symbols
        """
        table_name = self._get_table_name()

        where_clauses = []
        params = {}

        if snapshot_date:
            where_clauses.append("DATE(snapshot_date) = $snapshot_date")
            params["snapshot_date"] = snapshot_date

        where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""

        query = f"""
            SELECT DISTINCT underlying
            FROM {table_name}
            {where_sql}
            ORDER BY underlying
        """

        df = self._query_with_duckdb(query, params)
        return df["underlying"].tolist() if not df.empty else []

    def get_contract_count_by_strategy(
        self,
        snapshot_date: Optional[date] = None,
    ) -> pd.DataFrame:
        """
        Get count of contracts by strategy.

        Args:
            snapshot_date: Optional snapshot date filter

        Returns:
            DataFrame with strategy and count columns
        """
        table_name = self._get_table_name()

        where_clauses = []
        params = {}

        if snapshot_date:
            where_clauses.append("DATE(snapshot_date) = $snapshot_date")
            params["snapshot_date"] = snapshot_date

        where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""

        query = f"""
            SELECT strategy, COUNT(*) as count
            FROM {table_name}
            {where_sql}
            GROUP BY strategy
            ORDER BY strategy
        """

        return self._query_with_duckdb(query, params)
