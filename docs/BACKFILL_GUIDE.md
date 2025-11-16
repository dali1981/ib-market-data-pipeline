# dlt-ibapi Backfill Guide

**Complete guide to historical market data backfilling with dlt-ibapi**

Version: 1.0
Last Updated: 2025-01-20

---

## Table of Contents

1. [Introduction](#introduction)
2. [Architecture Overview](#architecture-overview)
3. [Prerequisites](#prerequisites)
4. [Quick Start](#quick-start)
5. [Option Chain Snapshots](#option-chain-snapshots)
6. [Option Bars Backfill](#option-bars-backfill)
7. [Equity Bars Backfill](#equity-bars-backfill)
8. [Gap Detection](#gap-detection)
9. [Querying Backfilled Data](#querying-backfilled-data)
10. [CLI Reference](#cli-reference)
11. [Performance Tips](#performance-tips)
12. [Troubleshooting](#troubleshooting)

---

## Introduction

The dlt-ibapi backfill infrastructure enables **gap-aware historical market data collection** from Interactive Brokers. Key features:

- **Gap Detection**: Only fetches missing data (idempotent backfills)
- **Contract Selection**: Flexible strategies for option contracts (ATM, moneyness, delta)
- **DLT-First**: All data writes through DLT (schema evolution, deduplication)
- **Multiple Bar Sizes**: From 1-second to daily bars
- **CLI & Python API**: Choose your interface

### What is Backfilling?

Backfilling is the process of fetching historical market data to fill gaps in your dataset. Unlike real-time streaming, backfilling:
- Retrieves past data on-demand
- Only fetches missing date ranges (efficient)
- Handles rate limits and retries automatically
- Stores data in DLT destinations (DuckDB, Postgres, Snowflake, etc.)

### Why Gap Detection?

Without gap detection, re-running a backfill would re-fetch all data, leading to:
- Duplicate API calls (wasted time)
- Hitting IB rate limits
- Storage bloat (DLT deduplicates, but still inefficient)

With gap detection:
- Query existing data to find coverage
- Calculate missing date ranges (gaps)
- Only fetch gaps
- Idempotent: Safe to re-run anytime

---

## Architecture Overview

### DLT-First Design

```
┌─────────────────────────────────────────────────────────────┐
│                    USER APPLICATION                         │
│  - Python scripts, CLI commands, Jupyter notebooks         │
└─────────────────────────────────────────────────────────────┘
                       │              │
          ┌────────────┘              └────────────┐
          │ Write (via DLT)                  Read  │
          ▼                                        ▼
┌─────────────────────┐                ┌──────────────────────┐
│   DLT RESOURCES     │                │ READER REPOSITORIES  │
│  (Write Path)       │                │   (Read Path)        │
│                     │                │                      │
│ - snapshot_option_  │                │ - OptionChainSnapshot│
│   chain()           │                │   Reader             │
│ - backfill_option_  │                │ - OptionBarsReader   │
│   bars()            │                │ - EquityBarsReader   │
│ - backfill_equity_  │                │                      │
│   bars()            │                │ SQL queries for:     │
│                     │                │ - Gap detection      │
│ DLT handles:        │                │ - Coverage tracking  │
│ - Schema inference  │                │ - Data retrieval     │
│ - Deduplication     │                │                      │
│ - Destinations      │                │                      │
└─────────────────────┘                └──────────────────────┘
          │                                        │
          ▼                                        ▼
┌──────────────────────────────────────────────────────────┐
│         DLT DESTINATION (DuckDB, Postgres, etc.)         │
│                                                          │
│  Tables: option_chain_snapshot, option_bars_backfill,   │
│          equity_bars_backfill                            │
└──────────────────────────────────────────────────────────┘
```

### Key Components

1. **DLT Resources**: Fetch data from IB, normalize, yield to DLT
2. **Reader Repositories**: Query DLT destinations for gap detection
3. **Gap Detection**: Find missing business days between date ranges
4. **Contract Selection**: Choose which option contracts to backfill

---

## Prerequisites

### 1. IB Gateway or TWS Running

Ensure Interactive Brokers Gateway or Trader Workstation is running and accepting API connections.

**Configuration checklist:**
- ✅ API connections enabled (IB Settings → API → Settings)
- ✅ Socket port configured (default: 4002 for paper, 4001 for live)
- ✅ Trusted IP addresses set (127.0.0.1 for local)
- ✅ Client ID available (dlt-ibapi uses client_id from config)

### 2. dlt-ibapi Installed

```bash
pip install dlt-ibapi
# or with uv
uv pip install dlt-ibapi
```

### 3. Configuration File

Initialize configuration:

```bash
dlt-ibapi init
```

This creates `.dlt-ibapi/ib_gateway.yaml`:

```yaml
connection:
  host: "127.0.0.1"
  port: 4002  # Paper trading: 4002, Live: 4001
  client_id: 1
  ready_timeout: 10.0

historical:
  bar_size: "1 min"
  duration: "1 D"
  what_to_show: "TRADES"
  use_rth: true
  timeout: 20.0
```

### 4. Test Connection

```bash
dlt-ibapi test-connection
```

Expected output:
```
✓ Connected successfully!
✓ Received contract details for AAPL
✓ Connection test successful!
```

---

## Quick Start

### Simplest Example: Equity Backfill

```python
import dlt
from datetime import date, timedelta
from dlt_ibapi import backfill_equity_bars

# Create DLT pipeline
pipeline = dlt.pipeline(
    pipeline_name="ib_stocks",
    destination="duckdb",
    dataset_name="stocks",
)

# Backfill AAPL daily bars (last 30 days)
data = backfill_equity_bars(
    symbol="AAPL",
    database_path="ib_stocks.duckdb",
    dataset_name="stocks",
    start_date=date.today() - timedelta(days=30),
    end_date=date.today(),
    bar_size="1 day",
)

# Run pipeline
info = pipeline.run(data)
print(f"Loaded {info.load_packages[0].jobs[0].metrics['read']} bars")
```

**Or using CLI:**

```bash
dlt-ibapi backfill-equity AAPL --bar-size "1 day"
```

### Next: Run Again (Gap Detection)

Run the same command again:

```python
info = pipeline.run(data)  # No gaps, no API calls!
```

The backfill detects existing data and finds no gaps, so it makes **zero API calls**. This is idempotency in action.

---

## Option Chain Snapshots

### What Are Snapshots?

Option chain snapshots capture **all available expirations and strikes** for an underlying at a point in time. This metadata is required **before backfilling option bars**.

**Snapshot contains:**
- List of expiration dates (filtered by DTE range)
- List of strike prices
- Exchange, trading class, multiplier
- Snapshot date (as_of)

### Why Snapshots First?

Option backfilling needs to know **which contracts exist** before fetching bars. The snapshot provides this information.

### Capturing Snapshots

#### Python API

```python
import dlt
from datetime import date
from dlt_ibapi import snapshot_option_chain

pipeline = dlt.pipeline(
    pipeline_name="ib_option_chains",
    destination="duckdb",
    dataset_name="options",
)

# Capture snapshot for today
data = snapshot_option_chain(
    underlying="AAPL",
    snapshot_date=date.today(),
    min_dte=7,   # At least 7 days to expiration
    max_dte=60,  # At most 60 days to expiration
)

info = pipeline.run(data, write_disposition="replace")
```

#### CLI

```bash
dlt-ibapi snapshot AAPL --min-dte 7 --max-dte 60
```

### Querying Snapshots

```python
from dlt_ibapi.repositories import OptionChainSnapshotReader

reader = OptionChainSnapshotReader(
    database_path="ib_option_chains.duckdb",
    dataset_name="options"
)

# Get available snapshot dates
snapshots = reader.get_available_snapshots("AAPL")
print(f"Snapshots: {snapshots}")

# Get chain for specific date
chain = reader.get_chain_for_date(
    underlying="AAPL",
    as_of=date.today(),
    min_dte=7,
    max_dte=60
)

# Get expirations
expirations = reader.get_available_expirations(
    underlying="AAPL",
    as_of=date.today()
)
```

### Snapshot Strategy

**Daily snapshots recommended** for:
- Tracking new contracts as they're listed
- Monitoring strike additions
- Historical analysis of option availability

**Storage**: Snapshots are small (~1 KB per underlying per day)

---

## Option Bars Backfill

### Overview

Option bars backfill fetches historical OHLCV data for selected option contracts with:
- **Contract selection** (which strikes to backfill)
- **Gap detection** (only fetch missing dates)
- **Expiry awareness** (don't fetch data after expiration)

### Workflow

```
1. Load Option Chain Snapshot
   ↓
2. Select Contracts (ATM, moneyness, delta, or all)
   ↓
3. For each contract:
   a. Check existing coverage
   b. Find gaps
   c. Fetch missing bars
   ↓
4. DLT writes to destination (with deduplication)
```

### Contract Selection Modes

#### 1. K_AROUND_ATM (Most Common)

Select **k strikes on each side of ATM** for each expiration.

```python
from dlt_ibapi import backfill_option_bars
from dlt_ibapi.backfill import OptionBackfillConfig, ContractSelectionMode

config = OptionBackfillConfig(
    start_date=date.today() - timedelta(days=7),
    end_date=date.today(),
    bar_size="1 day",
    selection_mode=ContractSelectionMode.K_AROUND_ATM,
    k_strikes=3,  # ±3 strikes around ATM (7 total per expiry)
    min_dte=7,
    max_dte=60,
)

data = backfill_option_bars(
    underlying="AAPL",
    spot_price=150.0,  # Current AAPL price
    database_path="ib_option_chains.duckdb",
    dataset_name="options",
    backfill_config=config,
)
```

**Use case**: General option analysis, near-the-money focus

#### 2. MONEYNESS

Select strikes by **moneyness ratio** (strike / spot).

```python
config = OptionBackfillConfig(
    start_date=date.today() - timedelta(days=7),
    end_date=date.today(),
    selection_mode=ContractSelectionMode.MONEYNESS,
    moneyness_levels=[0.90, 0.95, 1.0, 1.05, 1.10],
    # 0.90 = 10% OTM put, 1.0 = ATM, 1.10 = 10% OTM call
)
```

**Use case**: Consistent strike positioning across time, volatility surface analysis

#### 3. DELTA

Select strikes by **option delta** (using Black-Scholes).

```python
config = OptionBackfillConfig(
    start_date=date.today() - timedelta(days=7),
    end_date=date.today(),
    selection_mode=ContractSelectionMode.DELTA,
    target_deltas=[0.25, 0.50, 0.75],  # 25, 50, 75 delta calls
    # For puts, use negative: [-0.25, -0.50, -0.75]
)
```

**Use case**: Greeks-based analysis, risk-neutral positioning

**Note**: Requires volatility estimate (default: 30%). Provide better estimate via IV surface for accuracy.

#### 4. ALL

Select **all available strikes** (use with caution).

```python
config = OptionBackfillConfig(
    start_date=date.today() - timedelta(days=1),  # Short range!
    end_date=date.today(),
    selection_mode=ContractSelectionMode.ALL,
    min_dte=7,
    max_dte=14,  # Limit expirations
)
```

**Use case**: Complete option chain reconstruction, deep research

**Warning**: Can select 100+ contracts per expiry. Use short date ranges to avoid rate limits.

### Complete Example

```python
import dlt
from datetime import date, timedelta
from dlt_ibapi import snapshot_option_chain, backfill_option_bars
from dlt_ibapi.backfill import OptionBackfillConfig, ContractSelectionMode

# Step 1: Create pipeline
pipeline = dlt.pipeline(
    pipeline_name="ib_option_chains",
    destination="duckdb",
    dataset_name="options",
)

# Step 2: Capture snapshot (if not exists)
snapshot_data = snapshot_option_chain(
    underlying="AAPL",
    snapshot_date=date.today(),
    min_dte=7,
    max_dte=60,
)
pipeline.run(snapshot_data, write_disposition="replace")

# Step 3: Configure backfill
config = OptionBackfillConfig(
    start_date=date.today() - timedelta(days=7),
    end_date=date.today(),
    bar_size="1 day",
    selection_mode=ContractSelectionMode.K_AROUND_ATM,
    k_strikes=3,
    min_dte=7,
    max_dte=60,
    include_calls=True,
    include_puts=True,
)

# Step 4: Run backfill
backfill_data = backfill_option_bars(
    underlying="AAPL",
    spot_price=150.0,
    database_path="ib_option_chains.duckdb",
    dataset_name="options",
    backfill_config=config,
)
pipeline.run(backfill_data, write_disposition="append")
```

### CLI Usage

```bash
# Capture snapshot
dlt-ibapi snapshot AAPL --min-dte 7 --max-dte 60

# Backfill with ATM mode
dlt-ibapi backfill-options AAPL 150.0 \
  --mode atm \
  --k-strikes 3 \
  --min-dte 7 \
  --max-dte 60 \
  --bar-size "1 day"

# List snapshots
dlt-ibapi list-snapshots AAPL

# Check database stats
dlt-ibapi stats ib_options.duckdb --dataset options
```

### Earnings-Aware Spot Price Selection

When using `--earnings-date` for batch backfills, spot prices are **automatically selected based on earnings announcement timing**:

| Earnings Time | Spot Price Used | Rationale |
|---------------|-----------------|-----------|
| **PRE_MARKET** (before 9:30 AM) | **Previous trading day's close** | Options are priced before market opens |
| **AFTER_HOURS** (after 4:00 PM) | **Same day's close** | Options are priced after market closes |
| **UNKNOWN** | Same day's close (default) | Conservative assumption |

**Why This Matters**: Options are priced differently based on when earnings are announced. For pre-market earnings, the market hasn't opened yet, so option chains reflect the previous day's closing price, not the current day's close.

**Example Scenario**:

```bash
# Earnings on Wed Nov 13, 2025:
# - AAPL reports at 7:00 AM (PRE_MARKET)   → Uses Tue Nov 12 close
# - MSFT reports at 4:30 PM (AFTER_HOURS)  → Uses Wed Nov 13 close

# All symbols with earnings on this date
dlt-ibapi backfill-options --earnings-date 2025-11-13 \
  --k-strikes 5 --bar-size "5 mins"

# Filter specific symbols only
dlt-ibapi backfill-options --earnings-date 2025-11-13 \
  --symbols AAPL,MSFT,GOOGL \
  --k-strikes 5 --bar-size "5 mins"

# Automatically:
# 1. Reads earnings_time from earnings calendar
# 2. Filters to requested symbols (if --symbols provided)
# 3. Selects appropriate spot price date per symbol
# 4. Logs: "spot_price_selected: AAPL, earnings_time=PRE_MARKET, spot_price_date=2025-11-12"
```

**Weekend Handling**: Pre-market earnings on Monday automatically use previous Friday's close (skips weekend).

**Holiday Handling**: Uses NYSE market calendar to skip holidays (e.g., pre-market after Thanksgiving uses Wednesday's close).

**No Configuration Required**: The `earnings_time` field in the earnings calendar data automatically drives this behavior.

---

## Equity Bars Backfill

### Overview

Equity backfill is **much simpler** than options:
- No snapshots required
- No contract selection
- Single symbol or multiple symbols
- Same gap detection logic

### Single Symbol

```python
import dlt
from datetime import date, timedelta
from dlt_ibapi import backfill_equity_bars

pipeline = dlt.pipeline(
    pipeline_name="ib_stocks",
    destination="duckdb",
    dataset_name="stocks",
)

data = backfill_equity_bars(
    symbol="AAPL",
    database_path="ib_stocks.duckdb",
    dataset_name="stocks",
    start_date=date.today() - timedelta(days=30),
    end_date=date.today(),
    bar_size="1 day",
    what_to_show="TRADES",
    use_rth=True,
)

pipeline.run(data)
```

### Multiple Symbols

```python
from dlt_ibapi import equity_bars_backfill_source

symbols = ["AAPL", "MSFT", "GOOGL", "TSLA"]

data = equity_bars_backfill_source(
    symbols=symbols,
    database_path="ib_stocks.duckdb",
    dataset_name="stocks",
    start_date=date.today() - timedelta(days=30),
    end_date=date.today(),
    bar_size="1 day",
)

pipeline.run(data)
```

### CLI Usage

```bash
# Single symbol
dlt-ibapi backfill-equity AAPL --bar-size "1 day"

# Multiple symbols
dlt-ibapi backfill-equity AAPL MSFT GOOGL TSLA \
  --start 2024-01-01 \
  --end 2024-12-31 \
  --bar-size "1 hour"
```

### Bar Sizes

Supported bar sizes (IB format):
- `"1 secs"`, `"5 secs"`, `"10 secs"`, `"15 secs"`, `"30 secs"`
- `"1 min"`, `"2 mins"`, `"3 mins"`, `"5 mins"`, `"10 mins"`, `"15 mins"`, `"20 mins"`, `"30 mins"`
- `"1 hour"`, `"2 hours"`, `"3 hours"`, `"4 hours"`, `"8 hours"`
- `"1 day"`, `"1 week"`, `"1 month"`

**Note**: Smaller bar sizes have lookback limits (e.g., 1-second bars limited to last few days).

---

## Gap Detection

### How It Works

```python
# 1. Generate expected business days
expected_dates = business_day_range(start_date, end_date)
# Example: [2024-01-02, 2024-01-03, 2024-01-04, ...]

# 2. Query existing data
present_dates = reader.get_present_dates_for_symbol("AAPL", "1 day", start, end)
# Example: {2024-01-02, 2024-01-04}

# 3. Find missing dates
missing = expected_dates - present_dates
# Example: {2024-01-03}

# 4. Group into windows
gaps = missing_windows(present_dates, start_date, end_date)
# Example: [(2024-01-03, 2024-01-03)]

# 5. Fetch each gap
for gap_start, gap_end in gaps:
    fetch_bars(symbol, gap_start, gap_end)
```

### Business Day Calendar

By default, uses pandas `bdate_range` which:
- ✅ Excludes weekends
- ❌ Does NOT exclude market holidays

**For accurate NYSE holidays**, use `pandas_market_calendars`:

```python
import pandas_market_calendars as mcal

nyse = mcal.get_calendar('NYSE')
schedule = nyse.schedule(start_date='2024-01-01', end_date='2024-12-31')
trading_days = mcal.date_range(schedule, frequency='1D')
```

(Custom calendar support coming soon)

### Idempotency

Running backfill multiple times is safe:
- First run: Fetches all missing data
- Second run: Finds no gaps, makes zero API calls
- Anytime: Only fetches new gaps (e.g., new dates added)

### Partial Backfills

If backfill fails midway:
- Already fetched data is saved (DLT commits per batch)
- Re-running continues from last gap
- No duplicate data (primary key deduplication)

---

## Querying Backfilled Data

### Equity Bars

```python
from dlt_ibapi.repositories import EquityBarsReader

reader = EquityBarsReader(
    database_path="ib_stocks.duckdb",
    dataset_name="stocks"
)

# Get bars for AAPL
bars = reader.get_bars(
    symbol="AAPL",
    bar_size="1 day",
    start_date=date(2024, 1, 1),
    end_date=date(2024, 12, 31),
)
print(bars[['time', 'open', 'high', 'low', 'close', 'volume']])

# Get date range
min_date, max_date = reader.get_date_range("AAPL", "1 day")
print(f"Coverage: {min_date} to {max_date}")

# Get all symbols
symbols = reader.get_available_symbols(bar_size="1 day")
print(f"Symbols: {symbols}")

# Get summary
summary = reader.get_symbols_summary(bar_size="1 day")
print(summary)
```

### Option Bars

```python
from dlt_ibapi.repositories import OptionBarsReader

reader = OptionBarsReader(
    database_path="ib_option_chains.duckdb",
    dataset_name="options"
)

# Get bars for specific contract
bars = reader.get_bars(
    underlying="AAPL",
    expiry=date(2024, 12, 20),
    strike=150.0,
    right="C",  # Call
    bar_size="1 day",
)

# Get all contracts for AAPL
contracts = reader.get_contracts_for_underlying(
    underlying="AAPL",
    bar_size="1 day",
)
print(contracts[['expiry', 'strike', 'right', 'bar_count', 'first_bar', 'last_bar']])

# Get available expirations
expirations = reader.get_available_expirations("AAPL", "1 day")
```

### Direct SQL Queries

```python
import duckdb

conn = duckdb.connect("ib_stocks.duckdb", read_only=True)

# Custom query
df = conn.execute("""
    SELECT symbol, DATE(time) as date, close
    FROM stocks.equity_bars_backfill
    WHERE symbol IN ('AAPL', 'MSFT')
      AND DATE(time) BETWEEN '2024-01-01' AND '2024-12-31'
    ORDER BY symbol, time
""").df()
```

---

## CLI Reference

### snapshot

Capture option chain snapshot.

```bash
dlt-ibapi snapshot SYMBOL [OPTIONS]
```

**Options:**
- `--date, -d`: Snapshot date (YYYY-MM-DD, default: today)
- `--min-dte`: Minimum days to expiration (default: 7)
- `--max-dte`: Maximum days to expiration (default: 365)
- `--database, --db`: Database path (default: ib_snapshots.duckdb)
- `--dataset`: Dataset name (default: options)
- `--config, -c`: Path to config file

**Example:**
```bash
dlt-ibapi snapshot AAPL --min-dte 7 --max-dte 60
```

### backfill-options

Backfill option bars with contract selection.

```bash
dlt-ibapi backfill-options SYMBOL SPOT_PRICE [OPTIONS]
```

**Options:**
- `--start`: Start date (YYYY-MM-DD, default: 30 days ago)
- `--end`: End date (YYYY-MM-DD, default: today)
- `--bar-size, -b`: Bar size (default: "1 day")
- `--mode, -m`: Selection mode: atm, moneyness, delta, all (default: atm)
- `--k-strikes, -k`: K strikes for ATM mode (default: 5)
- `--min-dte`: Minimum days to expiration (default: 7)
- `--max-dte`: Maximum days to expiration (default: 60)
- `--database, --db`: Database path (default: ib_options.duckdb)
- `--dataset`: Dataset name (default: options)

**Example:**
```bash
dlt-ibapi backfill-options AAPL 150.0 --mode atm --k-strikes 3
```

### backfill-equity

Backfill equity bars for one or more symbols.

```bash
dlt-ibapi backfill-equity SYMBOL... [OPTIONS]
```

**Options:**
- `--start`: Start date (YYYY-MM-DD, default: 30 days ago)
- `--end`: End date (YYYY-MM-DD, default: today)
- `--bar-size, -b`: Bar size (default: "1 day")
- `--database, --db`: Database path (default: ib_stocks.duckdb)
- `--dataset`: Dataset name (default: stocks)

**Example:**
```bash
dlt-ibapi backfill-equity AAPL MSFT GOOGL --bar-size "1 hour"
```

### list-snapshots

List available option chain snapshots.

```bash
dlt-ibapi list-snapshots [SYMBOL] [OPTIONS]
```

**Example:**
```bash
dlt-ibapi list-snapshots AAPL
dlt-ibapi list-snapshots  # List all
```

### stats

Show database statistics.

```bash
dlt-ibapi stats DATABASE [OPTIONS]
```

**Options:**
- `--dataset`: Dataset name (default: options)

**Example:**
```bash
dlt-ibapi stats ib_options.duckdb --dataset options
```

---

## Performance Tips

### 1. Batch Multiple Symbols

**Inefficient:**
```python
for symbol in symbols:
    data = backfill_equity_bars(symbol, ...)
    pipeline.run(data)  # Separate connection per symbol
```

**Efficient:**
```python
data = equity_bars_backfill_source(symbols, ...)
pipeline.run(data)  # Single connection, batched
```

### 2. Choose Appropriate Bar Sizes

- **1 day**: Fastest, longest lookback (~20 years)
- **1 hour**: Moderate, ~2 years lookback
- **1 min**: Slower, ~60 days lookback
- **1 sec**: Very slow, ~1-2 days lookback

Use largest bar size that meets your needs.

### 3. Limit Contract Selection

**For exploratory analysis:**
- Use `K_AROUND_ATM` with k=3 (7 contracts per expiry)
- Limit DTE range (e.g., 7-30 days)

**For deep research:**
- Use `MONEYNESS` with 5-10 levels
- Extend DTE range as needed

**Avoid:**
- `ALL` mode with wide DTE ranges (100s of contracts)

### 4. Respect Rate Limits

IB API rate limits (approximate):
- Historical bars: 60 requests/10 minutes
- Contract details: 50 requests/second

Gap detection minimizes requests by only fetching missing data.

### 5. Use Regular Trading Hours (RTH)

```python
use_rth=True  # Excludes pre/post market (faster, cleaner)
```

Unless you specifically need extended hours data.

---

## Troubleshooting

### "No option chain snapshots found for {symbol}"

**Cause**: Trying to backfill options without capturing snapshot first.

**Solution**:
```bash
# 1. Capture snapshot
dlt-ibapi snapshot AAPL

# 2. Then backfill
dlt-ibapi backfill-options AAPL 150.0
```

### "Connection failed: [Errno 61] Connection refused"

**Cause**: IB Gateway/TWS not running or wrong port.

**Solution**:
1. Start IB Gateway/TWS
2. Check port in config (4002 for paper, 4001 for live)
3. Test: `dlt-ibapi test-connection`

### "No historical data returned"

**Possible causes**:
- Symbol doesn't exist or is misspelled
- Date range outside available data
- Bar size incompatible with date range (e.g., 1 sec bars for 1 year ago)

**Solution**:
- Verify symbol with IB
- Use shorter date range for smaller bar sizes
- Check IB data subscriptions (real-time vs delayed)

### "Rate limit exceeded"

**Cause**: Too many API requests in short time.

**Solution**:
- Reduce number of contracts (smaller k_strikes, narrower DTE)
- Use larger bar sizes
- Add delays between backfills
- Gap detection helps, but initial backfill still hits limits

### DuckDB "database is locked"

**Cause**: Multiple processes accessing same database.

**Solution**:
- Close other connections (Jupyter notebooks, DBeaver, etc.)
- Use `read_only=True` for reader repositories
- Or use different database paths

---

## Next Steps

- **API Reference**: See `API_REFERENCE.md` for complete API documentation
- **Examples**: Check `examples/` directory for working code
- **Specs**: Read `specs/BACKFILL_IMPLEMENTATION_PLAN.md` for architecture details

---

**Questions or issues?** Open an issue on GitHub: https://github.com/anthropics/dlt-ibapi/issues
