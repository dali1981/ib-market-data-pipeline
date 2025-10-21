"""
Public API for reading market data from Parquet storage.

This module provides convenient Python classes for querying historical data
stored in Parquet format by dlt-ibapi pipeline resources.

Example:
    >>> from dlt_ibapi.read import EquityBarsReader
    >>>
    >>> reader = EquityBarsReader(database_path="./data", dataset_name="stocks")
    >>> bars = reader.get_bars("AAPL", bar_size="1 day")
    >>> symbols = reader.get_available_symbols()
"""

from .repositories import (
    EquityBarsReader,
    OptionBarsReader,
    OptionChainSnapshotReader,
)

__all__ = [
    "EquityBarsReader",
    "OptionBarsReader",
    "OptionChainSnapshotReader",
]
