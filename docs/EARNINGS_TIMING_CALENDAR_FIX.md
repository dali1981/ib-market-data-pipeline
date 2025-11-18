# Earnings Timing Calculator - Market Calendar Fix

**Date**: 2025-11-17
**Status**: Fixed

## Problem

The `EarningsTimingCalculator` was using naive date arithmetic (`timedelta(days=1)`) to calculate entry/exit windows, which didn't respect market calendars (weekends and holidays).

**Example failure**:
- Earnings: **Monday Nov 17, 2025** (PRE_MARKET)
- Old behavior: Entry = **Sunday Nov 16** (market closed!)
- Correct behavior: Entry = **Friday Nov 14** (last trading day)

## Root Cause

In `src/dlt_ibapi/strategies/earnings_timing.py`, the `calculate_windows()` method used:

```python
if earnings_time == "PRE_MARKET":
    entry_date = earnings_date - timedelta(days=1)  # ❌ Naive!
    exit_date = earnings_date
elif earnings_time == "AFTER_HOURS":
    entry_date = earnings_date
    exit_date = earnings_date + timedelta(days=1)  # ❌ Naive!
```

This breaks when earnings fall on:
- **Monday** → Entry tries to use Sunday (PRE_MARKET)
- **Friday** → Exit tries to use Saturday (AFTER_HOURS)
- **Day after holiday** → Entry tries to use holiday

## Solution

Updated `calculate_windows()` to use the existing `MarketCalendar` utilities:

```python
from ..backfill.market_calendar import get_previous_trading_day, get_market_calendar

if earnings_time == "PRE_MARKET":
    # PRE_MARKET: Enter previous trading day, exit same day
    entry_date = get_previous_trading_day(earnings_date, exchange="NYSE")
    exit_date = earnings_date
elif earnings_time == "AFTER_HOURS":
    # AFTER_HOURS: Enter same day, exit next trading day
    cal = get_market_calendar("NYSE")
    entry_date = earnings_date
    next_day = cal.get_next_trading_day(earnings_date, skip_count=1)
    if next_day is None:
        raise ValueError(f"Cannot find next trading day after {earnings_date}")
    exit_date = next_day
```

## Testing

### Test Case 1: Monday PRE_MARKET Earnings

```python
from datetime import date
from dlt_ibapi.strategies import EarningsTimingCalculator

calc = EarningsTimingCalculator()
windows = calc.calculate_windows(date(2025, 11, 17), "PRE_MARKET")

# Result:
# Entry: 2025-11-14 15:00 to 2025-11-14 16:00 (Friday)
# Exit:  2025-11-17 09:00 to 2025-11-17 10:00 (Monday)
```

**✓ Correct**: Entry is on Friday (last trading day before Monday earnings)

### Test Case 2: Friday AFTER_HOURS Earnings

```python
windows = calc.calculate_windows(date(2025, 11, 14), "AFTER_HOURS")

# Result:
# Entry: 2025-11-14 15:00 to 2025-11-14 16:00 (Friday)
# Exit:  2025-11-17 09:00 to 2025-11-17 10:00 (Monday)
```

**✓ Correct**: Exit is on Monday (next trading day after Friday earnings)

### Test Case 3: Day After Holiday

The fix also handles holidays like Thanksgiving:

```python
# If earnings are on Black Friday (Nov 28, market closed):
# get_previous_trading_day() will return Nov 26 (day before Thanksgiving)
```

## Impact

**Files Modified**:
- `src/dlt_ibapi/strategies/earnings_timing.py`

**Commands Affected**:
- `dlt-ibapi backfill-batch-calendar-ticks`
- Any code using `EarningsTimingCalculator`

**Behavior Changes**:
- **PRE_MARKET**: Entry date now respects market calendar (Friday for Monday earnings)
- **AFTER_HOURS**: Exit date now respects market calendar (Monday for Friday earnings)
- Tick data downloads will now request correct date ranges

## Related Issues

This fix resolves the problem where:
1. Batch tick backfill was trying to download data from weekends
2. Notebook `07_refined_pnl_with_tick_data.ipynb` couldn't find tick data (wrong dates)
3. NKLR tick data was downloaded for Sunday instead of Friday

## Dependencies

Uses existing market calendar utilities:
- `dlt_ibapi.backfill.market_calendar.get_previous_trading_day()`
- `dlt_ibapi.backfill.market_calendar.get_market_calendar()`
- `pandas_market_calendars` (already a dependency)

## Migration

**No breaking changes** - this is a bug fix that makes the behavior correct.

Existing code using `EarningsTimingCalculator` will automatically get the correct behavior after upgrading.

## Future Enhancements

Potential improvements:
1. Support configurable exchange (currently hardcoded to NYSE)
2. Add validation to warn if earnings date itself is not a trading day
3. Cache calendar lookups for performance (already done in `market_calendar.py`)

## Example: Full Workflow

```bash
# Now works correctly for Monday earnings:
dlt-ibapi backfill-batch-calendar-ticks 2025-11-17 \\
  --earnings-timing PRE_MARKET \\
  --top-n 10

# Will download tick data from:
# - Entry: Friday Nov 14, 3-4pm (not Sunday!)
# - Exit: Monday Nov 17, 9-10am
```

## Verification

To verify the fix is working:

```bash
uv run python -c "
from datetime import date
from dlt_ibapi.strategies import EarningsTimingCalculator

calc = EarningsTimingCalculator()
windows = calc.calculate_windows(date(2025, 11, 17), 'PRE_MARKET')
print(f'Entry: {windows.entry}')
print(f'Exit: {windows.exit}')

# Should print:
# Entry: 2025-11-14 15:00 to 2025-11-14 16:00
# Exit: 2025-11-17 09:00 to 2025-11-17 10:00
"
```
