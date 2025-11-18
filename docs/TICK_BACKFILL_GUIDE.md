# Tick Data Backfill Guide

## Overview

This guide covers downloading tick-by-tick data for calendar spread analysis around earnings announcements.

## Current State (What Exists)

### ✅ Basic Command
```bash
dlt-ibapi backfill-ticks SYMBOL EXPIRY STRIKE RIGHT --start "..." --end "..."
```

**Limitations**:
- Only downloads ONE option contract at a time
- Must manually specify both entry and exit windows (2 commands per leg)
- Must manually specify both short and long legs (4 commands total per symbol)
- Must manually look up earnings timing from database
- No batch support for multiple symbols

### ✅ Components Built
- `EarningsTimingCalculator` class - calculates entry/exit windows
- `BackfillTicksParams` / `BackfillTicksResult` - Pydantic models
- `backfill_option_ticks_bid_ask` DLT resource - fetches tick data
- `execute_backfill_ticks` - business logic

## What Exists (✅ Implemented)

### ✅ Batch Calendar Spread Tick Backfill

**Goal**: Single command to download ALL tick data for multiple calendar spreads:
- Both legs (short + long expirations)
- Both windows (entry + exit)
- Auto-fetch earnings timing from database

**Command**: `dlt-ibapi backfill-batch-calendar-ticks`

**Example Usage**:
```bash
# Download ticks for specific symbols (runs IV ranking, gets all matches)
dlt-ibapi backfill-batch-calendar-ticks 2025-11-17 --symbols "ARMK,JJSF,ACM"

# Download ticks for TOP 10 by IV ratio
dlt-ibapi backfill-batch-calendar-ticks 2025-11-17 --top-n 10

# This executes 4 tick downloads per symbol:
# For each symbol:
#   1. Short leg - Entry window (auto-calculated from earnings timing)
#   2. Short leg - Exit window (auto-calculated from earnings timing)
#   3. Long leg - Entry window (auto-calculated from earnings timing)
#   4. Long leg - Exit window (auto-calculated from earnings timing)
```

**Features**:
- **Comma-separated symbols**: `--symbols "ARMK,JJSF,ACM"` for specific underlyings
- **Top N selection**: `--top-n 10` for best opportunities by IV ratio
- Automatically runs IV ratio ranking (backtest with IV calculation)
- Fetches earnings timing from database (PRE_MARKET/AFTER_HOURS)
- Calculates entry/exit windows based on earnings timing
- Handles UNKNOWN earnings timing (raises error to force resolution)
- Downloads ticks for all 4 scenarios per spread
- Graceful error handling per symbol (continues on failure)
- Summary table showing IV ratios and expected P&L

## What's Missing (TODO)

### ❌ Notebook 07 Batch Processing

**Goal**: Automate refined P&L analysis for multiple trades

**Current state**: Notebook 07 is hardcoded for a single trade

**Proposed**: Batch mode that accepts list of trades
```python
# Load tick data and run analysis for all trades from strategy selection
trades = load_trades_from_strategy_selection(earnings_date='2025-11-17', top_n=10)

results = []
for trade in trades:
    pnl_result = analyze_trade_with_ticks(trade)
    results.append(pnl_result)

# Generate summary statistics
summary_df = pd.DataFrame(results)
print(summary_df[['symbol', 'tick_based_pnl', 'bar_based_pnl', 'spread_cost']])
```

**Status**: Not implemented yet. Currently requires manual parameter entry per trade.

### ✅ Auto-Fetch Earnings Timing

**Status**: Implemented in `batch_ticks.py`

The `get_earnings_timing()` helper function automatically:
- Fetches earnings timing from database for the symbol/date
- Validates timing is not UNKNOWN (raises error if needed)
- Returns PRE_MARKET or AFTER_HOURS for window calculation

**Used by**: `backfill-batch-calendar-ticks` command

**Note**: The single-contract `backfill-ticks` command still requires manual `--earnings-time` specification. This is by design for explicit control.

### ✅ Strategy Integration (COMPLETE)

**Goal**: Seamless workflow from strategy selection to tick download

**Status**: ✅ Implemented

**Usage**:
```bash
# Auto-load TOP 10 from IV ratio ranking
dlt-ibapi backfill-batch-calendar-ticks 2025-11-17 --top-n 10

# Filter to specific symbols
dlt-ibapi backfill-batch-calendar-ticks 2025-11-17 --symbols "ARMK,JJSF,ACM"
```

This automatically:
1. Loads earnings for the date
2. Filters to tradable symbols (with option data)
3. Runs batch backtest with IV calculation
4. Ranks by IV ratio
5. Selects top N (or all matching symbols)
6. Downloads ticks for all 4 scenarios per symbol

## Implementation Plan

### ✅ Phase 1: Auto-Fetch Earnings Timing (COMPLETE)

**File**: `src/dlt_ibapi/cli/batch_ticks.py`

Implemented `get_earnings_timing()` helper function:
```python
def get_earnings_timing(
    symbol: str,
    earnings_date: date,
    database_path: Path,
    dataset_name: str = "earnings",
) -> str:
    """
    Fetch earnings timing from database.

    Raises:
        ValueError: If earnings not found or timing is UNKNOWN
    """
    reader = EarningsCalendarReader(str(database_path), dataset_name)
    earnings = reader.get_earnings_on_date(earnings_date)

    symbol_earnings = earnings[earnings['symbol'] == symbol]
    if symbol_earnings.empty:
        raise ValueError(f"No earnings found for {symbol} on {earnings_date}")

    timing = symbol_earnings.iloc[0]['earnings_time']

    # Validate timing is not UNKNOWN
    if timing == 'UNKNOWN':
        raise ValueError(
            f"Earnings timing for {symbol} on {earnings_date} is UNKNOWN. "
            f"Please update earnings data with correct timing."
        )

    return timing
```

**Status**: Used by `backfill-batch-calendar-ticks` command.

### ✅ Phase 2: Batch Calendar Spread Command (COMPLETE)

**File**: `src/dlt_ibapi/cli/batch_ticks.py`

Implemented `execute_backfill_batch_calendar_ticks()`:
```python
def execute_backfill_batch_calendar_ticks(
    params: BackfillBatchCalendarTicksParams,
    connection_config: Optional[any] = None,
) -> BackfillBatchCalendarTicksResult:
    """
    Execute batch calendar spread tick backfill.

    Downloads tick data for multiple calendar spreads.
    For each spread, downloads:
    - Short leg: entry + exit windows
    - Long leg: entry + exit windows
    """
    calculator = EarningsTimingCalculator()

    for symbol_data in params.symbols:
        # Fetch earnings timing from database
        earnings_time = get_earnings_timing(...)

        # Calculate windows
        windows = calculator.calculate_windows(...)

        # Download ticks for 4 scenarios
        scenarios = [
            ('short', short_expiry, 'entry', windows.entry),
            ('short', short_expiry, 'exit', windows.exit),
            ('long', long_expiry, 'entry', windows.entry),
            ('long', long_expiry, 'exit', windows.exit),
        ]

        for leg, expiry, window_type, window in scenarios:
            result = execute_backfill_ticks(tick_params, connection_config)
```

**Models** (`src/dlt_ibapi/cli/models.py`):
- `BackfillBatchCalendarTicksParams` - Added
- `BackfillBatchCalendarTicksResult` - Added

**CLI Command** (`src/dlt_ibapi/cli_app.py`):
```python
@app.command()
def backfill_batch_calendar_ticks(
    earnings_date: str = typer.Argument(..., help="Earnings date (YYYY-MM-DD)"),
    symbols_json: Optional[str] = typer.Option(None, "--symbols", help='JSON list of spreads'),
    top_n: Optional[int] = typer.Option(None, "--top-n", help="Auto-load top N from strategy selection"),
    # ... other options
):
    """
    Batch download tick data for multiple calendar spreads.

    Example:
        dlt-ibapi backfill-batch-calendar-ticks 2025-11-17 \\
          --symbols '[{"symbol": "ARMK", "strike": 38.0, "short_expiry": "2025-11-21", "long_expiry": "2025-12-19", "right": "C"}]'
    """
```

**Status**: ✅ Command completed and functional

### ✅ Phase 3: Strategy Integration (COMPLETE)

**Implemented**:
- `--top-n N` to auto-load top N opportunities
- `--symbols "SYM1,SYM2,SYM3"` to filter specific underlyings
- Runs IV ratio ranking internally
- Returns all 4 tick datasets per symbol

**Usage**:
```bash
# Top N globally
dlt-ibapi backfill-batch-calendar-ticks 2025-11-17 --top-n 10

# Specific symbols
dlt-ibapi backfill-batch-calendar-ticks 2025-11-17 --symbols "ARMK,JJSF,ACM"
```

## Current Workarounds

### Manual Workflow (4 commands per spread)

For ARMK (PRE_MARKET earnings on 2025-11-17):

```bash
# Short leg - Entry (2025-11-16 3-4pm)
dlt-ibapi backfill-ticks ARMK 20251121 38.0 C \\
  --earnings-date 2025-11-17 \\
  --earnings-time PRE_MARKET \\
  --window entry

# Short leg - Exit (2025-11-17 9-10am)
dlt-ibapi backfill-ticks ARMK 20251121 38.0 C \\
  --earnings-date 2025-11-17 \\
  --earnings-time PRE_MARKET \\
  --window exit

# Long leg - Entry (2025-11-16 3-4pm)
dlt-ibapi backfill-ticks ARMK 20251219 38.0 C \\
  --earnings-date 2025-11-17 \\
  --earnings-time PRE_MARKET \\
  --window entry

# Long leg - Exit (2025-11-17 9-10am)
dlt-ibapi backfill-ticks ARMK 20251219 38.0 C \\
  --earnings-date 2025-11-17 \\
  --earnings-time PRE_MARKET \\
  --window exit
```

### Shell Script Generation from Notebook

The notebook already generates these commands for TOP 10:
```python
# See notebooks/06c_iv_ratio_ranking_adjusted_times.ipynb
# Cell: "generate-tick-commands"
# Output: download_top10_ticks.sh
```

Run with:
```bash
chmod +x download_top10_ticks.sh
./download_top10_ticks.sh
```

## Summary of Implementation

### ✅ Completed Features

1. **Phase 1: Auto-fetch earnings timing** - ✅ COMPLETE
   - Fetches timing from database automatically
   - Validates UNKNOWN timing (raises error)

2. **Phase 2: Calendar spread batch command** - ✅ COMPLETE
   - Single command for both legs + both windows
   - 4 commands → 1 command per symbol
   - Batch processing for multiple symbols

3. **Phase 3: Strategy integration** - ✅ COMPLETE
   - `--top-n` for best opportunities
   - `--symbols` for specific underlyings
   - Automatic IV ratio ranking

### ⚠️ Remaining Work

**Notebook 07 Batch Processing**:
- Parameterize for multiple trades
- Auto-load from strategy selection
- Generate summary statistics

## Files Created/Updated

### Created:
- [x] `src/dlt_ibapi/cli/batch_ticks.py` - Business logic for batch backfill
- [x] `docs/TICK_BACKFILL_GUIDE.md` - This file (documentation)

### Updated:
- [x] `src/dlt_ibapi/cli/models.py` - Added BackfillBatchCalendarTicksParams/Result
- [x] `src/dlt_ibapi/cli_app.py` - Added backfill-batch-calendar-ticks command
- [x] `src/dlt_ibapi/strategies/earnings_timing.py` - Fixed UNKNOWN handling (raises error)

### Not Updated (By Design):
- `src/dlt_ibapi/cli_app.py` - Kept --earnings-time required in backfill-ticks (explicit control)
  - Batch command has auto-fetch, single command keeps manual specification

## Related Files

- `src/dlt_ibapi/strategies/earnings_timing.py` - EarningsTimingCalculator class
- `src/dlt_ibapi/backfill/tick_resources.py` - DLT resource for tick data
- `src/dlt_ibapi/repositories/earnings_calendar.py` - EarningsCalendarReader
- `notebooks/06c_iv_ratio_ranking_adjusted_times.ipynb` - Shell script generator
