# Troubleshooting: Option Bars Backfill

## Issue: No Data Written to Database

When running `dlt-ibapi backfill-options`, you may see IB Gateway activity but no data written to `./data_delta/options/`.

## Root Cause

**IB Gateway Historical Market Data Service (HMDS) is unavailable or under maintenance.**

This is indicated by error code **2105**:
```
HMDS data farm connection is broken:ushmds
```

This is **NOT a code issue** - it's an IB infrastructure issue that affects all historical data requests.

## Diagnosis

The isolation tests confirmed:
1. ✅ IB Gateway connection works (codes 2104, 2106, 2158 are normal)
2. ✅ Contract resolution works (contracts resolve with conIds)
3. ✅ Option chain snapshots work (20 contracts selected for TMC)
4. ✅ Gap detection works (identifies missing dates)
5. ❌ Historical bars requests fail (timeout or error 162)

### Error Codes Observed

| Code | Meaning | Impact |
|------|---------|--------|
| 2104 | Market data farm connection OK | ✅ Normal |
| 2106 | HMDS data farm connection OK | ✅ Normal (when available) |
| 2105 | **HMDS data farm connection broken** | ❌ **No historical data** |
| 2158 | Sec-def data farm connection OK | ✅ Normal |
| 162  | Historical market data service error | ❌ No data available |
| 2174 | Timezone warning (deprecated format) | ⚠️ Warning only |

## Solution: Wait for IB Maintenance to Complete

**Once IB Gateway shows HMDS connection restored**, follow these steps:

### Step 1: Verify HMDS Connection

Look for this message in IB Gateway logs:
```
HMDS data farm connection is OK:ushmds
```

Or run the test script:
```bash
uv run python test_equity_bars.py
```

**Expected output** when HMDS is working:
```
✅ TMC EQUITY: 5 bars received
Bar: 20251105 O=5.23 H=5.45 L=5.20 C=5.38 V=125000
...
```

### Step 2: Test Option Bars

Once equity bars work, test option bars:
```bash
uv run python test_aapl_option_bars.py
```

**Expected output**:
```
✅ AAPL Result: 5 bars
Bar: 20251111 O=2.35 H=2.50 L=2.30 C=2.45 V=1500
...
```

### Step 3: Run Full Backfill

Now run the full backfill command:
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

**Expected output** (when working):
```
2025-11-15T13:XX:XX.XXXXXX [info] contracts_selected count=20
2025-11-15T13:XX:XX.XXXXXX [info] Download plan: 10 trading days in 1 API calls
2025-11-15T13:XX:XX.XXXXXX [info] batch_complete bars_yielded=65 batch_start=2025-11-03 batch_end=2025-11-14
...
Pipeline completed successfully
✅ Backfilled 20 contracts, 1,234 total bars
```

### Step 4: Verify Data Wrote to Database

Check that data exists:
```bash
# Check directory size
du -sh ./data_delta/options/

# Expected: > 0 bytes (e.g., 500K - 5M depending on data volume)
```

Query the data:
```bash
uv run dlt-ibapi stats ./data_delta --dataset options
```

**Expected output**:
```
Dataset: options
Table: option_bars_backfill

Total rows: 1,234
Date range: 2025-11-01 to 2025-11-14
Symbols: TMC
Contracts: 20
```

Read the data:
```bash
uv run python -c "
from dlt_ibapi.repositories import OptionBarsReader
from datetime import date

reader = OptionBarsReader('./data_delta', 'options')
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

## Common Issues

### Issue: Still Getting Timeouts After HMDS Restored

**Cause**: Too many concurrent requests to IB API (rate limiting)

**Solution**: Reduce batch size or add delays:
```python
# In backfill/resources.py, add delay between contracts
import time
time.sleep(1)  # 1 second between contracts
```

### Issue: Error 162 for Specific Contracts

**Cause**: No historical data available for illiquid options (no trading volume)

**Solution**: This is expected for low-volume options. The code will skip these and continue:
```
2025-11-15T13:XX:XX.XXXXXX [error] Failed to fetch bars: IB error 162
2025-11-15T13:XX:XX.XXXXXX [info] Processing next contract...
```

### Issue: Data Written to Wrong Location

**Check**: Verify `storage_config.yaml` has correct `base_path`:
```yaml
storage:
  base_path: ./data_delta  # Data written here
```

Query the correct location:
```bash
uv run dlt-ibapi stats ./data_delta --dataset options  # NOT ./data
```

## Technical Details

### Why HMDS Maintenance Affects Backfill

Historical Market Data Service (HMDS) is IB's dedicated infrastructure for serving historical bar data (OHLCV). When HMDS is down:

1. ✅ Real-time market data still works (different service)
2. ✅ Contract details still work (different service)
3. ✅ Option chain snapshots still work (uses different API)
4. ❌ **Historical bars fail** (requires HMDS)

### What Happens During Backfill

```
User Command
    ↓
CLI (backfill-options)
    ↓
DLT Resource (backfill_option_bars)
    ↓
Contract Selection (20 contracts from snapshot)
    ↓
Gap Detection (identifies missing dates)
    ↓
Contract Resolution (gets conIds from cache)
    ↓
Historical Bars Request → IB Gateway → HMDS Service
    ↓
← TIMEOUT (if HMDS down)
    ↓
Error logged, move to next contract
    ↓
Pipeline completes with 0 bars written
```

### Debug Logging

To see detailed logs during backfill, the code already has structured logging:

```bash
# Logs show:
# - contracts_selected: count=20
# - Download plan: X trading days in Y API calls
# - batch_complete: bars_yielded=N
# - IB errors with codes
```

Look for `bars_yielded` in logs - if this is 0 for all batches, HMDS is not returning data.

## Summary

**This is NOT a bug in dlt-ibapi code.** The issue is:

1. IB Gateway HMDS service was under maintenance (error 2105)
2. All historical data requests timed out or returned error 162
3. Code correctly sent requests, but IB couldn't fulfill them
4. Zero bars returned → zero bars written to database

**Action**: Wait for IB maintenance to complete, then retry the backfill command. Use test scripts to verify HMDS is working before running full backfill.

---

## Quick Reference

**Test Scripts** (saved in project root):
- `test_equity_bars.py` - Test TMC stock bars (baseline)
- `test_aapl_option_bars.py` - Test AAPL option bars (liquid)
- `test_option_bars_resolved.py` - Test TMC option with resolution

**Commands**:
```bash
# 1. Test HMDS is working
uv run python test_equity_bars.py

# 2. Run backfill
uv run dlt-ibapi backfill-options TMC 5.6 --snapshot-date 2025-11-14 \
  --k-expirations 2 --k-strikes 2 --bar-size "1 hour" \
  --start 2025-11-01 --end 2025-11-14 --client-id 2

# 3. Verify data
du -sh ./data_delta/options/
uv run dlt-ibapi stats ./data_delta --dataset options
```

**Expected File Structure** (when working):
```
./data_delta/options/
  option_bars_backfill/
    underlying=TMC/
      part-00000-XXXXX.snappy.parquet  (contains bars)
```
