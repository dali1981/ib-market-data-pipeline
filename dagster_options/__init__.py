"""
Dagster pipeline for multi-ticker option data collection.

This package provides a complete pipeline for:
1. Resolving ticker symbols to IB contracts
2. Fetching historical stock data
3. Capturing option chain snapshots
4. Selecting option contracts using multiple delta-targeting strategies
5. Backfilling historical option data

The pipeline is designed to run on-demand via Dagster UI or API.
"""

from dagster_options.assets import (
    ticker_contracts,
    stock_historical_data,
    option_chain_snapshots,
    selected_option_contracts,
    option_historical_data,
)
from dagster_options.definitions import defs

__all__ = [
    "ticker_contracts",
    "stock_historical_data",
    "option_chain_snapshots",
    "selected_option_contracts",
    "option_historical_data",
    "defs",
]
