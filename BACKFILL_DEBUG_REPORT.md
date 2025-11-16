# Option Bars Backfill Debug Report
**Date:** 2025-11-15/16
**Command:** `dlt-ibapi backfill-options TMC 5.6 --snapshot-date 2025-11-14 --k-expirations 2 --k-strikes 2 --bar-size "1 hour" --start 2025-11-01 --end 2025-11-14 --client-id 2`

## Executive Summary

✅ **IB Gateway HMDS Service**: Working
✅ **Data Fetching**: 918 bars fetched successfully from IB
✅ **Contract Resolution**: All 20 contracts resolved
✅ **Data Normalization**: All bars normalized and yielded to DLT
❌ **Data Writing**: **DLT failed to write data to disk (0 files written)**

**Root Cause:** Delta Lake backend issue - DLT reports "Rows: 0, Files: 0" despite yielding 918 bars.

---

## Timeline of Events

### Initial Run (13:02 - 13:15 UTC)
- **Status:** All requests timed out after 30s
- **Cause:** IB Gateway HMDS maintenance (error 2105: "HMDS data farm connection is broken")
- **Result:** 0 bars written (expected - service was down)

### Gateway Restart (19:21 UTC)
- **Status:** HMDS restored (code 2106: connection OK)
- **Verification Tests:**
  - ✅ Equity bars: 10 bars received for TMC stock
  - ✅ Option bars: 9 bars received for TMC 2025-11-21 4.5C option

### Second Run (19:21 - 19:22 UTC)
- **Status:** All 20 contracts processed successfully
- **Bars Yielded:** 918 bars total
- **Bars Written:** **0 bars** ❌

---

## Detailed Breakdown

### Contracts Processed (20 total)

| # | Contract | Expiry | Strike | Right | Bars Yielded |
|---|----------|--------|--------|-------|--------------|
| 1 | TMC | 2025-11-21 | 4.5 | C | 9 |
| 2 | TMC | 2025-11-21 | 4.5 | P | 36 |
| 3 | TMC | 2025-11-21 | 5.0 | C | 63 |
| 4 | TMC | 2025-11-21 | 5.0 | P | 70 |
| 5 | TMC | 2025-11-21 | 5.5 | C | 55 |
| 6 | TMC | 2025-11-21 | 5.5 | P | 70 |
| 7 | TMC | 2025-11-21 | 6.0 | C | 67 |
| 8 | TMC | 2025-11-21 | 6.0 | P | 74 |
| 9 | TMC | 2025-11-21 | 6.5 | C | 70 |
| 10 | TMC | 2025-11-21 | 6.5 | P | 44 |
| 11 | TMC | 2025-11-28 | 4.5 | C | 7 |
| 12 | TMC | 2025-11-28 | 4.5 | P | 24 |
| 13 | TMC | 2025-11-28 | 5.0 | C | 25 |
| 14 | TMC | 2025-11-28 | 5.0 | P | 34 |
| 15 | TMC | 2025-11-28 | 5.5 | C | 39 |
| 16 | TMC | 2025-11-28 | 5.5 | P | 40 |
| 17 | TMC | 2025-11-28 | 6.0 | C | 41 |
| 18 | TMC | 2025-11-28 | 6.0 | P | 46 |
| 19 | TMC | 2025-11-28 | 6.5 | C | 62 |
| 20 | TMC | 2025-11-28 | 6.5 | P | 32 |

**Total: 918 bars yielded**

### DLT Pipeline Result

```
Pipeline run completed successfully. Rows: 0, Files: 0
```

**This is the problem!** DLT received 918 bars but wrote 0 rows/files.

---

## Root Cause Analysis

### Hypothesis 1: Delta Lake Backend Issue (Most Likely)

**Evidence:**
1. `storage_config.yaml` specifies `backend: delta_lake` and `use_delta: true`
2. DLT logs show successful data yielding but zero files written
3. `./data_delta/options/` directory exists but is empty (64 bytes)
4. Delta Lake requires specific Spark/Delta dependencies that may not be installed

**Test:**
```bash
# Check if Delta Lake dependencies are installed
uv run python -c "import deltalake; print('Delta Lake OK')"
```

If this fails, Delta Lake backend is not functional.

### Hypothesis 2: DLT Resource Configuration Issue

The resource is configured with:
```python
@dlt.resource(
    name="option_bars_backfill",
    write_disposition="append",
    primary_key=["underlying", "expiry", "strike", "right", "bar_size", "time"],
    columns={
        "underlying": {"partition": True},  # Only underlying is partitioned
    }
)
```

**Potential Issue:** Delta Lake format might require different partition configuration than Parquet.

### Hypothesis 3: Silent Exception in DLT Pipeline

The log shows:
```
Pipeline run completed successfully
```

But this contradicts "Rows: 0, Files: 0". DLT may be swallowing an exception during the write phase.

---

## Recommended Fixes

### Option A: Switch to Parquet Backend (Immediate Fix)

1. **Edit `storage_config.yaml`:**
   ```yaml
   storage:
     backend: filesystem  # Change from delta_lake
     base_path: ./data
     use_delta: false  # Disable Delta Lake
   ```

2. **Re-run backfill:**
   ```bash
   uv run dlt-ibapi backfill-options TMC 5.6 \
     --snapshot-date 2025-11-14 \
     --k-expirations 2 \
     --k-strikes 2 \
     --bar-size "1 hour" \
     --start 2025-11-01 \
     --end 2025-11-14 \
     --client-id 2
   ```

3. **Verify data:**
   ```bash
   du -sh ./data/options/
   find ./data/options/ -name "*.parquet" | wc -l
   ```

**Expected Result:** Data writes to `./data/options/option_bars_backfill/*.parquet`

### Option B: Fix Delta Lake Dependencies

1. **Install Delta Lake:**
   ```bash
   uv add deltalake
   uv sync
   ```

2. **Re-run backfill** (same command)

3. **Verify Delta table:**
   ```bash
   ls -lh ./data_delta/options/option_bars_backfill/
   ```

**Expected Result:** Delta Lake files (`*.parquet` + `_delta_log/`) in `./data_delta/options/`

### Option C: Add Debug Logging to DLT

1. **Edit `src/dlt_ibapi/cli/backfill.py` line ~385:**
   ```python
   # After pipeline.run()
   print(f"DEBUG: Pipeline info: {info}")
   print(f"DEBUG: Load packages: {info.load_packages}")
   print(f"DEBUG: Metrics: {info.metrics}")
   ```

2. **Re-run** and check debug output

---

## Verification Steps (Once Fixed)

### 1. Check Data Written

```bash
# Filesystem backend
du -sh ./data/options/option_bars_backfill/
find ./data/options/option_bars_backfill/ -name "*.parquet" | wc -l

# Delta Lake backend
du -sh ./data_delta/options/option_bars_backfill/
ls -lh ./data_delta/options/option_bars_backfill/_delta_log/
```

**Expected:** Several MB of data, multiple parquet files

### 2. Query Data

```bash
uv run dlt-ibapi stats ./data --dataset options

# Or
uv run python -c "
from dlt_ibapi.repositories import OptionBarsReader
from datetime import date

reader = OptionBarsReader('./data', 'options')
bars = reader.get_bars_for_contract(
    underlying='TMC',
    expiry=date(2025, 11, 21),
    strike=5.0,
    right='C',
    bar_size='1 hour',
    start_date=date(2025, 11, 1),
    end_date=date(2025, 11, 14),
)
print(f'Found {len(bars)} bars')
print(bars.head())
"
```

**Expected:** 63 bars for TMC 2025-11-21 5.0C contract

### 3. Verify All Contracts

```bash
uv run python -c "
from dlt_ibapi.repositories import OptionBarsReader

reader = OptionBarsReader('./data', 'options')
contracts = reader.get_available_contracts('TMC', '1 hour')
print(f'Contracts: {len(contracts)}')
for c in contracts:
    print(f'  {c}')
"
```

**Expected:** 20 contracts (2 expirations × 5 strikes × 2 rights)

---

## Summary

**What Worked:**
- ✅ IB Gateway connection and HMDS service
- ✅ Contract resolution (20 contracts with conIds)
- ✅ Historical data fetching (918 bars from IB API)
- ✅ Data normalization and transformation
- ✅ DLT resource yielding (logs confirm bars were yielded)

**What Failed:**
- ❌ DLT writing data to disk (Delta Lake backend issue)

**Next Steps:**
1. Try **Option A** (switch to Parquet) - quickest solution
2. If Delta Lake is required, try **Option B** (install dependencies)
3. Add debug logging (**Option C**) to understand DLT failure

**Total Time:** ~45 seconds to process 20 contracts and fetch 918 bars
**Data Size:** Unknown (not written to disk)
**Success Rate:** 20/20 contracts fetched, 0/20 written ❌

---

## Test Scripts Created

- `test_equity_bars.py` - Tests TMC stock bars (baseline)
- `test_aapl_option_bars.py` - Tests AAPL option bars (liquid stock)
- `test_option_bars_resolved.py` - Tests TMC option with proper contract resolution
- `test_final_option.py` - Tests exact backfill parameters with timezone format
- `test_timezone_format.py` - Tests different IB API datetime formats

All tests passed once HMDS was restored, confirming IB API integration is working correctly.

---

## Logs

- **Full backfill log:** `/tmp/backfill-rerun.log`
- **Original attempt (during maintenance):** `/tmp/backfill-output.log`

## Related Files

- **Storage config:** `storage_config.yaml`
- **DLT resource:** `src/dlt_ibapi/backfill/resources.py:202-478`
- **CLI backfill:** `src/dlt_ibapi/cli/backfill.py:241-410`
- **Troubleshooting guide:** `TROUBLESHOOTING_OPTION_BACKFILL.md`
