"""CLI business logic layer.

Provides testable business logic separated from CLI framework (Typer).
All functions use Pydantic models for type safety and validation.

Architecture:
- models.py: Pydantic models for params and results
- backfill.py: Backfill business logic
- snapshot.py: Snapshot business logic
- stats.py: Stats business logic

Pattern:
    CLI (Typer) → Pydantic models → Business logic → Pydantic results → CLI display
"""

from dlt_ibapi.cli.models import (
    BackfillEquityParams,
    BackfillEquityResult,
    BackfillOptionsParams,
    BackfillOptionsResult,
    SnapshotParams,
    SnapshotResult,
    ListSnapshotsParams,
    ListSnapshotsResult,
    StatsParams,
    StatsResult,
)
from dlt_ibapi.cli.backfill import execute_backfill_equity, execute_backfill_options
from dlt_ibapi.cli.snapshot import execute_snapshot, execute_list_snapshots
from dlt_ibapi.cli.stats import execute_stats

__all__ = [
    # Models
    "BackfillEquityParams",
    "BackfillEquityResult",
    "BackfillOptionsParams",
    "BackfillOptionsResult",
    "SnapshotParams",
    "SnapshotResult",
    "ListSnapshotsParams",
    "ListSnapshotsResult",
    "StatsParams",
    "StatsResult",
    # Business logic functions
    "execute_backfill_equity",
    "execute_backfill_options",
    "execute_snapshot",
    "execute_list_snapshots",
    "execute_stats",
]
