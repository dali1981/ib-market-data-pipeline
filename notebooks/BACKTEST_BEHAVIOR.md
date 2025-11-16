# Calendar Spread Backtest Behavior

## System Verification and Fix (2025-11-16)

This document clarifies the expected behavior of calendar spread backtests when option data is missing or incomplete.

## Update: Strike Selection Fixed

**Investigation Result**: Found and fixed a bug in strike selection logic where symbols were incorrectly rejected when ATM strike didn't have ≥2 expirations, even if other strikes did.

**Fix Applied**: Now searches ALL available strikes to find the best one with ≥2 expirations after earnings, falling back from ATM to nearest alternative.

## Strike Selection Logic (Fixed 2025-11-16)

The `_find_best_strike_with_sufficient_expirations()` function in `src/dlt_ibapi/strategies/batch.py` implements intelligent fallback logic:

1. **Calculate ATM**: Determine ideal at-the-money strike from spot price
2. **Count Expirations**: For each available strike, count expirations AFTER earnings date
3. **Filter Valid Strikes**: Keep only strikes with ≥2 expirations (needed for calendar spread)
4. **Prefer ATM**: If ATM strike has ≥2 expirations → use it
5. **Fallback to Nearest**: If ATM insufficient → use nearest strike with ≥2 expirations
6. **No Valid Strikes**: If no strike has ≥2 expirations → return None and skip symbol

### Example: BZH (Fixed - Previously Failed)

**Before Fix**:
```
Processing BZH - 2025-11-13 (AFTER_HOURS)...
  Spot: $21.40, ATM Strike: $21 ✓
  ⚠️  Insufficient expirations (need 2, got 1)
```

**After Fix**:
```
Processing BZH - 2025-11-13 (AFTER_HOURS)...
  Spot: $21.40, ATM Strike: $21 → Using $22.0 (best with ≥2 expirations)
  ✓ Calendar spread (Spot: $21.40, Strike: $22.0): Entry=$35.00, P&L=$40.00
```

**What happened**:
- Spot price: $21.40
- ATM strike calculated: $21.00
- Strike $21 expirations: only Nov 21 (1 expiration) ❌
- Strike $22 expirations: Nov 21, Dec 19 (2 expirations) ✓
- **System correctly used $22** (nearest with ≥2 expirations)

### Example: CTRM (Working Correctly)

```
Processing CTRM - 2025-11-13 (UNKNOWN)...
  Spot: $1.93, ATM Strike: $2 → Using $2.5 (best with ≥2 expirations)
  ✓ Calendar spread (Spot: $1.93, Strike: $2.5): Entry=$25.00, P&L=$-20.00
```

**What happened**:
- Spot price: $1.93
- ATM strike calculated: $2.00
- Available strikes: only `[2.5]` with ≥2 expirations
- **System correctly used $2.5** (only valid strike)

### Example: BNT (Working Correctly)

```
Processing BNT - 2025-11-13 (UNKNOWN)...
  Spot: $43.40, ATM Strike: $43
  ⚠️  No option data for C options
```

**What happened**:
- Spot price: $43.40
- ATM strike calculated: $43.00
- Available call options: **NONE** (only 1 put option at $40 strike)
- **System correctly skipped** (no call data exists)

**Verification**:
```python
from dlt_ibapi.repositories import OptionBarsReader

option_reader = OptionBarsReader(database_path='./data_delta', dataset_name='options')
contracts = option_reader.get_contracts_for_underlying(underlying='BNT', bar_size=None)

# Result: 1 contract total
#   - 0 calls
#   - 1 put at strike $40
```

## Why Some Symbols Fail

Symbols fail backtesting for legitimate data availability reasons:

| Symbol | Issue | Explanation |
|--------|-------|-------------|
| BNT | "No option data for C options" | Only has put options in data |
| CRVO | "No option data for C options" | No option contracts at all |
| DNTH | "No option data for C options" | No option contracts at all |
| HIHO | "No option data for C options" | No option contracts at all |

## Expected Behavior Summary

The batch backtest correctly handles these scenarios:

1. **Exact ATM Strike Available**: Use it directly
2. **Nearest Strike Available**: Find and use closest strike (with message "Using $X (nearest available)")
3. **Wrong Option Type**: Skip with "No option data for {C/P} options"
4. **No Option Data**: Skip with "No option data for {C/P} options"
5. **Missing Price Data**: Skip with "Missing entry/exit prices"
6. **Degenerate Spread**: Skip with "Degenerate spread (entry_cost=...)"

## Code Reuse Architecture

Both notebooks 04 and 06 use the **same underlying function**:

```python
from dlt_ibapi.strategies.batch import run_batch_calendar_spread_backtest

# Notebook 04: Without IV calculation
results_df = run_batch_calendar_spread_backtest(
    earnings_df=tradable_earnings,
    option_reader=option_reader,
    equity_reader=equity_reader,
    option_type='C',
    calculate_iv=False  # No IV metrics
)

# Notebook 06: With IV calculation
results_df = run_batch_calendar_spread_backtest(
    earnings_df=tradable_earnings,
    option_reader=option_reader,
    equity_reader=equity_reader,
    option_type='C',
    calculate_iv=True  # Include IV metrics
)
```

**Benefits**:
- Single implementation of backtest logic
- Fixes apply to both notebooks automatically
- Consistent behavior across notebooks
- No code duplication

## Success Rate Analysis

For earnings on 2025-11-13:

**Before Fix**:
- Total tradable earnings: 44 symbols
- Successful backtests: 23 (52%)
- Failed backtests: 21 (48%)

**After Fix**:
- Total tradable earnings: 44 symbols
- **Successful backtests: 26 (59.1%)**
- **Failed backtests: 18 (40.9%)**

**Improvement**: +3 backtests successfully added (BZH, BNTC, and 1 more)

**Remaining failure reasons** (all legitimate data issues):
- Missing call option data (most common)
- Missing spot price data
- Insufficient expirations (< 2 required)
- Missing entry/exit price bars

## Conclusion

The warning messages like "No option data for C options" are **informative and accurate**, not errors. They correctly identify symbols where:
- Option data wasn't backfilled
- Only put options were backfilled
- Symbol doesn't have options available in IB

The nearest strike selection logic is working correctly as evidenced by CTRM and other successful backtests.

## Future Improvements

To reduce warnings and increase success rate:

1. **Pre-filter symbols**: Remove symbols without call options before running backtest
2. **Batch backfill**: Ensure all tradable earnings symbols have option data backfilled
3. **Option availability check**: Query IB for option availability before attempting backfill
4. **Better progress reporting**: Distinguish between "no data" vs "data incomplete" warnings

**Note**: These are data preparation improvements, not bug fixes. The backtest logic is working correctly.
