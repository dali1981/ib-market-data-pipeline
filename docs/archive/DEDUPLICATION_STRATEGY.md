# Deduplication Strategy for dlt-ibapi

## The Problem

**Current State:**
- DLT filesystem destination with Parquet **does NOT deduplicate** on primary keys
- `write_disposition="append"` + `primary_key=[...]` → **Still creates duplicates!**
- `write_disposition="merge"` → **Falls back to "append"** (no deduplication)

**Why This Matters:**
1. **Ingestion should run fast** (no dedup overhead during writes)
2. **Queries should be correct** (no duplicate bars)
3. **Backfill should be idempotent** (rerunning doesn't duplicate)

---

## Current Architecture Analysis

### Where Primary Keys Are Defined

```python
# src/dlt_ibapi/backfill/resources.py

@dlt.resource(
    name="option_bars_backfill",
    write_disposition="append",
    primary_key=["underlying", "expiry", "strike", "right", "bar_size", "time"],
)
def backfill_option_bars(...):
    # ⚠️ PRIMARY KEY IS IGNORED BY FILESYSTEM DESTINATION!
    pass

@dlt.resource(
    name="equity_bars_backfill",
    write_disposition="append",
    primary_key=["symbol", "bar_size", "time"],
)
def backfill_equity_bars(...):
    # ⚠️ PRIMARY KEY IS IGNORED BY FILESYSTEM DESTINATION!
    pass
```

**Problem:** Primary keys are defined but **not enforced** by filesystem destination.

### Current Deduplication (Gap Detection)

```python
# src/dlt_ibapi/backfill/equity_bars.py

def backfill_equity_bars_for_symbol(...):
    # 1. Get dates with existing data
    present_dates = reader.get_present_dates_for_symbol(...)

    # 2. Find missing windows
    gaps = missing_windows(present_dates, start_date, end_date)

    # 3. Fetch ONLY missing data
    for gap_start, gap_end in gaps:
        # Fetch from IB API
        bars = fetch_bars(gap_start, gap_end)
        yield bars
```

**This prevents duplicates at INGESTION time** - but only if:
- ✅ Gap detection works correctly
- ✅ No concurrent writers
- ✅ No manual re-runs without gap detection

**Issue:** If you run the same backfill twice, you get duplicates!

---

## Solution Options

### Option 1: Keep Gap Detection Only (Current)

**Strategy:** Prevent duplicates at ingestion time.

**Pros:**
- ✅ Fast ingestion (no dedup overhead)
- ✅ Simple architecture
- ✅ Works for normal backfill workflows

**Cons:**
- ❌ Not idempotent (rerun = duplicates)
- ❌ Vulnerable to concurrent writes
- ❌ Requires careful gap detection logic
- ❌ No protection against bugs

**Verdict:** ⚠️ **Works but fragile**

---

### Option 2: Post-Ingestion Deduplication Job

**Strategy:**
1. Ingest fast (with duplicates possible)
2. Run periodic dedup job to clean Parquet files

**Implementation:**

```python
# New file: src/dlt_ibapi/maintenance/deduplicate.py

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq
from pathlib import Path

def deduplicate_equity_bars(data_dir: str, dataset: str = "stocks"):
    """
    Deduplicate equity bars in-place using DuckDB.

    Primary key: (symbol, bar_size, time)
    """
    table_path = Path(data_dir) / dataset / "equity_bars_backfill"

    # 1. Read all Parquet with DuckDB
    conn = duckdb.connect(":memory:")
    deduped = conn.execute(f"""
        SELECT DISTINCT ON (symbol, bar_size, time) *
        FROM parquet_scan('{table_path}/**/*.parquet', hive_partitioning=true)
        ORDER BY symbol, bar_size, time, _dlt_load_id DESC
    """).arrow()

    # 2. Backup old files
    backup_dir = table_path.parent / f"{table_path.name}_backup"
    table_path.rename(backup_dir)
    table_path.mkdir()

    # 3. Write deduplicated Parquet
    pq.write_to_dataset(
        deduped,
        root_path=str(table_path),
        partition_cols=["date", "symbol"],
        use_dictionary=True,
        compression="snappy",
    )

    # 4. Remove backup (or keep for safety)
    # shutil.rmtree(backup_dir)

    return {"removed_duplicates": len_before - len(deduped)}
```

**Usage:**

```bash
# CLI command
dlt-ibapi deduplicate ./data --dataset stocks

# Or scheduled job (daily at 2 AM)
0 2 * * * dlt-ibapi deduplicate ./data --dataset stocks
```

**Pros:**
- ✅ Fast ingestion (no overhead)
- ✅ Idempotent backfills (can rerun safely)
- ✅ Handles concurrent writes
- ✅ Separate maintenance from ingestion

**Cons:**
- ❌ Queries see duplicates until dedup runs
- ❌ Extra storage during dedup
- ❌ Additional maintenance job needed

**Verdict:** ✅ **Best for production**

---

### Option 3: Delta Lake Format (Advanced)

**Strategy:** Use Delta Lake instead of plain Parquet for ACID transactions and merges.

**Implementation:**

```python
# In pipeline creation
pipeline = dlt.pipeline(
    pipeline_name="ib_stocks",
    destination=dlt.destinations.filesystem(bucket_url="data"),
    dataset_name="stocks",
)

# Use Delta table format
info = pipeline.run(
    data,
    loader_file_format="delta",  # Instead of "parquet"
    table_format="delta",
    write_disposition="merge",
    primary_key=["symbol", "bar_size", "time"],
)
```

**Pros:**
- ✅ True UPSERT support
- ✅ ACID transactions
- ✅ Time travel (versioning)
- ✅ Idempotent by design

**Cons:**
- ❌ More complex (Delta Lake dependency)
- ❌ Slightly slower ingestion
- ❌ Less portable than Parquet
- ❌ DLT Delta support is experimental

**Verdict:** 🔬 **Future enhancement**

---

### Option 4: Hybrid (Gap Detection + Periodic Dedup)

**Strategy:** Best of both worlds.

**Workflow:**

1. **Normal ingestion:** Use gap detection (prevents most duplicates)
2. **Safety net:** Weekly dedup job (catches edge cases)
3. **Manual reruns:** Use `--force-deduplicate` flag

**Implementation:**

```python
# Backfill with optional dedup
def backfill_equity(
    symbols,
    start_date,
    end_date,
    deduplicate_after: bool = False,  # New flag
):
    # 1. Normal backfill with gap detection
    pipeline.run(data, write_disposition="append")

    # 2. Optional immediate dedup
    if deduplicate_after:
        deduplicate_equity_bars(data_dir, dataset)
```

**Usage:**

```bash
# Normal backfill (fast, uses gap detection)
dlt-ibapi backfill-equity AAPL --start 2025-01-01

# Manual rerun (with dedup to be safe)
dlt-ibapi backfill-equity AAPL --start 2025-01-01 --deduplicate

# Scheduled dedup (weekly)
0 2 * * 0 dlt-ibapi deduplicate ./data --all-datasets
```

**Pros:**
- ✅ Fast normal operation
- ✅ Safe for reruns
- ✅ Handles edge cases
- ✅ Flexible

**Cons:**
- ❌ More complex implementation

**Verdict:** ✅ **RECOMMENDED**

---

## Recommended Implementation

### Phase 1: Add Deduplication Job (Quick Win)

1. **Create deduplication module:**
   ```
   src/dlt_ibapi/maintenance/
   ├── __init__.py
   └── deduplicate.py
   ```

2. **Add CLI command:**
   ```bash
   dlt-ibapi deduplicate ./data --dataset stocks
   dlt-ibapi deduplicate ./data --all-datasets
   ```

3. **Add to backfill commands:**
   ```bash
   dlt-ibapi backfill-equity AAPL --deduplicate-after
   ```

### Phase 2: Query-Time Deduplication (Immediate)

**For queries that need to be 100% correct NOW:**

```python
# In readers, add dedup option
class EquityBarsReader(ParquetReaderBase):
    def get_bars(
        self,
        symbol: str,
        bar_size: str,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
        deduplicate: bool = True,  # NEW
    ):
        if deduplicate:
            # Use DISTINCT ON in DuckDB query
            query = f"""
                SELECT DISTINCT ON (symbol, bar_size, time) *
                FROM {table_name}
                WHERE symbol = $symbol AND bar_size = $bar_size
                ORDER BY symbol, bar_size, time, _dlt_load_id DESC
            """
        else:
            # Fast path (may have duplicates)
            query = f"""
                SELECT * FROM {table_name}
                WHERE symbol = $symbol AND bar_size = $bar_size
            """
```

**Usage:**

```python
# Safe query (auto-deduplicates)
df = reader.get_bars("AAPL", "1 day")

# Fast query (if you know data is clean)
df = reader.get_bars("AAPL", "1 day", deduplicate=False)
```

---

## Decision Matrix

| Scenario | Solution | Why |
|----------|----------|-----|
| **Production data pipeline** | Gap detection + weekly dedup | Balance speed & correctness |
| **Ad-hoc analysis** | Query-time dedup | Always correct results |
| **Manual backfill rerun** | `--deduplicate-after` flag | Safety net |
| **Real-time ingestion** | Gap detection only | Maximum speed |
| **Future (6+ months)** | Migrate to Delta Lake | ACID guarantees |

---

## Immediate Action Items

### 1. Document Current Behavior

Add warning to docs:

```markdown
## ⚠️ Deduplication Notice

The filesystem destination does NOT automatically deduplicate on primary keys.

**Current protection:**
- Gap detection prevents duplicates during normal backfills
- Rerunning the same backfill WILL create duplicates

**Solutions:**
- Use `--deduplicate-after` flag for manual reruns
- Run weekly dedup job: `dlt-ibapi deduplicate ./data`
- Enable query-time dedup: `reader.get_bars(..., deduplicate=True)`
```

### 2. Add Query-Time Dedup (Quick Fix)

Update all readers to use `DISTINCT ON` by default:

```python
# This protects users even if storage has duplicates
query = f"""
    SELECT DISTINCT ON ({', '.join(primary_key_columns)}) *
    FROM {table_name}
    WHERE ...
    ORDER BY {', '.join(primary_key_columns)}, _dlt_load_id DESC
"""
```

### 3. Create Deduplication Tool (Weekend Project)

Implement `src/dlt_ibapi/maintenance/deduplicate.py` with:
- Dedup equity bars
- Dedup option bars
- Dedup snapshots
- CLI integration
- Dry-run mode
- Statistics report

---

## Summary

**Current State:** ⚠️ Duplicates possible if backfill is rerun

**Recommended Fix:**
1. **Short term:** Add `DISTINCT ON` to all reader queries (protects users NOW)
2. **Medium term:** Add dedup CLI command (manual safety net)
3. **Long term:** Weekly automated dedup job (production hygiene)

**Trade-off:**
- ✅ Keep fast ingestion (no dedup overhead during writes)
- ✅ Correct queries (dedup at read time or via maintenance job)
- ✅ Idempotent reruns (via `--deduplicate-after` or weekly job)

This is the **standard pattern** for Parquet-based pipelines:
- Write fast (append-only)
- Read correct (dedup on query)
- Maintain clean (periodic compaction)

---

**Prepared by:** Architecture Analysis
**Date:** 2025-10-21
**Next Steps:** Implement query-time dedup (1 hour) + dedup CLI (4 hours)
