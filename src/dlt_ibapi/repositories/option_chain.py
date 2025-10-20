"""
Option chain snapshot reader for querying option chain data from DLT.

Queries data written by snapshot_option_chain DLT resource.
"""

from datetime import date
from typing import List, Optional, Set

import pandas as pd

from .base import BaseReader


class OptionChainSnapshotReader(BaseReader):
    """
    Reader for option chain snapshot data written by DLT.

    Table: option_chain_snapshot
    Primary key: [underlying, as_of, expiry, strike, right]
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
    ) -> List[date]:
        """
        Get available expiration dates for a snapshot.

        Args:
            underlying: Underlying symbol
            as_of: Snapshot date
            min_dte: Minimum days to expiration filter
            max_dte: Maximum days to expiration filter

        Returns:
            List of expiration dates
        """
        table_name = self._get_table_name()
        full_table = f"{self.dataset_name}.{table_name}"

        where_clauses = [
            "underlying = $underlying",
            "DATE(as_of) = $as_of"
        ]
        params = {"underlying": underlying.upper(), "as_of": as_of}

        if min_dte is not None:
            where_clauses.append(f"DATE_DIFF('day', DATE(as_of), expiry) >= {min_dte}")

        if max_dte is not None:
            where_clauses.append(f"DATE_DIFF('day', DATE(as_of), expiry) <= {max_dte}")

        where_sql = " AND ".join(where_clauses)

        query = f"""
            SELECT DISTINCT expiry
            FROM {full_table}
            WHERE {where_sql}
            ORDER BY expiry
        """

        df = self._execute_query(query, params)
        return df["expiry"].tolist() if not df.empty else []

    def get_strikes_for_expiry(
        self,
        underlying: str,
        as_of: date,
        expiry: date,
        right: Optional[str] = None,
    ) -> List[float]:
        """
        Get available strikes for specific expiration.

        Args:
            underlying: Underlying symbol
            as_of: Snapshot date
            expiry: Expiration date
            right: Option type ("C" or "P"), None for both

        Returns:
            List of strike prices
        """
        table_name = self._get_table_name()
        full_table = f"{self.dataset_name}.{table_name}"

        where_clauses = [
            "underlying = $underlying",
            "DATE(as_of) = $as_of",
            "expiry = $expiry"
        ]
        params = {
            "underlying": underlying.upper(),
            "as_of": as_of,
            "expiry": expiry
        }

        if right:
            where_clauses.append("right = $right")
            params["right"] = right.upper()

        where_sql = " AND ".join(where_clauses)

        query = f"""
            SELECT DISTINCT strike
            FROM {full_table}
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
        right: Optional[str] = None,
    ) -> pd.DataFrame:
        """
        Get complete option chain for a specific date.

        Args:
            underlying: Underlying symbol
            as_of: Snapshot date
            min_dte: Minimum days to expiration
            max_dte: Maximum days to expiration
            right: Option type filter ("C" or "P")

        Returns:
            DataFrame with option chain
        """
        table_name = self._get_table_name()
        full_table = f"{self.dataset_name}.{table_name}"

        where_clauses = [
            "underlying = $underlying",
            "DATE(as_of) = $as_of"
        ]
        params = {"underlying": underlying.upper(), "as_of": as_of}

        if min_dte is not None:
            where_clauses.append(f"DATE_DIFF('day', DATE(as_of), expiry) >= {min_dte}")

        if max_dte is not None:
            where_clauses.append(f"DATE_DIFF('day', DATE(as_of), expiry) <= {max_dte}")

        if right:
            where_clauses.append("right = $right")
            params["right"] = right.upper()

        where_sql = " AND ".join(where_clauses)

        query = f"""
            SELECT *
            FROM {full_table}
            WHERE {where_sql}
            ORDER BY expiry, strike, right
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
