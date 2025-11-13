# Plan to Fix Infinite Loop in stock_historical_data Asset

## Problem Analysis

The `stock_historical_data` asset is stuck in an infinite loop processing QQQ repeatedly. The logs show:
- "Processing QQQ" every ~2 seconds
- IB API error 2174 for date range 2025-09-23 to 2025-09-26
- "✓ QQQ: data loaded" after each iteration
- Then immediately "Processing QQQ" again

## Root Causes (Most Likely → Least Likely)

### 1. **DLT Pipeline Reuse Issue (MOST LIKELY)**
The DLT pipeline object is created ONCE outside the loop but used multiple times:
```python
pipeline = dlt.pipeline(...)  # Created once
for _, contract in descriptions_df.iterrows():
    resource = backfill_equity_bars(...)
    pipeline.run(resource)  # Re-used for each symbol
```

**DLT pipelines are stateful and may not be designed for reuse in tight loops.** Each call to `pipeline.run()` might be triggering some internal state issue or retry logic.

**Fix:** Create a fresh pipeline instance for each symbol, OR use DLT's batch/source pattern properly.

### 2. **IBRuntime Connection Not Cleaning Up**
Each `backfill_equity_bars` resource creates its own IBRuntime and should stop it in the finally block. But if there's an exception or the generator is being restarted, connections might not close properly, causing subsequent iterations to fail and retry.

**Fix:** Ensure runtime.stop() is always called, possibly move connection management outside the resource.

### 3. **Only QQQ in descriptions_df**
The ticker_contracts asset might have failed partway through (only resolving QQQ), so descriptions_df only contains one row, but something is causing the asset to re-execute infinitely.

**Fix:** Add logging to show how many symbols are in descriptions_df at the start of stock_historical_data.

### 4. **Gap Detection Finding Same Gap Repeatedly**
The gap detection finds Sept 23-26, IB returns error (no data), but the gap isn't marked as "attempted" so it tries again infinitely within the resource.

**Fix:** This is unlikely because the resource code shows it loops through gaps only once, not infinitely.

## Proposed Solution

### Step 1: Add Debugging Logs
Add log at start of `stock_historical_data` asset to show:
- Number of symbols in descriptions_df
- List of all symbols

This will confirm if only QQQ is present or if all symbols are there.

### Step 2: Fix DLT Pipeline Reuse
**Option A (Recommended):** Create fresh pipeline for each symbol:
```python
for _, contract in descriptions_df.iterrows():
    symbol = contract["symbol"]
    context.log.info(f"Processing {symbol}")

    # Create fresh pipeline for each symbol
    pipeline = dlt.pipeline(
        pipeline_name=f"stock_historical_data_{symbol}",
        destination="filesystem",
        dataset_name=config.stock_dataset,
    )

    resource = backfill_equity_bars(...)
    load_info = pipeline.run(resource)
```

**Option B:** Use DLT source pattern instead of individual resources:
```python
# Create ONE pipeline outside loop
pipeline = dlt.pipeline(...)

# Create list of resources
resources = []
for _, contract in descriptions_df.iterrows():
    resources.append(backfill_equity_bars(...))

# Run all resources in one pipeline.run() call
pipeline.run(resources)
```

### Step 3: Add Loop Protection
Add a counter to detect infinite loops and break after N iterations:
```python
max_iterations = len(descriptions_df) * 2  # Safety: 2x expected
iteration_count = 0

for _, contract in descriptions_df.iterrows():
    iteration_count += 1
    if iteration_count > max_iterations:
        context.log.error(f"INFINITE LOOP DETECTED: iteration {iteration_count}")
        raise RuntimeError("Infinite loop protection triggered")

    # Rest of loop...
```

### Step 4: Handle Error 2174 Gracefully
The error 2174 (no historical data) for Sept 23-26 might be legitimate (holidays/weekends). The resource already handles this with try/except, but we should verify the gaps are valid trading days.

## Implementation Steps

1. Add debugging log at start of `stock_historical_data` to show symbol count
2. Implement Option A (fresh pipeline per symbol) as primary fix
3. Add loop protection counter as safety measure
4. Test with single ticker first, then multiple tickers
5. Monitor logs to confirm loop is broken

## Files to Modify

- `dagster_options/assets.py` - stock_historical_data asset (lines 200-278)

## Expected Outcome

After fixes:
- Asset processes each symbol exactly once
- Moves through AAPL → MSFT → GOOGL → TSLA → NVDA → SPY → QQQ
- Completes successfully or fails with clear error (not infinite loop)
- Each symbol gets its own DLT pipeline instance to avoid state conflicts

## Additional Investigation Needed

If the above fixes don't work, investigate:

1. **Check DLT pipeline state directory**: DLT stores state in `.dlt` directory. There might be lock files or corrupted state causing retry behavior.

2. **Examine DLT logs**: Enable verbose DLT logging to see what's happening inside `pipeline.run()`:
   ```python
   import logging
   logging.getLogger("dlt").setLevel(logging.DEBUG)
   ```

3. **Check if pandas iterrows() is the issue**: Replace `iterrows()` with `itertuples()` or plain iteration:
   ```python
   for idx in range(len(descriptions_df)):
       symbol = descriptions_df.iloc[idx]["symbol"]
   ```

4. **Verify ticker_contracts output**: Add assertion to check descriptions_df:
   ```python
   assert len(descriptions_df) > 0, "descriptions_df is empty"
   assert len(descriptions_df) == len(descriptions_df["symbol"].unique()), "Duplicate symbols"
   context.log.info(f"Symbols to process: {descriptions_df['symbol'].tolist()}")
   ```

5. **Test without DLT**: Create a minimal test that calls the backfill logic without DLT pipeline to isolate whether DLT or the backfill logic is causing the loop.