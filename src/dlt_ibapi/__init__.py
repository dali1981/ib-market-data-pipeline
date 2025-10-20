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

__version__ = "0.1.0"

__all__ = [
    "ib_source",
    "ib_historical_bars",
    "ib_market_data_snapshot",
    "ib_option_chain",
    "ib_contract_details",
]
