"""Backfill infrastructure for historical market data."""

from .gap_detection import missing_windows, business_day_range
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
    "missing_windows",
    "business_day_range",
    "BackfillConfig",
    "OptionBackfillConfig",
    "OptionChainSnapshotConfig",
    "ContractSelectionMode",
    "snapshot_option_chain",
    "option_chain_snapshots_source",
    "backfill_option_bars",
    "option_bars_backfill_source",
    "backfill_equity_bars",
    "equity_bars_backfill_source",
    "select_k_around_atm",
    "select_by_moneyness",
    "select_by_delta",
    "filter_contracts_by_selection_mode",
]
