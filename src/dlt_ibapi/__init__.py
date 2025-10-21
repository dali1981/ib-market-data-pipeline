"""
dlt-ibapi: DLT connector for Interactive Brokers.

Provides DLT sources and resources for ingesting market data from IB Gateway/TWS
into data pipelines (DuckDB, PostgreSQL, Snowflake, etc.).

Writing data (pipeline resources):
    - ib_historical_bars: Fetch and load historical bars
    - backfill_equity_bars: Backfill historical equity bars with gap detection
    - snapshot_option_chain: Capture option chain snapshots

Reading data (query API):
    - read.EquityBarsReader: Query historical equity bars from Parquet
    - read.OptionBarsReader: Query option bars from Parquet
    - read.OptionChainSnapshotReader: Query option chain snapshots
"""

from .sources import (
    ib_historical_bars,
    ib_market_data_snapshot,
    ib_option_chain,
    ib_contract_details,
    ib_source,
)
from .backfill import (
    snapshot_option_chain,
    option_chain_snapshots_source,
    backfill_option_bars,
    option_bars_backfill_source,
    backfill_equity_bars,
    equity_bars_backfill_source,
)
from . import read  # Public API for reading data

__version__ = "0.1.0"

__all__ = [
    # Basic resources
    "ib_source",
    "ib_historical_bars",
    "ib_market_data_snapshot",
    "ib_option_chain",
    "ib_contract_details",
    # Backfill resources
    "snapshot_option_chain",
    "option_chain_snapshots_source",
    "backfill_option_bars",
    "option_bars_backfill_source",
    "backfill_equity_bars",
    "equity_bars_backfill_source",
    # Read API
    "read",
]
