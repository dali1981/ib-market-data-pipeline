"""Backfill infrastructure for historical market data."""

from .download_planner import DownloadPlanner, DownloadPlan, IBDurationLimit
from .gap_detection import missing_windows, business_day_range, trading_day_range  # Deprecated
from .market_calendar import MarketCalendar, get_market_calendar
from .config import (
    BackfillConfig,
    OptionBackfillConfig,
    OptionChainSnapshotConfig,
    ContractSelectionMode,
)
from .resources import (
    snapshot_option_chain,
    option_chain_snapshots_source,
    backfill_option_bars,
    option_bars_backfill_source,
    backfill_equity_bars,
    equity_bars_backfill_source,
)
from .contract_selection import (
    select_k_around_atm,
    select_by_moneyness,
    select_by_delta,
    filter_contracts_by_selection_mode,
)

__all__ = [
    # Download planning (NEW)
    "DownloadPlanner",
    "DownloadPlan",
    "IBDurationLimit",
    # Gap detection (DEPRECATED - use DownloadPlanner)
    "missing_windows",
    "business_day_range",
    "trading_day_range",
    # Market calendar
    "MarketCalendar",
    "get_market_calendar",
    # Config
    "BackfillConfig",
    "OptionBackfillConfig",
    "OptionChainSnapshotConfig",
    "ContractSelectionMode",
    # Resources
    "snapshot_option_chain",
    "option_chain_snapshots_source",
    "backfill_option_bars",
    "option_bars_backfill_source",
    "backfill_equity_bars",
    "equity_bars_backfill_source",
    # Contract selection
    "select_k_around_atm",
    "select_by_moneyness",
    "select_by_delta",
    "filter_contracts_by_selection_mode",
]
