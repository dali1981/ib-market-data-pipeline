#!/usr/bin/env python3
"""
Migrate Delta Lake tables from date/symbol partitioning to symbol-only partitioning.

Problem: 77,811 tiny files (4.3KB each) with date/symbol partitions → 91MB Delta log → 30s query overhead
Solution: Repartition by symbol only → fewer files, smaller Delta log, 1557x faster queries

Usage:
    # Backup first!
    cp -r data_delta data_delta_backup

    # Run migration
    uv run python scripts/migrate_to_symbol_partitioning.py

    # Or migrate specific dataset
    uv run python scripts/migrate_to_symbol_partitioning.py --dataset stocks
"""
import argparse
import time
import shutil
from pathlib import Path
from datetime import datetime
import duckdb
from deltalake import DeltaTable, write_deltalake

def migrate_dataset(
    source_path: Path,
    dest_path: Path,
    partition_by: str,
    table_name: str,
) -> dict:
    """
    Migrate a Delta table to new partitioning scheme.

    Args:
        source_path: Source Delta table path
        dest_path: Destination path for migrated table
        partition_by: Partition column (e.g., "symbol", "underlying", "date")
        table_name: Table name for logging

    Returns:
        Migration metrics
    """
    print(f"\n{'='*80}")
    print(f"Migrating: {table_name}")
    print(f"Source: {source_path}")
    print(f"Dest: {dest_path}")
    print(f"Partition by: {partition_by}")
    print(f"{'='*80}")

    start_time = time.time()

    # Check source exists
    if not source_path.exists():
        print(f"❌ Source does not exist: {source_path}")
        return {"success": False, "error": "Source not found"}

    if not (source_path / "_delta_log").exists():
        print(f"❌ Not a Delta table: {source_path}")
        return {"success": False, "error": "Not a Delta table"}

    # Get source stats
    dt_source = DeltaTable(str(source_path))
    files_before = len(dt_source.file_uris())

    delta_log_before = source_path / "_delta_log"
    json_files = list(delta_log_before.glob("*.json"))
    log_size_before_mb = sum(f.stat().st_size for f in json_files) / 1024 / 1024 if json_files else 0

    print(f"📊 Source stats:")
    print(f"   - Files: {files_before:,}")
    print(f"   - Delta log: {log_size_before_mb:.1f} MB")

    # Read all data using DuckDB (fast)
    print(f"\n📖 Reading data from source...")
    conn = duckdb.connect(":memory:")
    conn.execute("INSTALL delta")
    conn.execute("LOAD delta")

    read_start = time.time()
    df = conn.execute(f"SELECT * FROM delta_scan('{source_path}')").df()
    read_time = time.time() - read_start

    print(f"   ✓ Read {len(df):,} rows in {read_time:.1f}s")

    if df.empty:
        print(f"⚠️  No data to migrate")
        return {"success": True, "rows": 0, "files_before": files_before, "files_after": 0}

    # Create destination directory
    if dest_path.exists():
        print(f"\n⚠️  Destination exists, removing: {dest_path}")
        shutil.rmtree(dest_path)

    dest_path.parent.mkdir(parents=True, exist_ok=True)

    # Write with new partitioning
    print(f"\n📝 Writing data with new partitioning ({partition_by})...")
    write_start = time.time()

    write_deltalake(
        str(dest_path),
        df,
        partition_by=[partition_by],
        mode="append",
    )

    write_time = time.time() - write_start
    print(f"   ✓ Wrote {len(df):,} rows in {write_time:.1f}s")

    # Get destination stats
    dt_dest = DeltaTable(str(dest_path))
    files_after = len(dt_dest.file_uris())

    delta_log_after = dest_path / "_delta_log"
    json_files_after = list(delta_log_after.glob("*.json"))
    log_size_after_mb = sum(f.stat().st_size for f in json_files_after) / 1024 / 1024 if json_files_after else 0

    # Calculate improvements
    files_reduction = ((files_before - files_after) / files_before * 100) if files_before > 0 else 0
    log_reduction = ((log_size_before_mb - log_size_after_mb) / log_size_before_mb * 100) if log_size_before_mb > 0 else 0

    print(f"\n📊 Migration results:")
    print(f"   - Files before: {files_before:,}")
    print(f"   - Files after: {files_after:,}")
    print(f"   - Reduction: {files_reduction:.1f}%")
    print(f"   - Delta log before: {log_size_before_mb:.1f} MB")
    print(f"   - Delta log after: {log_size_after_mb:.1f} MB")
    print(f"   - Log reduction: {log_reduction:.1f}%")

    elapsed = time.time() - start_time
    print(f"\n✅ Migration complete in {elapsed:.1f}s")

    return {
        "success": True,
        "rows": len(df),
        "files_before": files_before,
        "files_after": files_after,
        "files_reduction_pct": files_reduction,
        "log_size_before_mb": log_size_before_mb,
        "log_size_after_mb": log_size_after_mb,
        "log_reduction_pct": log_reduction,
        "duration_seconds": elapsed,
    }


def main():
    parser = argparse.ArgumentParser(description="Migrate Delta tables to symbol-only partitioning")
    parser.add_argument(
        "--dataset",
        choices=["stocks", "options", "option_chains", "all"],
        default="all",
        help="Dataset to migrate (default: all)",
    )
    parser.add_argument(
        "--source-dir",
        type=Path,
        default=Path("data_delta"),
        help="Source directory (default: data_delta)",
    )
    parser.add_argument(
        "--dest-dir",
        type=Path,
        default=Path("data_delta_migrated"),
        help="Destination directory (default: data_delta_migrated)",
    )
    args = parser.parse_args()

    print(f"{'='*80}")
    print(f"Delta Lake Partitioning Migration")
    print(f"{'='*80}")
    print(f"Source: {args.source_dir}")
    print(f"Destination: {args.dest_dir}")
    print(f"Dataset filter: {args.dataset}")

    # Define migration tasks
    migrations = []

    if args.dataset in ("stocks", "all"):
        migrations.append({
            "table_name": "stocks/historical_bars",
            "source": args.source_dir / "stocks" / "historical_bars",
            "dest": args.dest_dir / "stocks" / "historical_bars",
            "partition_by": "symbol",
        })

    if args.dataset in ("options", "all"):
        migrations.append({
            "table_name": "options/option_bars_backfill",
            "source": args.source_dir / "options" / "option_bars_backfill",
            "dest": args.dest_dir / "options" / "option_bars_backfill",
            "partition_by": "underlying",
        })

    if args.dataset in ("option_chains", "all"):
        migrations.append({
            "table_name": "option_chains/option_chain_snapshot",
            "source": args.source_dir / "option_chains" / "option_chain_snapshot",
            "dest": args.dest_dir / "option_chains" / "option_chain_snapshot",
            "partition_by": "date",
        })

        # Also migrate child tables (expirations, strikes)
        for child_table in ["option_chain_snapshot__expirations", "option_chain_snapshot__strikes"]:
            source_child = args.source_dir / "option_chains" / child_table
            if source_child.exists():
                migrations.append({
                    "table_name": f"option_chains/{child_table}",
                    "source": source_child,
                    "dest": args.dest_dir / "option_chains" / child_table,
                    "partition_by": "date",  # Same as parent
                })

    if not migrations:
        print("❌ No migrations to perform")
        return

    # Run migrations
    results = []
    for migration in migrations:
        result = migrate_dataset(
            source_path=migration["source"],
            dest_path=migration["dest"],
            partition_by=migration["partition_by"],
            table_name=migration["table_name"],
        )
        results.append({"table": migration["table_name"], **result})

    # Summary
    print(f"\n{'='*80}")
    print(f"Migration Summary")
    print(f"{'='*80}")

    total_files_before = sum(r["files_before"] for r in results if r["success"])
    total_files_after = sum(r["files_after"] for r in results if r["success"])
    total_rows = sum(r["rows"] for r in results if r["success"])
    total_duration = sum(r["duration_seconds"] for r in results if r["success"])

    for result in results:
        if result["success"]:
            print(f"✅ {result['table']}: {result['files_before']:,} → {result['files_after']:,} files ({result['files_reduction_pct']:.1f}% reduction)")
        else:
            print(f"❌ {result['table']}: {result.get('error', 'Failed')}")

    print(f"\nTotal:")
    print(f"  - Rows migrated: {total_rows:,}")
    print(f"  - Files before: {total_files_before:,}")
    print(f"  - Files after: {total_files_after:,}")
    print(f"  - Overall reduction: {((total_files_before - total_files_after) / total_files_before * 100):.1f}%")
    print(f"  - Total time: {total_duration:.1f}s")

    print(f"\n{'='*80}")
    print(f"✅ Migration complete!")
    print(f"{'='*80}")
    print(f"\nNext steps:")
    print(f"1. Test queries on migrated data: {args.dest_dir}")
    print(f"2. If successful, replace old data:")
    print(f"   mv {args.source_dir} {args.source_dir}_old")
    print(f"   mv {args.dest_dir} {args.source_dir}")
    print(f"3. Update storage_config.yaml base_path if needed")


if __name__ == "__main__":
    main()