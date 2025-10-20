"""
Option chain snapshot reader for querying option chain data from DLT.

Queries data written by snapshot_option_chain DLT resource.

Schema: underlying, underlying_conid, exchange, trading_class,
        multiplier, expirations (array), strikes (array),
        expiration_count, strike_count, as_of, captured_at
"""

from datetime import date, datetime
from typing import List, Optional, Set

import pandas as pd

from .base import BaseReader


class OptionChainSnapshotReader(BaseReader):
    """
    Reader for option chain snapshot data written by DLT.

    Table: option_chain_snapshot
    Schema: Stores option chain parameters per exchange with expirations
            and strikes as arrays
    Primary key: [underlying, as_of, exchange, trading_class]
    """

    def _get_table_name(self) -> str:
        """Table name for option chain snapshots."""
        return "option_chain_snapshot"

    def get_available_expirations(
        self,
        underlying: str,
        as_of: date,
        min_dte: Optional[int] = None,
        max_dte: Optional[int] = None,
        exchange: Optional[str] = None,
    ) -> List[date]:
        """
        Get available expiration dates for a snapshot.

        Args:
            underlying: Underlying symbol
            as_of: Snapshot date
            min_dte: Minimum days to expiration filter
            max_dte: Maximum days to expiration filter
            exchange: Filter by specific exchange (default: use all exchanges)

        Returns:
            List of expiration dates sorted ascending
        """
        table_name = self._get_table_name()
        full_table = f"{self.dataset_name}.{table_name}"
        exp_table = f"{self.dataset_name}.{table_name}__expirations"

        where_clauses = [
            "p.underlying = $underlying",
            "DATE(p.as_of) = $as_of"
        ]
        params = {"underlying": underlying.upper(), "as_of": as_of}

        if exchange:
            where_clauses.append("p.exchange = $exchange")
            params["exchange"] = exchange.upper()

        where_sql = " AND ".join(where_clauses)

        # Join with child table for expirations
        query = f"""
            SELECT DISTINCT e.value as exp_str
            FROM {full_table} p
            JOIN {exp_table} e ON p._dlt_id = e._dlt_parent_id
            WHERE {where_sql}
        """

        df = self._execute_query(query, params)

        if df.empty:
            return []

        # Parse expiration strings (YYYYMMDD) to dates and filter by DTE
        expirations = []
        for exp_str in df["exp_str"].tolist():
            try:
                exp_date = datetime.strptime(str(exp_str), "%Y%m%d").date()
                dte = (exp_date - as_of).days

                if min_dte is not None and dte < min_dte:
                    continue
                if max_dte is not None and dte > max_dte:
                    continue

                expirations.append(exp_date)
            except Exception:
                continue

        return sorted(set(expirations))

    def get_strikes_for_expiry(
        self,
        underlying: str,
        as_of: date,
        expiry: date,
        exchange: Optional[str] = None,
    ) -> List[float]:
        """
        Get available strikes for a snapshot.

        Note: The snapshot stores strikes at the chain level (all expirations
        share the same strikes). This method returns all strikes.

        Args:
            underlying: Underlying symbol
            as_of: Snapshot date
            expiry: Expiration date (for compatibility, not used in query)
            exchange: Filter by specific exchange

        Returns:
            List of strike prices sorted ascending
        """
        table_name = self._get_table_name()
        full_table = f"{self.dataset_name}.{table_name}"
        strike_table = f"{self.dataset_name}.{table_name}__strikes"

        where_clauses = [
            "p.underlying = $underlying",
            "DATE(p.as_of) = $as_of"
        ]
        params = {"underlying": underlying.upper(), "as_of": as_of}

        if exchange:
            where_clauses.append("p.exchange = $exchange")
            params["exchange"] = exchange.upper()

        where_sql = " AND ".join(where_clauses)

        # Join with child table for strikes
        query = f"""
            SELECT DISTINCT s.value as strike
            FROM {full_table} p
            JOIN {strike_table} s ON p._dlt_id = s._dlt_parent_id
            WHERE {where_sql}
            ORDER BY strike
        """

        df = self._execute_query(query, params)
        return df["strike"].tolist() if not df.empty else []

    def get_chain_for_date(
        self,
        underlying: str,
        as_of: date,
        min_dte: Optional[int] = None,
        max_dte: Optional[int] = None,
        exchange: Optional[str] = None,
    ) -> pd.DataFrame:
        """
        Get complete option chain snapshot for a specific date.

        Returns snapshot records from the parent table (without child arrays).
        Use get_available_expirations() and get_strikes_for_expiry() to get
        the actual expirations and strikes lists.

        Args:
            underlying: Underlying symbol
            as_of: Snapshot date
            min_dte: Minimum days to expiration (informational only, not filtered)
            max_dte: Maximum days to expiration (informational only, not filtered)
            exchange: Filter by specific exchange

        Returns:
            DataFrame with option chain snapshot records (parent table only)
        """
        table_name = self._get_table_name()
        full_table = f"{self.dataset_name}.{table_name}"

        where_clauses = [
            "underlying = $underlying",
            "DATE(as_of) = $as_of"
        ]
        params = {"underlying": underlying.upper(), "as_of": as_of}

        if exchange:
            where_clauses.append("exchange = $exchange")
            params["exchange"] = exchange.upper()

        where_sql = " AND ".join(where_clauses)

        query = f"""
            SELECT *
            FROM {full_table}
            WHERE {where_sql}
            ORDER BY exchange, trading_class
        """

        return self._execute_query(query, params)

    def get_available_snapshots(self, underlying: str) -> Set[date]:
        """
        Get all snapshot dates available for a symbol.

        Args:
            underlying: Underlying symbol

        Returns:
            Set of snapshot dates
        """
        table_name = self._get_table_name()
        full_table = f"{self.dataset_name}.{table_name}"

        query = f"""
            SELECT DISTINCT DATE(as_of) as snapshot_date
            FROM {full_table}
            WHERE underlying = $underlying
            ORDER BY snapshot_date
        """

        df = self._execute_query(query, {"underlying": underlying.upper()})
        return set(df["snapshot_date"].tolist()) if not df.empty else set()

    def get_exchanges_for_snapshot(
        self,
        underlying: str,
        as_of: date,
    ) -> List[str]:
        """
        Get all exchanges available for a snapshot.

        Args:
            underlying: Underlying symbol
            as_of: Snapshot date

        Returns:
            List of exchange names
        """
        table_name = self._get_table_name()
        full_table = f"{self.dataset_name}.{table_name}"

        query = f"""
            SELECT DISTINCT exchange
            FROM {full_table}
            WHERE underlying = $underlying
            AND DATE(as_of) = $as_of
            ORDER BY exchange
        """

        params = {"underlying": underlying.upper(), "as_of": as_of}
        df = self._execute_query(query, params)
        return df["exchange"].tolist() if not df.empty else []
