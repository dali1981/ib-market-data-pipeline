# Snapshot Data Loss Fix

## Problem

The `dlt-ibapi snapshot` command was erasing existing snapshot data when run. Empty Parquet files were being created, overwriting existing data.

## Root Cause

**DLT's `merge` write disposition doesn't work properly with filesystem destination (Parquet files)**.

The snapshot resource was configured with:
```python
@dlt.resource(
    name="option_chain_snapshot",
    write_disposition="merge",  # ← Problem!
    primary_key=["underlying", "as_of", "exchange", "trading_class"],
)
```

And the pipeline was running with:
```python
info = run_pipeline(pipeline, data, storage_config, write_disposition="merge")
```

**Why this fails:**
- DLT's `merge` requires loading existing data to perform upserts
- With Parquet files, DLT creates temporary files during merge
- These temporary files sometimes end up empty or corrupted
- This is a known limitation of DLT with filesystem destinations

## Solution

Changed write disposition from `merge` to `append`:

### 1. Resource Configuration

**File**: `src/dlt_ibapi/backfill/resources.py`

```python
@dlt.resource(
    name="option_chain_snapshot",
    write_disposition="append",  # ← Fixed!
    primary_key=["underlying", "as_of", "exchange", "trading_class"],
)
```

### 2. Pipeline Execution

**File**: `src/dlt_ibapi/cli/snapshot.py`

```python
# Use 'append' for Parquet, 'merge' for Delta Lake
write_disp = "merge" if params.use_delta else "append"
logger.info(f"Running pipeline with write_disposition={write_disp}")
info = run_pipeline(pipeline, data, storage_config, write_disposition=write_disp)
```

## Handling Duplicates

With `append` mode, the same snapshot captured multiple times will create duplicate records. Handle this at query time:

### Option 1: Use DISTINCT in Queries

The `OptionChainSnapshotReader` automatically handles duplicates:

```python
reader = OptionChainSnapshotReader("./data", "option_chains")

# Internally uses DISTINCT to deduplicate
expirations = reader.get_available_expirations("AAPL", as_of=date(2025, 11, 14))
strikes = reader.get_strikes_for_expiry("AAPL", as_of=date(2025, 11, 14), expiry=...)
```

### Option 2: Use Delta Lake for True Upserts

Use the `--delta` flag to enable Delta Lake format with proper merge support:

```bash
dlt-ibapi snapshot AAPL --min-dte 7 --max-dte 60 --delta
```

**Delta Lake benefits:**
- True ACID upserts (no duplicates)
- Time travel (query historical versions)
- Schema evolution
- Optimized for incremental updates

**Trade-offs:**
- Slightly larger storage footprint
- Requires Delta Lake libraries

## Migration Guide

### If You Have Existing Snapshots

Your existing snapshot data is safe. The fix prevents future data loss.

**If you accidentally ran a snapshot that erased data:**

1. Check if you have backups in `data_backup_pre_delta/` or similar
2. Restore from backup if available
3. Re-capture snapshots for affected symbols:
   ```bash
   dlt-ibapi snapshot AAPL --min-dte 7 --max-dte 60
   dlt-ibapi snapshot MSFT --min-dte 7 --max-dte 60
   # ... etc
   ```

### For New Projects

Start with the fixed version. Optionally enable Delta Lake for better merge behavior:

```bash
# Standard Parquet (append mode, dedupe at query time)
dlt-ibapi snapshot AAPL --min-dte 7 --max-dte 60

# Delta Lake (true upserts, no duplicates)
dlt-ibapi snapshot AAPL --min-dte 7 --max-dte 60 --delta
```

## Testing the Fix

```bash
# 1. Capture initial snapshot
dlt-ibapi snapshot AAPL --min-dte 7 --max-dte 60

# 2. Verify data exists
dlt-ibapi list-snapshots

# 3. Capture again (should NOT erase)
dlt-ibapi snapshot AAPL --min-dte 7 --max-dte 60

# 4. Verify data still exists (may show duplicates)
dlt-ibapi list-snapshots

# 5. Query data (reader handles deduplication)
uv run python -c "
from dlt_ibapi.repositories import OptionChainSnapshotReader
from datetime import date

reader = OptionChainSnapshotReader('./data', 'option_chains')
expirations = reader.get_available_expirations('AAPL', as_of=date.today())
print(f'Expirations: {len(expirations)}')
"
```

## Related Issues

This fix also benefits:
- `backfill_equity_bars` - Uses append mode
- `backfill_option_bars` - Uses append mode
- `load_earnings` - Uses replace mode (intentional, overwrites calendar)

All resources using `append` or `replace` are unaffected by this issue.

## Recommendation

**For production use**: Enable Delta Lake format (`--delta`) for all pipelines that need upsert behavior:
- Option chain snapshots
- Any incremental data loads
- Data that gets re-captured/updated

**For simple use cases**: Standard Parquet with append mode is fine. Duplicates are minimal and handled at query time.
