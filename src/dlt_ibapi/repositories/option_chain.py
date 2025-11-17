"""
Option chain snapshot reader for querying option chain data from DLT.

Queries data written by snapshot_option_chain DLT resource.
Now supports Parquet files using DuckDB for all queries (snapshots are small).

Schema: underlying, underlying_conid, exchange, trading_class,
        multiplier, expirations (array), strikes (array),
        expiration_count, strike_count, as_of, captured_at
"""

from datetime import date, datetime
from typing import List, Optional, Set

import pandas as pd

from .parquet_reader import ParquetReaderBase


class OptionChainSnapshotReader(ParquetReaderBase):
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

    def _should_use_duckdb(self, query_type: str) -> bool:
        """Always use DuckDB for option chain snapshots (small datasets)."""
        return True  # Snapshots are small, always use DuckDB

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
            as_of: Snapshot date (date or pandas Timestamp)
            min_dte: Minimum days to expiration filter
            max_dte: Maximum days to expiration filter
            exchange: Filter by specific exchange (default: use all exchanges)

        Returns:
            List of expiration dates sorted ascending
        """
        table_name = self._get_table_name()
        exp_table = f"{table_name}__expirations"

        # Convert pandas Timestamp to date if needed
        if hasattr(as_of, 'date') and callable(as_of.date):
            as_of = as_of.date()

        where_clauses = [
            "p.underlying = $underlying",
            "p.date = $snapshot_date_str"
        ]
        params = {
            "underlying": underlying.upper(),
            "snapshot_date_str": as_of.isoformat()
        }

        if exchange:
            where_clauses.append("p.exchange = $exchange")
            params["exchange"] = exchange.upper()

        where_sql = " AND ".join(where_clauses)

        # Join with DLT child table for expirations
        query = f"""
            SELECT DISTINCT e.value as exp_str
            FROM {table_name} p
            JOIN {exp_table} e
                ON p._dlt_id = e._dlt_parent_id
            WHERE {where_sql}
        """

        df = self._query_with_duckdb(query, params)

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
            as_of: Snapshot date (date or pandas Timestamp)
            expiry: Expiration date (for compatibility, not used in query)
            exchange: Filter by specific exchange

        Returns:
            List of strike prices sorted ascending
        """
        table_name = self._get_table_name()
        strike_table = f"{table_name}__strikes"

        # Convert pandas Timestamp to date if needed
        if hasattr(as_of, 'date') and callable(as_of.date):
            as_of = as_of.date()

        where_clauses = [
            "p.underlying = $underlying",
            "p.date = $snapshot_date_str"
        ]
        params = {
            "underlying": underlying.upper(),
            "snapshot_date_str": as_of.isoformat()
        }

        if exchange:
            where_clauses.append("p.exchange = $exchange")
            params["exchange"] = exchange.upper()

        where_sql = " AND ".join(where_clauses)

        # Join with DLT child table for strikes
        query = f"""
            SELECT DISTINCT s.value as strike
            FROM {table_name} p
            JOIN {strike_table} s
                ON p._dlt_id = s._dlt_parent_id
            WHERE {where_sql}
            ORDER BY strike
        """

        df = self._query_with_duckdb(query, params)
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

        where_clauses = [
            "underlying = $underlying",
            "date = $snapshot_date_str"
        ]
        params = {
            "underlying": underlying.upper(),
            "snapshot_date_str": as_of.isoformat()
        }

        if exchange:
            where_clauses.append("exchange = $exchange")
            params["exchange"] = exchange.upper()

        where_sql = " AND ".join(where_clauses)

        query = f"""
            SELECT *
            FROM {table_name}
            WHERE {where_sql}
            ORDER BY exchange, trading_class
        """

        return self._query_with_duckdb(query, params)

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
            FROM {table_name}
            WHERE underlying = $underlying
            ORDER BY snapshot_date
        """

        df = self._query_with_duckdb(query, {"underlying": underlying.upper()})
        if df.empty:
            return set()
        # Convert pandas Timestamps to dates
        return {d.date() if hasattr(d, 'date') else d for d in df["snapshot_date"].tolist()}

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
            FROM {table_name}
            WHERE underlying = $underlying
            AND date = $snapshot_date_str
            ORDER BY exchange
        """

        params = {
            "underlying": underlying.upper(),
            "snapshot_date_str": as_of.isoformat()
        }
        df = self._query_with_duckdb(query, params)
        return df["exchange"].tolist() if not df.empty else []

    def get_symbols_with_snapshots(
        self,
        snapshot_date: Optional[date] = None,
        symbols: Optional[List[str]] = None,
    ) -> pd.DataFrame:
        """
        Get all symbols that have option chain snapshots, with summary stats.

        Args:
            snapshot_date: Optional filter for specific snapshot date
            symbols: Optional filter for specific symbols

        Returns:
            DataFrame with columns:
            - symbol: Symbol name
            - snapshot_date: Date of snapshot
            - expiration_count: Number of expirations
            - strike_count: Number of strikes
            - earliest_expiry: Earliest expiration date
            - latest_expiry: Latest expiration date

        Example:
            >>> reader = OptionChainSnapshotReader('./data', 'option_chains')
            >>> # Get all symbols with snapshots on a specific date
            >>> df = reader.get_symbols_with_snapshots(snapshot_date=date(2025, 11, 17))
            >>> # Get all snapshots for specific symbols
            >>> df = reader.get_symbols_with_snapshots(symbols=['AAPL', 'MSFT'])
        """
        table_name = self._get_table_name()
        where_clauses = []
        params = {}

        if snapshot_date:
            where_clauses.append("date = $snapshot_date")
            params["snapshot_date"] = snapshot_date

        if symbols:
            # Convert to uppercase for case-insensitive matching
            symbols_upper = [s.upper() for s in symbols]
            placeholders = ", ".join([f"$symbol_{i}" for i in range(len(symbols_upper))])
            where_clauses.append(f"underlying IN ({placeholders})")
            for i, sym in enumerate(symbols_upper):
                params[f"symbol_{i}"] = sym

        where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""

        query = f"""
            SELECT DISTINCT
                underlying as symbol,
                date as snapshot_date,
                MAX(expiration_count) as expiration_count,
                MAX(strike_count) as strike_count
            FROM {table_name}
            {where_sql}
            GROUP BY underlying, date
            ORDER BY underlying, date DESC
        """

        df = self._query_with_duckdb(query, params)
        return df
