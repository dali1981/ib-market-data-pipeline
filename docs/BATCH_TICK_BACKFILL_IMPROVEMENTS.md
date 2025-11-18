# Batch Calendar Spread Tick Backfill Improvements

**Date**: 2025-11-17
**Status**: Complete ✅

## Problem Statement

The `backfill-batch-calendar-ticks` command had several issues:

1. **Future data unavailable**: For AFTER_HOURS earnings, the exit window is next day 9-10am. Running the command on the same day as earnings would fail because this data doesn't exist yet.

2. **Required --top-n**: The `--top-n` parameter was mandatory, making it impossible to process all symbols at once.

3. **Mixed timing groups**: No way to separate PRE_MARKET vs AFTER_HOURS earnings, which have different data availability windows.

4. **All-or-nothing downloads**: No way to download entry and exit windows separately as data becomes available throughout the day.

## Solution

### 1. Earnings Timing Filter (`--earnings-timing`)

Added a new optional parameter to filter symbols by their earnings announcement timing:

```bash
# Process only PRE_MARKET earnings (data available same day)
dlt-ibapi backfill-batch-calendar-ticks 2025-11-17 --earnings-timing PRE_MARKET

# Process only AFTER_HOURS earnings (run next day when data available)
dlt-ibapi backfill-batch-calendar-ticks 2025-11-17 --earnings-timing AFTER_HOURS
```

**Valid values**: `PRE_MARKET` or `AFTER_HOURS`

**Timing Logic**:
- **PRE_MARKET**: Entry = day before 3-4pm, Exit = same day 9-10am (✓ data available immediately)
- **AFTER_HOURS**: Entry = same day 3-4pm, Exit = next day 9-10am (⚠️ data available next day)

### 2. Optional Top-N (`--top-n`)

The `--top-n` parameter is now optional. Omit it to process all matching symbols:

```bash
# Process TOP 10 opportunities (sorted by IV ratio)
dlt-ibapi backfill-batch-calendar-ticks 2025-11-17 --top-n 10

# Process ALL opportunities (no limit)
dlt-ibapi backfill-batch-calendar-ticks 2025-11-17
```

### 3. Future Data Detection

Added automatic detection and warning for symbols with exit windows in the future:

```python
# Checks if exit_time > now() for AFTER_HOURS earnings
if earnings_timing == 'AFTER_HOURS':
    exit_time = earnings_date + 1 day @ 10am
    if exit_time > now:
        logger.warning("future_exit_windows_detected", symbols=[...])
```

This helps diagnose why tick downloads might fail (data doesn't exist yet).

### 4. Earnings Timing in Results

Each opportunity now includes `earnings_timing` field for visibility:

```python
{
    'symbol': 'ARMK',
    'strike': 150.0,
    'short_expiry': date(2025, 11, 29),
    'long_expiry': date(2025, 12, 20),
    'right': 'C',
    'iv_ratio': 1.856,
    'expected_pnl': 12.50,
    'earnings_timing': 'PRE_MARKET',  # NEW
}
```

### 5. Window Selection Flags (`--entry` / `--exit`)

Added optional flags to download entry and exit windows separately:

**Default behavior (no flags):**
- Downloads BOTH entry and exit windows
- Total: 4 tick downloads per symbol (short entry, short exit, long entry, long exit)

**With `--entry` flag:**
- Downloads ONLY entry window (3-4pm day before earnings)
- Total: 2 tick downloads per symbol (short entry, long entry)
- Use when entry data becomes available but exit data is still in the future

**With `--exit` flag:**
- Downloads ONLY exit window (9-10am after earnings announcement)
- Total: 2 tick downloads per symbol (short exit, long exit)
- Use after earnings announcement when exit data becomes available

**Validation:**
- Cannot specify both `--entry` AND `--exit` simultaneously
- Error message: "Cannot specify both --entry and --exit. Choose one or omit both for all windows."

**Use Cases:**
1. **Progressive downloads**: Download entry data @ 4pm day before, then exit data @ 10am earnings day
2. **Retry failed windows**: Re-download only exit window if it failed initially
3. **Scheduled workflows**: Automate separate entry/exit downloads at different times

## Usage Examples

### Example 1: Process Pre-Market Earnings Same Day

```bash
# Run on 2025-11-17 (same day as earnings)
dlt-ibapi backfill-batch-calendar-ticks 2025-11-17 --earnings-timing PRE_MARKET

# Output:
# ✓ Loaded 13 PRE_MARKET opportunities
# ✓ All exit windows at 9-10am TODAY (data available)
```

**Result**: All data downloads successfully because exit windows are same day.

### Example 2: Process After-Hours Earnings Next Day

```bash
# Run on 2025-11-18 (day after earnings)
dlt-ibapi backfill-batch-calendar-ticks 2025-11-17 --earnings-timing AFTER_HOURS

# Output:
# ✓ Loaded 5 AFTER_HOURS opportunities
# ✓ All exit windows at 9-10am TODAY (data now available)
```

**Result**: All data downloads successfully because exit windows are today (day after earnings).

### Example 3: Combine Filters

```bash
# Top 5 pre-market earnings only
dlt-ibapi backfill-batch-calendar-ticks 2025-11-17 \
  --top-n 5 \
  --earnings-timing PRE_MARKET

# All after-hours earnings (run next day)
dlt-ibapi backfill-batch-calendar-ticks 2025-11-17 \
  --earnings-timing AFTER_HOURS
```

### Example 4: Specific Symbols with Filter

```bash
# Process specific symbols (still runs strategy selection for these symbols)
dlt-ibapi backfill-batch-calendar-ticks 2025-11-17 \
  --symbols "ARMK,JJSF,ACM"
```

### Example 5: Progressive Download Workflow (NEW)

**Scenario**: PRE_MARKET earnings on Monday Nov 17. Download data progressively as it becomes available.

```bash
# Step 1: Friday Nov 14 @ 4:00 PM - Download entry window (now available)
dlt-ibapi backfill-batch-calendar-ticks 2025-11-17 \
  --earnings-timing PRE_MARKET \
  --entry

# Result: Downloads ticks from Friday 3-4pm for short + long legs
# Status: Entry data ✓ complete, Exit data ⏳ pending (not available yet)

# Step 2: Monday Nov 17 @ 10:00 AM - Download exit window (now available)
dlt-ibapi backfill-batch-calendar-ticks 2025-11-17 \
  --earnings-timing PRE_MARKET \
  --exit

# Result: Downloads ticks from Monday 9-10am for short + long legs
# Status: Entry data ✓ complete, Exit data ✓ complete
```

**Benefits**:
- Download data immediately when available (no waiting)
- Lower memory usage (2 downloads per run vs 4)
- Easy retry of failed windows
- Parallel execution across multiple earnings dates

### Example 6: AFTER_HOURS Progressive Download

```bash
# Friday Nov 14 @ 4:00 PM - Download entry window
dlt-ibapi backfill-batch-calendar-ticks 2025-11-14 \
  --earnings-timing AFTER_HOURS \
  --entry

# Monday Nov 17 @ 10:00 AM - Download exit window (next trading day)
dlt-ibapi backfill-batch-calendar-ticks 2025-11-14 \
  --earnings-timing AFTER_HOURS \
  --exit
```

**Note**: For AFTER_HOURS on Friday, exit window is Monday (next trading day) @ 9-10am.

## Implementation Details

### Files Modified

1. **`src/dlt_ibapi/cli_app.py`**:
   - Added `--earnings-timing` parameter
   - Made `--top-n` optional (defaults to None)
   - Added `--entry` flag (download only entry window)
   - Added `--exit` flag (download only exit window)
   - Added validation: prevent both --entry and --exit simultaneously
   - Updated help text and examples
   - Added validation for earnings_timing values
   - Added earnings timing column to output table

2. **`src/dlt_ibapi/cli/models.py`**:
   - Added `download_entry: bool` field to `BackfillBatchCalendarTicksParams`
   - Added `download_exit: bool` field to `BackfillBatchCalendarTicksParams`
   - Updated docstring to explain window selection logic

3. **`src/dlt_ibapi/cli/batch_ticks.py`**:
   - Added `earnings_timing_filter` parameter to `load_top_n_from_strategy_selection()`
   - Filter earnings DataFrame by `earnings_time` column before processing
   - Include `earnings_timing` in output dictionaries
   - Added future data detection in `execute_backfill_batch_calendar_ticks()`
   - Updated scenario building logic to respect `params.download_entry` and `params.download_exit`
   - Added logging for window selection (download_entry, download_exit)

### Data Flow

```
CLI Command
  ↓
load_top_n_from_strategy_selection()
  ├─ Load earnings for date
  ├─ Filter by earnings_timing (if specified)
  ├─ Filter by symbols (if specified)
  ├─ Filter to tradable earnings (with option data)
  ├─ Run IV ratio ranking backtest
  ├─ Sort by IV ratio descending
  ├─ Take top N (or all if no limit)
  └─ Return spread opportunities with earnings_timing
  ↓
execute_backfill_batch_calendar_ticks()
  ├─ Check for future exit windows (warn user)
  ├─ For each spread:
  │   ├─ Get earnings timing from database
  │   ├─ Calculate entry/exit windows
  │   ├─ Download ticks (short entry, short exit, long entry, long exit)
  │   └─ Track success/failure
  └─ Return batch results
```

## Testing Results

**Test Date**: 2025-11-17

```
PRE_MARKET earnings:  20 total → 16 tradable → 13 with valid IV data
AFTER_HOURS earnings:  8 total →  8 tradable →  5 with valid IV data
UNKNOWN earnings:     15 total →  5 tradable →  3 with valid IV data
```

**Filter validation**:
```python
# PRE_MARKET filter
✓ Found 13 PRE_MARKET opportunities (all have earnings_timing='PRE_MARKET')

# AFTER_HOURS filter
✓ Found 5 AFTER_HOURS opportunities (all have earnings_timing='AFTER_HOURS')

# No filter
✓ Found 21 total opportunities (13 + 5 + 3 = 21)
```

**Future data detection**:
```
2025-11-17 19:27:14 [warning] future_exit_windows_detected
    symbols=['TCOM', 'LFMD', 'ACM', 'XP', 'HP']
    count=5
    message="Some symbols have exit windows in the future - data may not be available yet"
```

**Window selection validation**:
```bash
# Both flags error (correct)
$ dlt-ibapi backfill-batch-calendar-ticks 2025-11-17 --entry --exit
Error: Cannot specify both --entry and --exit. Choose one or omit both for all windows.

# Entry only (correct)
$ dlt-ibapi backfill-batch-calendar-ticks 2025-11-17 --entry
# Downloads: short entry, long entry (2 total)

# Exit only (correct)
$ dlt-ibapi backfill-batch-calendar-ticks 2025-11-17 --exit
# Downloads: short exit, long exit (2 total)

# No flags (correct - default)
$ dlt-ibapi backfill-batch-calendar-ticks 2025-11-17
# Downloads: short entry, short exit, long entry, long exit (4 total)
```

## Migration Guide

### Before (Old Workflow)

```bash
# Required to specify --top-n
dlt-ibapi backfill-batch-calendar-ticks 2025-11-17 --top-n 100

# No way to filter by timing
# Mixed PRE_MARKET and AFTER_HOURS in results
# Some downloads would fail (future data)
```

### After (New Workflow)

```bash
# Day 1 (earnings day): Process PRE_MARKET only
dlt-ibapi backfill-batch-calendar-ticks 2025-11-17 --earnings-timing PRE_MARKET

# Day 2 (day after): Process AFTER_HOURS
dlt-ibapi backfill-batch-calendar-ticks 2025-11-17 --earnings-timing AFTER_HOURS

# Optional: Limit to top opportunities
dlt-ibapi backfill-batch-calendar-ticks 2025-11-17 \
  --earnings-timing PRE_MARKET \
  --top-n 10
```

### Progressive (NEW - Recommended for Production)

```bash
# Friday 4pm: Download entry window for Monday PRE_MARKET earnings
dlt-ibapi backfill-batch-calendar-ticks 2025-11-17 \
  --earnings-timing PRE_MARKET \
  --entry

# Monday 10am: Download exit window for Monday PRE_MARKET earnings
dlt-ibapi backfill-batch-calendar-ticks 2025-11-17 \
  --earnings-timing PRE_MARKET \
  --exit

# Benefits:
# - Data downloaded immediately when available
# - Lower memory per run (2 downloads vs 4)
# - Easy retry of failed windows
# - Can run multiple earnings dates in parallel
```

## Backward Compatibility

✅ **Fully backward compatible**

- Existing commands continue to work (--symbols, --top-n still supported)
- New parameters are optional
- No breaking changes to function signatures or data formats

## Future Enhancements

Potential improvements for future iterations:

1. **Auto-detect timing**: Automatically skip AFTER_HOURS earnings if exit window is in future
2. **Retry mechanism**: Automatically retry failed symbols after 24 hours
3. **Schedule support**: Integration with scheduler to automatically run at appropriate times
4. **Batch status tracking**: Track which earnings dates have been fully processed

## Conclusion

These improvements solve the original issues:

1. ✅ **Separate processing**: Use `--earnings-timing` to process PRE_MARKET and AFTER_HOURS separately
2. ✅ **Optional limits**: Omit `--top-n` to process all symbols
3. ✅ **Future data detection**: Automatic warning when exit windows are in the future
4. ✅ **Better visibility**: Earnings timing shown in output tables
5. ✅ **Progressive downloads**: Use `--entry` and `--exit` to download windows separately as data becomes available

**Recommended workflow for production (2025-11-17 PRE_MARKET earnings)**:

```bash
# Friday Nov 14 @ 4:00 PM - Download entry window (available now)
dlt-ibapi backfill-batch-calendar-ticks 2025-11-17 \
  --earnings-timing PRE_MARKET \
  --entry

# Monday Nov 17 @ 10:00 AM - Download exit window (available now)
dlt-ibapi backfill-batch-calendar-ticks 2025-11-17 \
  --earnings-timing PRE_MARKET \
  --exit
```

**Alternative: All-at-once (simple but must wait for all data)**:

```bash
# Monday Nov 17 @ 10:00 AM - Download both entry and exit windows
dlt-ibapi backfill-batch-calendar-ticks 2025-11-17 --earnings-timing PRE_MARKET
```

**Key Advantages of Progressive Approach**:
- ⚡ **Immediate data access**: Download entry data 3+ days before earnings
- 💾 **Lower memory**: 2 downloads per run vs 4
- 🔄 **Easy retries**: Re-run failed windows independently
- 📅 **Parallel execution**: Run multiple earnings dates simultaneously
