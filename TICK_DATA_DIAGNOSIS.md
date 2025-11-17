# Tick Data Issue Diagnosis

## ✅ RESOLVED (November 17, 2025)

### Issue Summary
Tick data download was entering an infinite loop, making the same API request repeatedly instead of receiving data.

### Root Cause
Manual pagination loop in `fetch_historical_ticks()` was unnecessary and broken:
- IB API **already handles pagination automatically** via callback batches
- `historicalTicksBidAsk` is called multiple times per request with `done=False/True`
- Manual loop was re-requesting with same start/end times → duplicate requests
- Caused infinite loop of identical 1007-tick responses

### Solution
Removed manual pagination loop entirely:
- Make **single** `reqHistoricalTicks` call per time window
- IB sends data in batches via multiple callback invocations
- Wrapper accumulates ticks and calls `finish()` when `done=True`
- Increased timeout from 20s to 120s to allow IB time to send all batches

### Verification
```bash
✓ Single API request (no duplicates)
✓ 1007 ticks received successfully
✓ Data persisted to parquet (1007 rows confirmed)
✓ No infinite loop
```

---

## Original Diagnosis (Historical)

##Symptoms

```bash
$ ./test_tick_download.sh

# Command hangs after this line:
Fetching ticks for 2025-11-14: 2025-11-14 15:00:00 to 2025-11-14 15:30:00
IB error (no reqId) code=... msg=2104  # Market data farm connection OK
IB error (no reqId) code=... msg=2107  # HMDS data farm connection OK
IB error (no reqId) code=... msg=2106  # Market data farm connected (delayed)
IB error (no reqId) code=... msg=2158  # Historical data farm connected

# Then hangs indefinitely (needs to be killed)
```

## Analysis

**User reports**: "i can see data coming in in the gateway ui"

This means:
1. ✅ Request is sent to IB successfully
2. ✅ IB is responding with tick data
3. ✅ Data is visible in TWS/Gateway UI
4. ❌ Data is NOT reaching our Python code

**Hypothesis**: The callback (`historicalTicksBidAsk`) is being called by IB, but the `IBFuture` is not collecting or returning the results properly.

## Possible Root Causes

### 1. IBFuture Timeout
- Default timeout: 20 seconds
- If IB sends data slowly or in batches, future might timeout before getting all data
- **Check**: Increase timeout to 60+ seconds

### 2. Registry/Future Not Completing
- `historicalTicksBidAsk` callback might not be calling `self._reg.finish(reqId)` properly
- `IBFuture` might be waiting forever for `done=True`
- **Check**: Verify wrapper callback logic

### 3. Empty Response Handling
- If IB returns 0 ticks, `historicalTicksBidAsk` might not set `done=True`
- Future hangs waiting for completion signal
- **Check**: Add logging to wrapper callbacks

### 4. Date Format Still Wrong
- Even though timezone is added, IB might not accept the format
- **Check**: Verify exact format matches IB examples

### 5. Data Availability Window
- Historical tick data might only be available for very recent dates
- Nov 14, 2025 might be outside the available window
- **Check**: Try with today's date minus 1-2 days

## Debugging Steps

### Step 1: Add Wrapper Logging
Add print statements to `wrapper.py` `historicalTicksBidAsk`:
```python
def historicalTicksBidAsk(self, reqId, ticks, done):
    print(f"[WRAPPER] historicalTicksBidAsk called: reqId={reqId}, ticks={len(ticks)}, done={done}")
    for tick in ticks:
        print(f"[WRAPPER] Tick: {tick.time}, bid={tick.priceBid}, ask={tick.priceAsk}")
        self._reg.add_item(reqId, tick)
    if done:
        print(f"[WRAPPER] Finishing reqId={reqId}")
        self._reg.finish(reqId)
    print(f"[WRAPPER] historicalTicksBidAsk done")
```

### Step 2: Add Service Logging
Add print statements to `tick_historical.py` `_fetch_ticks_page`:
```python
print(f"[SERVICE] Calling reqHistoricalTicks: rid={rid}")
print(f"[SERVICE] Start: {start_dt_str}")
print(f"[SERVICE] End: {end_dt_str}")
print(f"[SERVICE] Type: {tick_type}")

self.rt.client.reqHistoricalTicks(...)

print(f"[SERVICE] Waiting for future.result()...")
result = fut.result()
print(f"[SERVICE] Got result: {len(result)} ticks")
return result
```

### Step 3: Test with Very Recent Date
Try with yesterday/today:
```bash
# If today is Nov 17, 2025, try Nov 15, 2025:
dlt-ibapi backfill-ticks DIS 20251205 108.0 C \
  --start "2025-11-15 15:00" \
  --end "2025-11-15 15:05"
```

### Step 4: Check IB API Version
Verify ib_insync/ibapi version matches requirements:
```bash
pip show ibapi
```

### Step 5: Try with Different Contract
Use highly liquid contract (SPY):
```bash
dlt-ibapi backfill-ticks SPY 20251219 590.0 C \
  --start "2025-11-15 15:00" \
  --end "2025-11-15 15:05"
```

## Expected Next Actions

1. User should add logging to wrapper and service
2. Re-run test and check console output
3. Verify if callback is being called
4. If callback IS called but future hangs → Registry/Future issue
5. If callback NOT called → Request format issue

## Questions for User

1. What exact messages do you see in the Gateway UI when data comes in?
2. Does the Gateway show "Receiving historical tick data" or similar?
3. Does the Gateway show any errors?
4. What IB account type (paper/live)?
5. What ibapi version is installed?
