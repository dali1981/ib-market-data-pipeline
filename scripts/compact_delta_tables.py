#!/usr/bin/env python3
"""
Compact Delta Lake tables to fix small files problem.

Problem: 77,811 small parquet files → 91MB Delta log → 30s query overhead
Solution: Compact into larger files (target: 128MB each)

Usage:
    uv run python scripts/compact_delta_tables.py
"""
import time
from pathlib import Path
from deltalake import DeltaTable

def compact_table(table_path: Path, target_size_mb: int = 128):
    """Compact a Delta table by merging small files."""
    print(f"\n{'='*80}")
    print(f"Compacting: {table_path}")
    print(f"{'='*80}")

    if not table_path.exists():
        print(f"❌ Table does not exist: {table_path}")
        return

    if not (table_path / "_delta_log").exists():
        print(f"❌ Not a Delta table: {table_path}")
        return

    # Load table
    dt = DeltaTable(str(table_path))

    # Count files before
    files_before = len(dt.files())
    print(f"📊 Files before: {files_before:,}")

    # Get Delta log size
    delta_log = table_path / "_delta_log"
    json_files = list(delta_log.glob("*.json"))
    if json_files:
        json_size_mb = sum(f.stat().st_size for f in json_files) / 1024 / 1024
        print(f"📊 Delta log size: {json_size_mb:.1f} MB")

    # Compact
    print(f"🔧 Compacting (target: {target_size_mb} MB per file)...")
    start = time.time()

    try:
        metrics = dt.optimize.compact(
            target_size=target_size_mb * 1024 * 1024,  # Convert to bytes
        )
        elapsed = time.time() - start

        print(f"✅ Compaction complete in {elapsed:.1f}s")
        print(f"📊 Metrics:")
        print(f"   - Files added: {metrics['numFilesAdded']}")
        print(f"   - Files removed: {metrics['numFilesRemoved']}")
        print(f"   - Partitions optimized: {metrics['partitionsOptimized']}")

        # Count files after
        dt = DeltaTable(str(table_path))  # Reload
        files_after = len(dt.files())
        reduction = (1 - files_after / files_before) * 100 if files_before > 0 else 0
        print(f"📊 Files after: {files_after:,} ({reduction:.1f}% reduction)")

    except Exception as e:
        print(f"❌ Compaction failed: {e}")

def vacuum_table(table_path: Path, retention_hours: int = 168):
    """Vacuum old files to reclaim space."""
    print(f"\n🗑️  Vacuuming old files (retention: {retention_hours}h)...")

    dt = DeltaTable(str(table_path))

    # Dry run first
    deleted_files = dt.vacuum(retention_hours=retention_hours, dry_run=True)
    print(f"   Would delete {len(deleted_files)} files")

    if deleted_files:
        # Actually delete
        deleted_files = dt.vacuum(retention_hours=retention_hours, dry_run=False)
        print(f"   ✅ Deleted {len(deleted_files)} files")
    else:
        print(f"   ℹ️  No files to delete")

def main():
    """Compact all Delta tables in data_delta/."""
    base_path = Path("data_delta")

    if not base_path.exists():
        print(f"❌ data_delta/ directory not found")
        return

    # Find all Delta tables
    tables = []
    for dataset_dir in base_path.iterdir():
        if not dataset_dir.is_dir():
            continue

        for table_dir in dataset_dir.iterdir():
            if not table_dir.is_dir():
                continue

            if (table_dir / "_delta_log").exists():
                tables.append(table_dir)

    if not tables:
        print("❌ No Delta tables found in data_delta/")
        return

    print(f"Found {len(tables)} Delta table(s)")

    # Compact each table
    for table_path in sorted(tables):
        try:
            compact_table(table_path, target_size_mb=128)

            # Vacuum to reclaim space (7 days retention)
            vacuum_table(table_path, retention_hours=168)

        except Exception as e:
            print(f"❌ Error processing {table_path}: {e}")

    print(f"\n{'='*80}")
    print("✅ Compaction complete!")
    print(f"{'='*80}")

if __name__ == "__main__":
    main()