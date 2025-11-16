# Calendar Spread Backtest Behavior

## System Verification (2025-11-16)

This document clarifies the expected behavior of calendar spread backtests when option data is missing or incomplete.

## Key Finding: System Working as Designed

**Investigation Result**: The batch calendar spread backtest system (`run_batch_calendar_spread_backtest()`) is functioning correctly. Warnings about missing option data reflect actual data availability issues, not bugs in the strike selection logic.

## Nearest Strike Selection Logic

The `_find_nearest_available_strike()` function in `src/dlt_ibapi/strategies/batch.py` correctly implements fallback logic:

1. **Exact Match**: If target ATM strike exists → use it
2. **Nearest Strike**: If target strike doesn't exist → find closest available strike
3. **Bar Size Fallback**: If preferred bar size unavailable → use any available bar size
4. **No Data**: If no strikes available → return None and skip symbol

### Example: CTRM (Working Correctly)

```
Processing CTRM - 2025-11-13 (UNKNOWN)...
  Spot: $1.93, ATM Strike: $2 → Using $2.5 (nearest available)
  ✓ Calendar spread: Entry=$25.00, P&L=$-20.00
```

**What happened**:
- Spot price: $1.93
- ATM strike calculated: $2.00
- Available strikes: `[2.5]` (only $2.5 available)
- **System correctly used $2.5** (nearest available)

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
- **Total tradable earnings**: 44 symbols
- **Successful backtests**: 23 (52%)
- **Failed backtests**: 21 (48%)

**Failure reasons** (all legitimate data issues):
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
