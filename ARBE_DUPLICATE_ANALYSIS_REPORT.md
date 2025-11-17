# ARBE Option Bars Duplicate Analysis Report

**Generated:** 2025-11-17
**Contract:** ARBE 2025-12-19 3.0 Call
**Data Location:** `/Users/mohamedali/trading_project/dlt-ibapi/data_delta/options/`

---

## Executive Summary

**YES, DUPLICATES EXIST** in the ARBE option bars data for the 2025-12-19 $3.00 Call contract.

### Key Findings

- **Total rows for contract:** 433
- **Unique timestamps:** 217
- **Duplicate rows:** 432 out of 433 (99.8% duplicated!)
- **Timestamps with duplicates:** 216 out of 217 (99.5%)
- **Duplicate pattern:** Almost every timestamp appears exactly twice

---

## Root Cause Analysis

### Duplicate Sources

The duplicates come from **TWO separate DLT pipeline runs** that loaded the same data:

| Load ID | Timestamp | Source File | Rows |
|---------|-----------|-------------|------|
| `1763385795.2881658` | 2025-11-17 14:23:15 | `part-00000-8b156bff-f4f9-48b4-a0d8-db676bfc1839-c000.snappy.parquet` | 216 |
| `1763392282.1125739` | 2025-11-17 16:11:22 | `part-00000-641b29c6-ae32-486a-8a01-221dc4a28de8-c000.snappy.parquet` | 216 |

**Time gap between loads:** ~1 hour 48 minutes

### Why Did This Happen?

The data was loaded twice on the same day (November 17, 2025), approximately 1 hour and 48 minutes apart. This indicates:

1. **No primary key enforcement:** DLT did not deduplicate based on the expected primary key `[symbol, expiry, strike, right, time, bar_size]`
2. **Append mode without deduplication:** The pipeline used `write_disposition="append"` without proper primary key configuration
3. **Same data fetched twice:** Both loads retrieved identical bar data from IB API

---

## Duplicate Characteristics

### Are Duplicates Identical?

**YES** - All duplicate rows are 100% identical across all value columns:

Sample duplicate at `20251112 11:00:00 US/Eastern`:
```
open: 0.1 (identical)
high: 0.1 (identical)
low: 0.05 (identical)
close: 0.1 (identical)
volume: 5071 (identical)
wap: 0.1 (identical)
bar_count: 179 (identical)
```

Only differences are DLT metadata:
- `_dlt_load_id`: Different (indicates source pipeline run)
- `_dlt_id`: Different (unique row identifier)
- Source file: Different parquet files

### Sample Duplicate Rows

| Time | Open | High | Low | Close | Volume | Load ID (excerpt) | Source File (excerpt) |
|------|------|------|-----|-------|--------|-------------------|----------------------|
| 20251112 11:00:00 | 0.10 | 0.10 | 0.05 | 0.10 | 5071 | ...2282 | ...641b29c6... |
| 20251112 11:00:00 | 0.10 | 0.10 | 0.05 | 0.10 | 5071 | ...5795 | ...8b156bff... |
| 20251112 11:05:00 | 0.10 | 0.10 | 0.05 | 0.10 | 259 | ...2282 | ...641b29c6... |
| 20251112 11:05:00 | 0.10 | 0.10 | 0.05 | 0.10 | 259 | ...5795 | ...8b156bff... |
| 20251112 11:10:00 | 0.10 | 0.10 | 0.05 | 0.05 | 246 | ...2282 | ...641b29c6... |
| 20251112 11:10:00 | 0.10 | 0.10 | 0.05 | 0.05 | 246 | ...5795 | ...8b156bff... |

---

## Data Summary

### Contract Details
- **Symbol:** ARBE
- **Expiration:** 2025-12-19
- **Strike:** $3.00
- **Right:** Call (C)
- **Bar Size:** 5 mins
- **Exchange:** SMART
- **Currency:** USD

### Date Range
- **First timestamp:** 20251112 11:00:00 US/Eastern
- **Last timestamp:** 20251117 09:30:00 US/Eastern
- **Duration:** ~5 trading days

### Price/Volume Statistics
- **Price range:** $0.00 - $0.10
- **Volume range:** 0 - 5,071 contracts

---

## Impact Assessment

### Data Quality Issues

1. **Storage waste:** 2x storage usage (432 duplicate rows)
2. **Query performance:** Queries return duplicate results unless deduplicated
3. **Analysis errors:** Metrics (volume, trade counts) will be double-counted
4. **Integrity violation:** Violates expected primary key constraint

### Affected Queries

Any query on this contract will return duplicates unless explicitly deduplicated:
```sql
-- Without deduplication (WRONG - returns 433 rows)
SELECT * FROM option_bars WHERE symbol='ARBE' AND expiry='2025-12-19' AND strike=3.0 AND right='C'

-- With deduplication (CORRECT - returns 217 rows)
SELECT DISTINCT symbol, expiry, strike, right, time, bar_size, open, high, low, close, volume
FROM option_bars
WHERE symbol='ARBE' AND expiry='2025-12-19' AND strike=3.0 AND right='C'
```

---

## Recommendations

### Immediate Actions

1. **Deduplicate existing data:**
   - Use DuckDB or pandas to remove duplicates
   - Keep only one copy based on `_dlt_load_id` or `_dlt_id`
   - Write deduplicated data back to parquet

2. **Verify other contracts:**
   - Check if other ARBE contracts have duplicates
   - Check if other symbols have duplicates
   - Assess scale of duplicate problem

### Long-term Fixes

1. **Configure DLT primary key properly:**
   ```python
   @dlt.resource(
       name="option_bars_backfill",
       write_disposition="append",
       primary_key=["symbol", "expiry", "strike", "right", "time", "bar_size"],
   )
   ```

2. **Use merge write disposition:**
   ```python
   write_disposition="merge"  # Automatically deduplicates on primary key
   ```

3. **Add data validation:**
   - Check for duplicates after each load
   - Alert on unexpected row counts
   - Implement idempotency checks

4. **Gap detection improvement:**
   - Ensure gap detection skips already-loaded data
   - Use `_dlt_load_id` to track loaded ranges
   - Prevent re-fetching same time windows

---

## Technical Details

### Primary Key Schema

Expected primary key (not currently enforced):
- `symbol` (ARBE)
- `expiry` (2025-12-19)
- `strike` (3.0)
- `right` (C)
- `time` (timestamp of bar)
- `bar_size` (5 mins)

### File Structure

```
data_delta/options/option_bars_backfill/underlying=ARBE/
├── part-00000-8b156bff-f4f9-48b4-a0d8-db676bfc1839-c000.snappy.parquet  (Load 1: 14:23:15)
└── part-00000-641b29c6-ae32-486a-8a01-221dc4a28de8-c000.snappy.parquet  (Load 2: 16:11:22)
```

### Columns Available

All data columns:
- `symbol`, `exchange`, `currency`, `bar_size`
- `time`, `date`, `timestamp`
- `open`, `high`, `low`, `close`, `volume`, `wap`, `bar_count`
- `expiry`, `strike`, `right`
- `_dlt_load_id`, `_dlt_id`
- `underlying`

---

## Appendix: Analysis Script

The analysis was performed using a Python script with DuckDB:

**File:** `check_arbe_duplicates.py`

**Key logic:**
1. Load all ARBE option data from parquet files
2. Filter for specific contract (2025-12-19 $3.00 Call)
3. Check for duplicates based on primary key columns
4. Compare values across duplicate rows
5. Analyze source files and load IDs

**Command to run:**
```bash
uv run python check_arbe_duplicates.py
```

---

**End of Report**