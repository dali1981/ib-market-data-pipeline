"""
Backtesting integration for dlt-ibapi.

This package provides adapters to connect dlt-ibapi's data repositories
to the tools/ backtesting framework.

Components:
- Data providers: Adapt Parquet readers to tools/ interfaces
- Earnings providers: Provide earnings calendar data
- Runner: Options backtest execution engine
- Validation: Data availability checking

WARNING: OptionsChainProvider is DEPRECATED and non-functional.
IB API does not provide historical option chain snapshots.
Use OptionBarsReader directly for historical option prices.
"""

from .data_providers import (
    IBBacktestDataProvider,
    EarningsCalendarProvider,
    OptionsChainProvider,  # DEPRECATED - kept for backward compatibility
    BacktestDataRequirements,
)
from .earnings_loader import (
    EarningsCalendarLoader,
    EarningsEvent,
)
from .runner import (
    OptionsBacktestRunner,
    OptionsBacktestResult,
)
from .validation import (
    BacktestDataValidator,
    ValidationSummary,
    DataCoverageReport,
    OptionCoverageReport,
    BarsCoverageReport,
)

__all__ = [
    # Data providers
    "IBBacktestDataProvider",
    "EarningsCalendarProvider",
    "OptionsChainProvider",  # DEPRECATED
    "BacktestDataRequirements",
    # Earnings loading
    "EarningsCalendarLoader",
    "EarningsEvent",
    # Validation
    "BacktestDataValidator",
    "ValidationSummary",
    "DataCoverageReport",
    "OptionCoverageReport",
    "BarsCoverageReport",
    # Backtest execution
    "OptionsBacktestRunner",
    "OptionsBacktestResult",
]
