"""
Maintenance module for data quality operations.

Provides tools for:
- Deduplication of Delta Lake/Parquet tables
- Data validation and quality checks
- Cleanup operations
"""

from .deduplicate import (
    deduplicate_delta_table,
    deduplicate_dataset,
    get_duplicate_report,
    DeduplicationResult,
)

__all__ = [
    "deduplicate_delta_table",
    "deduplicate_dataset",
    "get_duplicate_report",
    "DeduplicationResult",
]
