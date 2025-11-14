# Contract Resolution Assessment: `backfill-options --earnings-date`

## Overview

This document provides a complete technical assessment of how contract resolution works when executing:

```bash
dlt-ibapi backfill-options --earnings-date 2025-11-13 \
  --start 2025-01-01 --end 2025-11-13 \
  --mode atm --k-strikes 5
```

## Executive Summary

**Does this command resolve option contracts on IB?**

- ✅ **YES** - Option contracts (strike/expiry combinations) are resolved implicitly during historical data fetch
- ⚠️ **UNDERLYING stocks** must be resolved separately (either via `resolve-contracts` command or during `snapshot`)

**Key Insight:** Contract resolution happens at **two different layers** with **two different mechanisms**.

---

## Contract Resolution Flow

### Complete Flow Diagram

```
┌─────────────────────────────────────────────────────────────┐
│ CLI Command                                                 │
│ dlt-ibapi backfill-options --earnings-date 2025-11-13      │
│   --start 2025-01-01 --end 2025-11-13                      │
│   --mode atm --k-strikes 5                                  │
└─────────────────┬───────────────────────────────────────────┘
                  │
                  ▼
┌─────────────────────────────────────────────────────────────┐
│ CLI Layer (cli_app.py:565-770)                             │
│ - Parse args → BackfillOptionsParams                       │
│ - Call execute_backfill_options()                          │
└─────────────────┬───────────────────────────────────────────┘
                  │
                  ▼
┌─────────────────────────────────────────────────────────────┐
│ Business Logic (cli/backfill.py:199-341)                   │
│ - Load earnings symbols from ./data/earnings/              │
│ - Create DLT pipeline                                       │
│ - Call backfill_option_bars() DLT resource                 │
└─────────────────┬───────────────────────────────────────────┘
                  │
                  ▼
┌─────────────────────────────────────────────────────────────┐
│ DLT Resource (backfill/resources.py:208-403)               │
│                                                             │
│ For each symbol from earnings:                             │
│                                                             │
│ 1️⃣ Load Option Chain Snapshot (lines 260-277)             │
│    ├─ OptionChainSnapshotReader.get_chain_for_date()      │
│    └─ Returns: strikes/expirations (NO IB API call)        │
│                                                             │
│ 2️⃣ Select Contracts (lines 284-298)                        │
│    ├─ filter_contracts_by_selection_mode()                │
│    ├─ Mode: K_AROUND_ATM, k_strikes=5                     │
│    └─ Returns: [(expiry, strike, right), ...]             │
│                                                             │
│ 3️⃣ Backfill Each Contract (lines 301-401)                  │
│    For each (expiry, strike, right):                       │
│    │                                                        │
│    ├─ Create option contract (line 347-353)               │
│    │  contract = make_option(                             │
│    │      symbol="AAPL",                                  │
│    │      expiry="20251121",                              │
│    │      strike=150.0,                                   │
│    │      right="C"                                       │
│    │  )                                                    │
│    │                                                        │
│    ├─ Fetch historical bars (line 371-379)                │
│    │  bars = hist_svc.bars(                               │
│    │      contract=contract,  ← IB API RESOLVES HERE!    │
│    │      ...                                             │
│    │  )                                                    │
│    │                                                        │
│    └─ Yield normalized bar data                           │
│                                                             │
└─────────────────┬───────────────────────────────────────────┘
                  │
                  ▼
┌─────────────────────────────────────────────────────────────┐
│ IB Gateway/TWS                                             │
│ - Receives option contract specification                   │
│ - Resolves to conid (contract identifier)                 │
│ - Returns historical bars OR error 200                     │
└─────────────────────────────────────────────────────────────┘
```

---

## Two Types of Contract Resolution

### 1. Underlying Stock Contracts (Symbol → IB Contract)

**Purpose:** Resolve stock symbols (e.g., "AAPL") to valid IB Contract objects

**When:** Before snapshot or backfill operations

**How:**
- **Recommended:** `dlt-ibapi resolve-contracts --earnings-date 2025-11-13`
- **Automatic:** During `dlt-ibapi snapshot` execution
- **On-demand:** During `backfill_equity_bars()` resource

**Implementation:** `src/dlt_ibapi/resolution/resolver.py:116-192`

```python
def resolve_symbol(symbol, exchange="SMART", currency="USD", ...):
    # 1. Check cache
    if use_cache:
        cached = cache.get_contracts_by_symbol(symbol)
        if cached:
            return cached.iloc[0].to_dict()

    # 2. Call IB API: ContractDetails
    contract = make_stock(symbol, exch=exchange, curr=currency)
    details_list = self.details_svc.fetch(contract, timeout=10.0)

    # 3. Save to cache
    if save_to_cache:
        cache.save(details_df)

    return details_dict
```

**IB API Used:** `ContractDetailsService.fetch()`

**Rate Limit:** 50 requests/second

**Cache Location:** `.dlt-ibapi/cache/contracts/*.parquet`

**Cache Structure:**
```
.dlt-ibapi/cache/contracts/
  sec_type=STK/
    snapshot=2025-11-13/
      *.parquet
```

---

### 2. Option Contracts (Strike/Expiry/Right → Historical Data)

**Purpose:** Fetch historical OHLCV bars for specific option contracts

**When:** During `backfill_option_bars()` execution (for each strike/expiry combination)

**How:** Implicitly resolved during `HistoricalService.bars()` API call

**Implementation:** `src/dlt_ibapi/backfill/resources.py:347-379`

```python
# Create option contract specification
contract = make_option(
    symbol="AAPL",
    expiry="20251121",  # From chain snapshot
    strike=150.0,       # From chain snapshot
    right="C",          # Call or Put
    exchange="SMART",
)

# IB API resolves contract HERE during historical data fetch
bars = hist_svc.bars(
    contract=contract,  # ← Resolution happens implicitly
    endDateTime="20251113 23:59:59",
    durationStr="10 M",
    barSizeSetting="1 day",
    whatToShow="TRADES",
    useRTH=1,
    timeout=30.0,
)
```

**IB API Used:** `HistoricalService.bars()` (from `ib-connector`)

**Rate Limit:** 60 requests/minute ⚠️ (slower than ContractDetails!)

**Cache:** None (contract specifications come from option chain snapshot)

---

## Code Locations

### CLI Layer

**File:** `src/dlt_ibapi/cli_app.py:565-770`

**Function:** `backfill_options()`

**Responsibilities:**
- Parse command-line arguments
- Create `BackfillOptionsParams` Pydantic model
- Call business logic in `cli/backfill.py`

### Business Logic Layer

**File:** `src/dlt_ibapi/cli/backfill.py:199-341`

**Function:** `execute_backfill_options()`

**Responsibilities:**
- Load earnings symbols from `./data/earnings/`
- Map selection mode string → enum
- Create DLT pipeline
- Invoke `backfill_option_bars()` DLT resource

### DLT Resource Layer

**File:** `src/dlt_ibapi/backfill/resources.py:208-403`

**Function:** `backfill_option_bars()`

**Responsibilities:**

1. **Load Option Chain Snapshot** (lines 260-277)
   ```python
   chain_reader = OptionChainSnapshotReader(database_path, dataset_name)
   snapshots = chain_reader.get_available_snapshots(underlying)
   latest_snapshot_date = max(snapshots)
   chain = chain_reader.get_chain_for_date(
       underlying=underlying,
       as_of=latest_snapshot_date,
       min_dte=backfill_config.min_dte,
       max_dte=backfill_config.max_dte,
   )
   ```

2. **Select Contracts** (lines 284-298)
   ```python
   contracts = filter_contracts_by_selection_mode(
       chain_snapshot=chain,
       spot_price=spot_price,
       as_of=latest_snapshot_date,
       selection_mode=ContractSelectionMode.K_AROUND_ATM,
       k_strikes=5,
       delta_target=None,
       expiry_preference=None,
   )
   ```

3. **Backfill Each Contract** (lines 301-401)
   - Detect gaps in historical data
   - Create option contract with `make_option()`
   - Fetch bars via `HistoricalService.bars()` ← **IB API resolution here**
   - Yield normalized data to DLT

### Contract Selection Logic

**File:** `src/dlt_ibapi/backfill/contract_selection.py`

**Function:** `select_k_around_atm()`

**Logic:**
```python
def select_k_around_atm(strikes, spot_price, k):
    """Select k strikes on each side of ATM"""
    atm_index = find_nearest_index(strikes, spot_price)
    start = max(0, atm_index - k)
    end = min(len(strikes), atm_index + k + 1)
    return strikes[start:end]
```

For `--k-strikes 5` with AAPL @ $150:
- Selects: 145, 147.5, 150, 152.5, 155 (5 strikes each side of ATM)
- For each expiry in snapshot
- For both calls and puts

---

## Prerequisites and Dependencies

### Required Data

| Data Type | Command to Generate | Location | Purpose |
|-----------|---------------------|----------|---------|
| Earnings Calendar | `dlt-ibapi load-earnings` | `./data/earnings/` | Symbol list for batch mode |
| Option Chain Snapshot | `dlt-ibapi snapshot --earnings-date` | `./data/option_chains/` | Strikes/expirations metadata |
| Contract Cache | `dlt-ibapi resolve-contracts` | `.dlt-ibapi/cache/contracts/` | Underlying stock contracts |
| Equity Bars | `dlt-ibapi backfill-equity` | `./data/stocks/` | Spot price for ATM selection |

### Dependency Chain

```
resolve-contracts (underlyings)
    ↓
snapshot (option chains) ← uses resolved underlyings
    ↓
backfill-equity (spot prices)
    ↓
backfill-options (option bars) ← uses snapshots + spot prices
```

---

## Error Scenarios

### 1. Missing Option Chain Snapshot

**Error:**
```
ValueError: No snapshots found for symbol AAPL
```

**Location:** `backfill/resources.py:267`

**Solution:**
```bash
dlt-ibapi snapshot AAPL --min-dte 0 --max-dte 60
# or batch mode:
dlt-ibapi snapshot --earnings-date 2025-11-13 --min-dte 0 --max-dte 60
```

### 2. Invalid Option Contract

**Error:**
```
IBError: 200 - No security definition has been found for the request
```

**Cause:** Option contract doesn't exist (delisted, wrong expiry, etc.)

**Location:** During `HistoricalService.bars()` call

**Mitigation:** Error is logged and backfill continues with next contract

### 3. Missing Underlying Resolution

**Error:**
```
IBError: Invalid contract (no primary exchange)
```

**Cause:** Underlying stock contract not resolved/cached

**Solution:**
```bash
dlt-ibapi resolve-contracts --earnings-date 2025-11-13
```

### 4. Rate Limit Exceeded

**Error:**
```
IBError: 162 - Historical Market Data Service error message:
  HMDS query returned no data
```

**Cause:** Exceeded 60 requests/minute for historical data

**Mitigation:** `ib-connector` has built-in rate limiting (sleeps between requests)

---

## Recommended Workflow

### Complete Pre-Backfill Setup

```bash
# Step 1: Resolve underlying stock contracts (one-time cache population)
dlt-ibapi resolve-contracts --earnings-date 2025-11-13

# Step 2: Capture option chain snapshots (uses cached underlyings)
dlt-ibapi snapshot --earnings-date 2025-11-13 --min-dte 0 --max-dte 60

# Step 3: Backfill equity bars (for spot price reference)
dlt-ibapi backfill-equity --earnings-date 2025-11-13 \
  --start 2025-01-01 --end 2025-11-13 \
  --bar-size "1 day"

# Step 4: Backfill option bars (uses snapshots + spot prices)
dlt-ibapi backfill-options --earnings-date 2025-11-13 \
  --start 2025-01-01 --end 2025-11-13 \
  --mode atm --k-strikes 5
```

### Verification

```bash
# Check contract cache
dlt-ibapi stats .dlt-ibapi/cache --dataset contracts

# Check option chain snapshots
dlt-ibapi list-snapshots

# Check equity data
dlt-ibapi stats ./data --dataset stocks

# Check option data
dlt-ibapi stats ./data --dataset options
```

---

## Performance Characteristics

### API Rate Limits

| API | Rate Limit | Used For | Mitigation |
|-----|------------|----------|------------|
| ContractDetails | 50/sec | Underlying resolution | Cached in `.dlt-ibapi/cache/` |
| HistoricalData | 60/min | Option bar fetches | Built-in rate limiter in `ib-connector` |
| MatchingSymbols | 1/sec | Symbol search | Not used in this workflow |

### Backfill Timing Estimate

For `--earnings-date 2025-11-13` with ~50 symbols, `--k-strikes 5`, 4 expirations:

```
Calculations:
- 50 symbols
- 5 strikes each side = 10 strikes
- 4 expirations
- 2 option types (calls, puts)
- Total contracts: 50 × 10 × 4 × 2 = 4,000 contracts

Time:
- Rate: 60 requests/min = 1 request/sec
- Total time: 4,000 sec = 66.7 minutes = ~1.1 hours
```

**Optimization:** Run multiple `backfill-options` processes with different symbol subsets (IB allows multiple client IDs)

---

## Architecture Insights

### Why Two Resolution Mechanisms?

**Underlying Stocks (Explicit Cache):**
- Used by multiple operations (snapshot, backfill)
- Slow to resolve (ContractDetails API call)
- Rarely change (stock symbols are stable)
- **Solution:** Explicit cache with `resolve-contracts` command

**Option Contracts (Implicit Resolution):**
- Unique to each backfill request (depends on selection mode)
- Already constrained by slower Historical Data API (60/min)
- Change frequently (new expirations, strikes)
- **Solution:** Resolve on-the-fly during historical data fetch (no additional overhead)

### Design Tradeoffs

**Pros:**
- ✅ Separation of concerns (underlyings cached, options dynamic)
- ✅ Flexibility (can change selection mode without re-resolving)
- ✅ Performance (cache hit rate ~100% for underlyings)

**Cons:**
- ❌ Requires understanding two resolution flows
- ❌ Easy to forget `resolve-contracts` step (fails later during snapshot)
- ❌ No option contract cache (re-resolve if re-running backfill)

---

## Summary

### Key Takeaways

1. **Two-layer resolution:**
   - Layer 1: Underlying stocks (explicit, cached)
   - Layer 2: Option contracts (implicit, on-the-fly)

2. **Critical prerequisite:** Option chain snapshot must exist before backfilling option bars

3. **Rate limiting:** Historical data API (60/min) is the bottleneck, not contract resolution

4. **Recommended pattern:** Always run `resolve-contracts` → `snapshot` → `backfill-equity` → `backfill-options`

5. **Error handling:** Invalid contracts are logged and skipped (graceful degradation)

### Where Contract Resolution Happens

| Contract Type | Location | Mechanism | IB API | Cache |
|---------------|----------|-----------|--------|-------|
| Underlying stocks | `resolution/resolver.py:116-192` | `ContractResolver.resolve_symbol()` | `ContractDetailsService.fetch()` | `.dlt-ibapi/cache/contracts/` |
| Option contracts | `backfill/resources.py:371-379` | `HistoricalService.bars()` | Historical Data request | None (uses snapshot metadata) |

---

## References

### Code Files

- `src/dlt_ibapi/cli_app.py` - CLI command entry point
- `src/dlt_ibapi/cli/backfill.py` - Business logic for backfill operations
- `src/dlt_ibapi/backfill/resources.py` - DLT resources with gap detection
- `src/dlt_ibapi/backfill/contract_selection.py` - Contract selection strategies
- `src/dlt_ibapi/resolution/resolver.py` - ContractResolver implementation
- `src/dlt_ibapi/resolution/contract_cache.py` - Parquet-based contract cache
- `src/dlt_ibapi/repositories/option_chain.py` - OptionChainSnapshotReader

### Documentation

- `README.md` - User-facing documentation
- `docs/BACKFILL_GUIDE.md` - Complete backfill guide
- `docs/EARNINGS_GUIDE.md` - Earnings calendar workflow
- `CLAUDE.md` - Project architecture (this file's source)

### External Dependencies

- `ib-connector` - IB Gateway/TWS wrapper (`../ib-connector`)
  - `HistoricalService` - Historical data fetching
  - `ContractDetailsService` - Contract resolution
  - `OptionChainService` - Option chain snapshots

---

**Last Updated:** 2025-11-14
**Author:** Generated from codebase analysis
**Version:** 1.0
