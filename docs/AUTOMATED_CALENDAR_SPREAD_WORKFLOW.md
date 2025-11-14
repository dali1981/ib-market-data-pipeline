# Automated Calendar Spread Data Collection Workflow

**Status**: Design Document
**Date**: 2025-11-13
**Purpose**: Complete automated pipeline for collecting calendar spread backtest data

---

## Executive Summary

**Problem**: Current manual workflow is broken for 300+ earnings symbols:
1. Requires manual spot price lookup for each symbol
2. Cannot specify exact expirations (only DTE ranges)
3. No batch automation
4. Tedious and error-prone

**Solution**: Fully automated Python orchestrator that:
1. Reads earnings symbols from calendar
2. Resolves contracts and captures snapshots
3. Backfills equity bars for spot prices
4. Selects calendar spread expirations from snapshot data
5. Backfills option bars for front + back legs (parallel processing)
6. Validates and reports completeness

**Timeline**: 48 minutes for 100 symbols (5 parallel workers)

---

## Current System Architecture

```
┌──────────────────────────────────────────────────────────────┐
│                  DATA COLLECTION PIPELINE                     │
├──────────────────────────────────────────────────────────────┤
│                                                               │
│  1. EARNINGS CALENDAR (Manual Load)                          │
│     └─ dlt-ibapi load-earnings earnings.json                 │
│                                                               │
│  2. CONTRACT RESOLUTION (Pre-population)                      │
│     └─ dlt-ibapi resolve-contracts --earnings-date YYYY-MM-DD│
│                                                               │
│  3. OPTION CHAIN SNAPSHOTS (Metadata)                         │
│     └─ dlt-ibapi snapshot --earnings-date YYYY-MM-DD         │
│        Captures: expirations[], strikes[]                     │
│                                                               │
│  4. EQUITY BARS (Spot Prices)                                 │
│     └─ dlt-ibapi backfill-equity SYMBOLS                     │
│        Purpose: Get current prices                           │
│                                                               │
│  5. OPTION BARS (Historical Pricing) ← BOTTLENECK            │
│     └─ dlt-ibapi backfill-options SYMBOL SPOT_PRICE          │
│        Problem: Requires manual spot price per symbol        │
│        Current: No batch automation                          │
│                                                               │
└──────────────────────────────────────────────────────────────┘
```

---

## Proposed Automated Workflow

```
┌────────────────────────────────────────────────────────────────┐
│         AUTOMATED CALENDAR SPREAD DATA COLLECTOR               │
├────────────────────────────────────────────────────────────────┤
│                                                                 │
│  INPUT: earnings_date = 2025-11-13                             │
│                                                                 │
│  ┌───────────────────────────────────────────────────────┐    │
│  │ STEP 1: Load Earnings Symbols                         │    │
│  │ ───────────────────────────────                       │    │
│  │ • Query earnings calendar for 2025-11-13              │    │
│  │ • Filter: earnings_time (optional: PRE_MARKET, etc.)  │    │
│  │ • Output: [AAPL, MSFT, DIS, ...]                     │    │
│  └───────────────────────────────────────────────────────┘    │
│                          ↓                                      │
│  ┌───────────────────────────────────────────────────────┐    │
│  │ STEP 2: Resolve Contracts                             │    │
│  │ ───────────────────────                               │    │
│  │ • Pre-populate contract cache                         │    │
│  │ • Handle invalid symbols gracefully                   │    │
│  │ • Cache location: .dlt-ibapi/cache/contracts/        │    │
│  └───────────────────────────────────────────────────────┘    │
│                          ↓                                      │
│  ┌───────────────────────────────────────────────────────┐    │
│  │ STEP 3: Capture Snapshots                             │    │
│  │ ───────────────────────                               │    │
│  │ • Run: snapshot --earnings-date 2025-11-13            │    │
│  │ • Captures: expirations[], strikes[] per symbol       │    │
│  │ • DTE filter: 0 to 60 (covers front + back legs)     │    │
│  └───────────────────────────────────────────────────────┘    │
│                          ↓                                      │
│  ┌───────────────────────────────────────────────────────┐    │
│  │ STEP 4: Backfill Equity Bars                          │    │
│  │ ───────────────────────                               │    │
│  │ • Batch backfill: backfill-equity SYMBOL1 SYMBOL2...  │    │
│  │ • Date range: earnings_date - 25 days to today       │    │
│  │ • Purpose: Get spot prices for option backfill        │    │
│  └───────────────────────────────────────────────────────┘    │
│                          ↓                                      │
│  ┌───────────────────────────────────────────────────────┐    │
│  │ STEP 5: Extract Spot Prices                           │    │
│  │ ───────────────────────                               │    │
│  │ FOR EACH symbol:                                       │    │
│  │   • Query equity bars (latest close price)            │    │
│  │   • Output: {AAPL: 150.0, MSFT: 380.0, ...}          │    │
│  └───────────────────────────────────────────────────────┘    │
│                          ↓                                      │
│  ┌───────────────────────────────────────────────────────┐    │
│  │ STEP 6: Select Calendar Spread Expirations            │    │
│  │ ───────────────────────────────────                   │    │
│  │ FOR EACH symbol:                                       │    │
│  │   • Read snapshot expirations[]                       │    │
│  │   • Calculate DTE from earnings_date                  │    │
│  │   • Select front_expiry: First in DTE range (14-25)   │    │
│  │   • Select back_expiry: First in DTE range (35-60)    │    │
│  │   • Output: {symbol: (front_exp, back_exp, spot)}    │    │
│  └───────────────────────────────────────────────────────┘    │
│                          ↓                                      │
│  ┌───────────────────────────────────────────────────────┐    │
│  │ STEP 7: Batch Backfill Option Bars (PARALLEL)         │    │
│  │ ───────────────────────────────────                   │    │
│  │ FOR EACH symbol (5 workers in parallel):              │    │
│  │                                                         │    │
│  │   Front Leg:                                           │    │
│  │   └─ backfill-options SYMBOL SPOT_PRICE \            │    │
│  │       --min-dte 14 --max-dte 25 \                    │    │
│  │       --mode atm --k-strikes 3                        │    │
│  │                                                         │    │
│  │   Back Leg:                                            │    │
│  │   └─ backfill-options SYMBOL SPOT_PRICE \            │    │
│  │       --min-dte 35 --max-dte 60 \                    │    │
│  │       --mode atm --k-strikes 3                        │    │
│  │                                                         │    │
│  │ • ThreadPoolExecutor for parallel processing          │    │
│  │ • Error handling: Log and continue                    │    │
│  └───────────────────────────────────────────────────────┘    │
│                          ↓                                      │
│  ┌───────────────────────────────────────────────────────┐    │
│  │ STEP 8: Validate & Report                             │    │
│  │ ───────────────────────                               │    │
│  │ • Check: All symbols have front + back leg data       │    │
│  │ • Report: Success/failure counts                      │    │
│  │ • Export: Summary CSV for review                      │    │
│  └───────────────────────────────────────────────────────┘    │
│                                                                 │
│  OUTPUT:                                                        │
│  ├─ ./data/stocks/ (equity bars)                              │
│  ├─ ./data/option_chains/ (snapshots)                         │
│  ├─ ./data/options/ (option bars - front + back legs)         │
│  └─ ./logs/collection_summary_2025-11-13.json                 │
│                                                                 │
└────────────────────────────────────────────────────────────────┘
```

---

## Key Implementation Details

### 1. Spot Price Extraction

```python
def get_spot_price(symbol: str, earnings_date: date) -> float:
    """
    Get current spot price from equity bars.

    Uses latest close price from backfilled equity data.
    """
    equity_reader = EquityBarsReader("./data", "stocks")

    # Get bars from last 7 days
    bars = equity_reader.get_bars(
        symbol=symbol,
        bar_size="1 day",
        start_date=earnings_date - timedelta(days=7),
        end_date=earnings_date,
    )

    if bars.empty:
        raise ValueError(f"No equity data for {symbol}")

    # Return latest close price
    return float(bars.iloc[-1]["close"])
```

### 2. Expiration Selection Logic

```python
def select_calendar_expirations(
    symbol: str,
    earnings_date: date,
    front_dte_range: Tuple[int, int] = (14, 25),
    back_dte_range: Tuple[int, int] = (35, 60),
) -> Tuple[date, date]:
    """
    Select front and back leg expirations from snapshot data.

    Returns:
        (front_expiry, back_expiry)

    Raises:
        ValueError: If no suitable expirations found
    """
    chain_reader = OptionChainSnapshotReader("./data", "option_chains")

    # Get available expirations from latest snapshot
    expirations = chain_reader.get_available_expirations(
        underlying=symbol,
        as_of=date.today(),
    )

    # Calculate DTE from earnings_date (NOT snapshot date)
    exp_with_dte = [
        (exp, (exp - earnings_date).days)
        for exp in expirations
    ]

    # Front leg: First expiration in range
    front_candidates = [
        (exp, dte) for exp, dte in exp_with_dte
        if front_dte_range[0] <= dte <= front_dte_range[1]
    ]

    if not front_candidates:
        raise ValueError(f"No front leg expiration for {symbol}")

    front_expiry = min(front_candidates, key=lambda x: x[1])[0]

    # Back leg: First expiration in range
    back_candidates = [
        (exp, dte) for exp, dte in exp_with_dte
        if back_dte_range[0] <= dte <= back_dte_range[1]
    ]

    if not back_candidates:
        raise ValueError(f"No back leg expiration for {symbol}")

    back_expiry = min(back_candidates, key=lambda x: x[1])[0]

    return (front_expiry, back_expiry)
```

### 3. Batch Processing with Parallelization

```python
from concurrent.futures import ThreadPoolExecutor, as_completed

def backfill_options_batch(
    symbols_data: Dict[str, Dict],  # {symbol: {spot, front_exp, back_exp}}
    earnings_date: date,
    max_workers: int = 5,
) -> Dict:
    """
    Backfill option bars for multiple symbols in parallel.

    Args:
        symbols_data: Dict mapping symbol to {spot_price, front_expiry, back_expiry}
        earnings_date: Earnings announcement date
        max_workers: Number of parallel workers

    Returns:
        Results dict with success/failure counts
    """
    results = {"successful": 0, "failed": 0, "errors": []}

    entry_start = earnings_date - timedelta(days=25)

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        # Submit all backfill tasks
        futures = {}
        for symbol, data in symbols_data.items():
            future = executor.submit(
                backfill_single_symbol,
                symbol=symbol,
                spot_price=data["spot_price"],
                start_date=entry_start,
                end_date=earnings_date,
                front_dte=(14, 25),
                back_dte=(35, 60),
            )
            futures[future] = symbol

        # Collect results as they complete
        for future in as_completed(futures):
            symbol = futures[future]
            try:
                success = future.result()
                if success:
                    results["successful"] += 1
                    print(f"✓ {symbol}")
                else:
                    results["failed"] += 1
                    print(f"✗ {symbol}")
            except Exception as e:
                results["failed"] += 1
                results["errors"].append(f"{symbol}: {str(e)}")
                print(f"✗ {symbol}: {e}")

    return results

def backfill_single_symbol(
    symbol: str,
    spot_price: float,
    start_date: date,
    end_date: date,
    front_dte: Tuple[int, int],
    back_dte: Tuple[int, int],
) -> bool:
    """Backfill front + back legs for a single symbol."""
    # Front leg
    front_params = BackfillOptionsParams(
        underlying=symbol,
        spot_price=spot_price,
        start_date=start_date,
        end_date=end_date,
        selection_mode="atm",
        k_strikes=3,
        min_dte=front_dte[0],
        max_dte=front_dte[1],
        pipeline_name="ib_options",
        dataset_name="options",
    )

    front_result = execute_backfill_options(front_params)
    if not front_result.success:
        return False

    # Back leg
    back_params = BackfillOptionsParams(
        underlying=symbol,
        spot_price=spot_price,
        start_date=start_date,
        end_date=end_date,
        selection_mode="atm",
        k_strikes=3,
        min_dte=back_dte[0],
        max_dte=back_dte[1],
        pipeline_name="ib_options",
        dataset_name="options",
    )

    back_result = execute_backfill_options(back_params)
    return back_result.success
```

---

## Usage Examples

### CLI Command (Automated)

```bash
# Create the automation script
uv run python scripts/collect_calendar_spread_data.py 2025-11-13 \
    --entry-window 10 25 \
    --front-dte 14 25 \
    --back-dte 35 60 \
    --workers 5

# Output:
# ======================================================================
# CALENDAR SPREAD DATA COLLECTION
# ======================================================================
# Earnings Date:    2025-11-13
#
# STEP 1: Loading earnings symbols... Found 100 symbols
# STEP 2: Resolving contracts... 98 successful, 2 failed
# STEP 3: Capturing snapshots... 98 successful
# STEP 4: Backfilling equity bars... Complete
# STEP 5: Selecting expirations... 95 valid, 3 missing
# STEP 6: Backfilling option bars (parallel)...
#   ✓ AAPL (front: 5 contracts, back: 5 contracts)
#   ✓ MSFT (front: 5 contracts, back: 5 contracts)
#   ...
# STEP 7: Validation... 95/95 complete
#
# SUMMARY:
# Total Symbols:    100
# Successful:       95
# Failed:           5 (EMX, BILI, ...)
# Duration:         48 minutes
# ======================================================================
```

### Python API (Programmatic)

```python
from datetime import date
from scripts.collect_calendar_spread_data import (
    CalendarSpreadConfig,
    CalendarSpreadDataCollector,
)

# Configure
config = CalendarSpreadConfig(
    earnings_date=date(2025, 11, 13),
    entry_window_days=(10, 25),
    front_leg_dte=(14, 25),
    back_leg_dte=(35, 60),
    k_strikes=3,
    max_workers=5,
)

# Run collection
collector = CalendarSpreadDataCollector(config)
results = collector.run()

# Check results
print(f"Successful: {results['successful']}/{results['total_symbols']}")
```

---

## Performance Estimates

**For 100 symbols with 25-day entry window:**

| Step | Sequential | Parallel (5 workers) |
|------|-----------|---------------------|
| 1. Load earnings | < 1 sec | < 1 sec |
| 2. Resolve contracts | 5 min | 1 min |
| 3. Capture snapshots | 10 min | 2 min |
| 4. Backfill equity | 20 min | 4 min |
| 5. Select expirations | < 10 sec | < 10 sec |
| 6. Backfill options | 200 min | 40 min |
| 7. Validation | < 30 sec | < 30 sec |
| **TOTAL** | **~4 hours** | **~48 minutes** |

**Assumptions:**
- IB API rate limit: 50 req/sec
- Average 3 sec per contract resolution
- Average 6 sec per snapshot
- Average 2 sec per option bar fetch
- Network latency: 100ms

---

## Daily Automation Setup

### Bash Script

```bash
#!/bin/bash
# ~/auto_collect_calendar_spreads.sh

set -e

cd /Users/mohamedali/trading_project/dlt-ibapi

# Get tomorrow's earnings date
TOMORROW=$(date -v+1d +%Y-%m-%d)

echo "[$TOMORROW] Starting calendar spread data collection"

# Run automated collector
uv run python scripts/collect_calendar_spread_data.py $TOMORROW \
    --entry-window 10 25 \
    --front-dte 14 25 \
    --back-dte 35 60 \
    --workers 5 \
    2>&1 | tee logs/collection_$TOMORROW.log

echo "[$TOMORROW] Complete"
```

### Cron Setup

```bash
# Edit crontab
crontab -e

# Add: Run daily at 6 PM EST (after market close)
0 18 * * 1-5 /Users/mohamedali/auto_collect_calendar_spreads.sh
```

---

## Data Validation

After collection, verify completeness:

```bash
# 1. Check all datasets
uv run dlt-ibapi stats ./data --dataset earnings
uv run dlt-ibapi stats ./data --dataset option_chains
uv run dlt-ibapi stats ./data --dataset stocks
uv run dlt-ibapi stats ./data --dataset options

# 2. Verify specific symbol (example: AAPL)
uv run python -c "
from dlt_ibapi.repositories import OptionBarsReader
from datetime import date

reader = OptionBarsReader('./data', 'options')

# Check front leg (DTE 14-25)
front_bars = reader.get_bars(
    underlying='AAPL',
    strike=150.0,
    expiry=date(2025, 12, 7),  # Example front leg expiry
    right='C',
    bar_size='1 day',
)
print(f'Front leg bars: {len(front_bars)}')

# Check back leg (DTE 35-60)
back_bars = reader.get_bars(
    underlying='AAPL',
    strike=150.0,
    expiry=date(2025, 12, 28),  # Example back leg expiry
    right='C',
    bar_size='1 day',
)
print(f'Back leg bars: {len(back_bars)}')
"
```

---

## Error Handling & Recovery

### Common Failures

1. **Invalid Symbol (No IB Contract)**
   - Symptom: "No security definition" error
   - Action: Logged and skipped
   - Recovery: Manual review, add to exclusion list

2. **No Expirations in DTE Range**
   - Symptom: Empty snapshot or wrong DTE
   - Action: Logged and skipped
   - Recovery: Check snapshot filters, retry

3. **Missing Spot Price**
   - Symptom: No equity bars for symbol
   - Action: Logged and skipped
   - Recovery: Backfill equity separately, retry

4. **API Rate Limit Hit**
   - Symptom: "Pacing violation" error
   - Action: Automatic retry with backoff
   - Recovery: Reduce max_workers, slow down

### Retry Strategy

```python
def backfill_with_retry(params, max_retries=2):
    """Backfill with automatic retry on transient errors."""
    for attempt in range(max_retries):
        try:
            result = execute_backfill_options(params)
            if result.success:
                return result

            # Log failure
            if attempt < max_retries - 1:
                time.sleep(5)  # Backoff
                continue
            else:
                return result  # Final failure

        except Exception as e:
            if "pacing" in str(e).lower() and attempt < max_retries - 1:
                time.sleep(10)  # Longer backoff for rate limit
                continue
            raise
```

---

## File Structure

```
dlt-ibapi/
├── scripts/
│   └── collect_calendar_spread_data.py     # Main automation script
├── docs/
│   └── AUTOMATED_CALENDAR_SPREAD_WORKFLOW.md  # This document
├── logs/
│   ├── collection_2025-11-13.log           # Daily collection logs
│   └── collection_summary_2025-11-13.json  # Summary results
└── data/
    ├── earnings/           # Earnings calendar
    ├── stocks/             # Equity bars (spot prices)
    ├── option_chains/      # Option chain snapshots
    └── options/            # Option bars (historical pricing)
```

---

## Next Steps

### Immediate (This Implementation)
1. Create `scripts/collect_calendar_spread_data.py`
2. Test with 10 symbols (smoke test)
3. Test with 100 symbols (performance test)
4. Document in README

### Short-term (Follow-up)
1. Add validation reporting (CSV export)
2. Add cost estimation (API call counting)
3. Add Dagster integration for orchestration
4. Add monitoring/alerting

### Long-term (Enhancements)
1. Support for exact expiration dates (modify backfill-options command)
2. Intelligent spot price selection (VWAP, entry date price, etc.)
3. Historical snapshot reconstruction (if possible)
4. Multi-strategy support (iron condor, vertical spreads, etc.)

---

## Questions Requiring User Input

Before implementation, please clarify:

1. **DTE Calculation**: Calculate from earnings_date or snapshot_date?
   - Recommendation: earnings_date (more logical for calendar spreads)

2. **Expiration Selection**: If multiple match DTE range, take first/last/middle?
   - Recommendation: First (closest to min DTE = earliest expiration)

3. **Spot Price Method**: Latest close or average over period?
   - Recommendation: Latest close (simplest, matches real trading)

4. **Max Workers**: What's your IB rate limit? Suggest 5 workers.
   - Recommendation: Start with 5, increase if no rate limit errors

5. **Error Tolerance**: Skip failed symbols or fail entire batch?
   - Recommendation: Skip and continue (collect max data)

6. **Dataset Name**: Snapshots go to `option_chains` or `options`?
   - Current observation: Data in `options` but should be `option_chains`

---

## Approval Needed

Ready to proceed with implementation?

**Changes to make:**
1. Create `scripts/collect_calendar_spread_data.py` (full Python script)
2. Update docs to reference new automation
3. Test with small dataset
4. Create cron job template

**Estimated implementation time:** 2-3 hours
**Estimated test time:** 1-2 hours
**Total:** Half day of work

Approve to proceed?