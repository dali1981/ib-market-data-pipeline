"""
Backtesting integration for dlt-ibapi.

This package provides adapters to connect dlt-ibapi's data repositories
to the tools/ backtesting framework.

Components:
- Data providers: Adapt Parquet readers to tools/ interfaces
- Earnings providers: Provide earnings calendar data
- Runner: Options backtest execution engine
"""

from .data_providers import (
    IBBacktestDataProvider,
    EarningsCalendarProvider,
    OptionsChainProvider,
)
from .runner import (
    OptionsBacktestRunner,
    OptionsBacktestResult,
)

__all__ = [
    "IBBacktestDataProvider",
    "EarningsCalendarProvider",
    "OptionsChainProvider",
    "OptionsBacktestRunner",
    "OptionsBacktestResult",
]
