#!/usr/bin/env python3
"""
Checkpoint Delta Lake tables to eliminate transaction log warnings.

Root cause: Large transaction logs (78K+ lines) cause delta-rs async channel
warnings during parsing. Checkpointing consolidates the log and eliminates warnings.

Usage:
    uv run python scripts/checkpoint_delta_tables.py
"""

from pathlib import Path
from deltalake import DeltaTable
import sys


def get_transaction_log_size(table_path: Path) -> tuple[int, int]:
    """Get transaction log file size and line count."""
    delta_log = table_path / "_delta_log"
    if not delta_log.exists():
        return 0, 0

    total_size = 0
    total_lines = 0

    for log_file in delta_log.glob("*.json"):
        if not log_file.name.startswith("_"):  # Skip checkpoint files
            total_size += log_file.stat().st_size
            total_lines += sum(1 for _ in open(log_file))

    return total_size, total_lines


def checkpoint_delta_table(table_path: Path) -> bool:
    """Checkpoint a Delta table and return success status."""
    print(f"\nProcessing: {table_path.name}")
    print("=" * 60)

    # Get before stats
    size_before, lines_before = get_transaction_log_size(table_path)
    print(f"Before:  {size_before:,} bytes, {lines_before:,} lines")

    try:
        # Load Delta table
        dt = DeltaTable(str(table_path))
        version_before = dt.version()
        print(f"Version: {version_before}")

        # Create checkpoint
        print("Creating checkpoint...")
        dt.create_checkpoint()

        # Get after stats
        size_after, lines_after = get_transaction_log_size(table_path)
        print(f"After:   {size_after:,} bytes, {lines_after:,} lines")

        # Calculate reduction
        size_reduction = 100 * (1 - size_after / size_before) if size_before > 0 else 0
        line_reduction = 100 * (1 - lines_after / lines_before) if lines_before > 0 else 0

        print(f"✓ Reduced size by {size_reduction:.1f}%")
        print(f"✓ Reduced lines by {line_reduction:.1f}%")

        return True

    except Exception as e:
        print(f"❌ Error: {e}")
        return False


def main():
    """Find and checkpoint all Delta tables."""
    base_path = Path("data_delta")

    if not base_path.exists():
        print(f"Error: {base_path} does not exist")
        sys.exit(1)

    # Find all Delta tables
    delta_tables = []
    for path in base_path.rglob("_delta_log"):
        table_path = path.parent
        delta_tables.append(table_path)

    if not delta_tables:
        print("No Delta tables found")
        sys.exit(0)

    print(f"Found {len(delta_tables)} Delta tables")
    print("=" * 60)

    # Checkpoint each table
    success_count = 0
    for table_path in sorted(delta_tables):
        if checkpoint_delta_table(table_path):
            success_count += 1

    # Summary
    print("\n" + "=" * 60)
    print(f"✅ Checkpointed {success_count}/{len(delta_tables)} tables")

    if success_count < len(delta_tables):
        print(f"⚠️  {len(delta_tables) - success_count} tables failed")
        sys.exit(1)


if __name__ == "__main__":
    main()
