"""
Backtesting integration for dlt-ibapi.

This package provides adapters to connect dlt-ibapi's data repositories
to the tools/ backtesting framework.

Components:
- Data providers: Adapt Parquet readers to tools/ interfaces
- Earnings providers: Provide earnings calendar data
"""

from .data_providers import (
    IBBacktestDataProvider,
    EarningsCalendarProvider,
)

__all__ = [
    "IBBacktestDataProvider",
    "EarningsCalendarProvider",
]
