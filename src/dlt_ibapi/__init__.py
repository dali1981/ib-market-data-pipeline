"""
dlt-ibapi: DLT connector for Interactive Brokers.

Provides DLT sources and resources for ingesting market data from IB Gateway/TWS
into data pipelines (DuckDB, PostgreSQL, Snowflake, etc.).
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
]
