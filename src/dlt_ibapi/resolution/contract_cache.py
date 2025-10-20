"""
Contract cache repository for storing resolved IB contract information.

Uses custom Parquet writer (not DLT) because we need:
1. Deduplication by conid (contract ID)
2. Persistent cache across pipeline runs
3. Control over when contracts are re-resolved
"""

from pathlib import Path
from typing import List, Optional, Set, Union
from datetime import datetime

import pandas as pd
import pyarrow as pa
import pyarrow.dataset as ds
import pyarrow.parquet as pq


class ContractCache:
    """
    Repository for caching resolved contract information.

    Schema mirrors earnings_ibapi contract repository but simplified for DLT use case.
    Deduplicates by conid and partitions by sec_type for efficient lookups.
    """

    def __init__(self, base_path: Union[str, Path]):
        """
        Initialize contract cache.

        Args:
            base_path: Base directory for cache storage (e.g., .dlt-ibapi/cache/contracts)
        """
        self.base_path = Path(base_path)
        self.dataset_path = self.base_path / "contracts"
        self.dataset_path.mkdir(parents=True, exist_ok=True)
        self._schema = self._create_schema()

    def _create_schema(self) -> pa.Schema:
        """Define PyArrow schema for contract cache."""
        return pa.schema([
            # Primary identifiers
            pa.field("symbol", pa.string()),
            pa.field("sec_type", pa.string()),
            pa.field("conid", pa.int64()),

            # Contract details
            pa.field("exchange", pa.string(), nullable=True),
            pa.field("primary_exchange", pa.string(), nullable=True),
            pa.field("currency", pa.string(), nullable=True),
            pa.field("local_symbol", pa.string(), nullable=True),
            pa.field("trading_class", pa.string(), nullable=True),

            # Numeric fields
            pa.field("multiplier", pa.int64(), nullable=True),
            pa.field("min_tick", pa.float64(), nullable=True),
            pa.field("price_magnifier", pa.int64(), nullable=True),

            # Option/derivative fields
            pa.field("under_conid", pa.int64(), nullable=True),
            pa.field("under_symbol", pa.string(), nullable=True),
            pa.field("under_sec_type", pa.string(), nullable=True),

            # Metadata
            pa.field("long_name", pa.string(), nullable=True),
            pa.field("industry", pa.string(), nullable=True),
            pa.field("category", pa.string(), nullable=True),
            pa.field("subcategory", pa.string(), nullable=True),

            # Trading hours
            pa.field("timezone_id", pa.string(), nullable=True),
            pa.field("trading_hours", pa.string(), nullable=True),
            pa.field("liquid_hours", pa.string(), nullable=True),

            # Additional fields
            pa.field("market_rule_ids", pa.string(), nullable=True),
            pa.field("real_expiration_date", pa.string(), nullable=True),
            pa.field("last_trade_time", pa.string(), nullable=True),
            pa.field("stock_type", pa.string(), nullable=True),

            # Partition column (derived from created_at)
            pa.field("snapshot", pa.date32(), nullable=False),

            # Timestamp (UTC)
            pa.field("created_at", pa.timestamp("ns", "UTC"), nullable=False),
        ])

    def save(self, df: pd.DataFrame) -> None:
        """
        Save contracts to cache with deduplication by conid.

        Args:
            df: DataFrame with contract data
        """
        if df is None or df.empty:
            return

        df = df.copy()

        # Validate required columns
        required = {"conid", "symbol", "sec_type", "currency"}
        missing = required - set(df.columns)
        if missing:
            raise ValueError(f"Missing required columns: {sorted(missing)}")

        # Deduplicate by conid (keep first occurrence)
        df = df.drop_duplicates(subset=["conid"], keep="first")

        # Add timestamps if not present
        if "created_at" not in df.columns:
            df["created_at"] = pd.Timestamp.utcnow()

        # Ensure created_at is timezone-aware UTC
        if pd.api.types.is_datetime64_any_dtype(df["created_at"]):
            df["created_at"] = pd.to_datetime(df["created_at"], utc=True)

        # Derive snapshot date from created_at
        df["snapshot"] = pd.to_datetime(df["created_at"]).dt.date

        # Ensure all schema columns exist (fill missing with None)
        for field in self._schema:
            if field.name not in df.columns:
                df[field.name] = None

        # Select only schema columns in correct order
        df = df[[field.name for field in self._schema]]

        # Convert to PyArrow table
        table = pa.Table.from_pandas(df, schema=self._schema)

        # Write to dataset partitioned by sec_type
        pq.write_to_dataset(
            table,
            root_path=str(self.dataset_path),
            partition_cols=["sec_type", "snapshot"],
            use_dictionary=True,
            compression="snappy",
            existing_data_behavior="overwrite_or_ignore",
        )

    def load(
        self,
        columns: Optional[List[str]] = None,
        symbol: Optional[Union[str, List[str]]] = None,
        conid: Optional[Union[int, List[int]]] = None,
        sec_type: Optional[str] = None,
    ) -> pa.Table:
        """
        Load contracts from cache with optional filtering.

        Args:
            columns: Columns to return (None = all)
            symbol: Filter by symbol(s)
            conid: Filter by contract ID(s)
            sec_type: Filter by security type

        Returns:
            PyArrow table with filtered contracts
        """
        # Return empty table if cache doesn't exist yet
        if not self.dataset_path.exists() or not any(self.dataset_path.rglob("*.parquet")):
            empty_df = pd.DataFrame(columns=[f.name for f in self._schema])
            return pa.Table.from_pandas(empty_df, schema=self._schema)

        # Create dataset
        dataset = ds.dataset(
            str(self.dataset_path),
            format="parquet",
            partitioning="hive",
            schema=self._schema,
        )

        # Build filter expression
        expr = None
        F = ds.field

        if symbol is not None:
            symbols = [symbol] if isinstance(symbol, str) else list(symbol)
            symbols = [s.upper() for s in symbols]  # Normalize to uppercase
            expr = F("symbol").isin(symbols) if len(symbols) > 1 else F("symbol") == symbols[0]

        if conid is not None:
            conids = [conid] if isinstance(conid, int) else list(conid)
            cond = F("conid").isin(conids) if len(conids) > 1 else F("conid") == conids[0]
            expr = cond if expr is None else (expr & cond)

        if sec_type is not None:
            cond = F("sec_type") == sec_type
            expr = cond if expr is None else (expr & cond)

        # Execute query
        table = dataset.to_table(columns=columns, filter=expr)

        return table

    def present_conids(self, sec_type: Optional[str] = None) -> Set[int]:
        """
        Get set of contract IDs present in cache.

        Args:
            sec_type: Optional filter by security type

        Returns:
            Set of conids in cache
        """
        table = self.load(columns=["conid"], sec_type=sec_type)
        if table.num_rows == 0:
            return set()

        df = table.to_pandas()
        return set(df["conid"].dropna().astype(int))

    def get_contract_by_conid(self, conid: int) -> Optional[dict]:
        """
        Get single contract by conid.

        Args:
            conid: Contract ID to lookup

        Returns:
            Contract dict or None if not found
        """
        table = self.load(conid=conid)
        if table.num_rows == 0:
            return None

        df = table.to_pandas()
        return df.iloc[0].to_dict()

    def get_contracts_by_symbol(self, symbol: str, sec_type: Optional[str] = None) -> pd.DataFrame:
        """
        Get all contracts for a symbol.

        Args:
            symbol: Symbol to lookup
            sec_type: Optional security type filter

        Returns:
            DataFrame of matching contracts
        """
        table = self.load(symbol=symbol, sec_type=sec_type)
        return table.to_pandas()
