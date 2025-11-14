# Options Backtesting - Quick Start Guide

**Complete guide to running earnings calendar spread backtests with dlt-ibapi**

---

## Overview

The `dlt-ibapi` backtest system enables you to test options strategies using **daily-collected market data**. The system works by combining:

1. **Daily option chain snapshots** - Available strikes and expirations (metadata)
2. **Option bars** - OHLCV price data for specific contracts
3. **Equity bars** - Underlying spot prices
4. **Earnings calendar** - Earnings event dates and timing

### How It Works

The backtest follows this daily workflow:

```
For each backtest date:
├─ Check if option chain snapshot exists for this date
├─ Check if equity bars exist for underlying
├─ For each earnings event on this date:
│  ├─ Determine option contracts using DTE rules (14-21 DTE front, 35-50 DTE back)
│  ├─ Check if option bars exist for selected contracts
│  ├─ If all data available: Execute spread
│  └─ If data missing: Skip event (logged)
└─ Continue to next date
```

**Key Principle**: Data must be collected **daily and proactively**. Option chain snapshots cannot be collected retroactively for expired options.

### Data Collection Requirements

✅ **Required Daily Collections**:
- Option chain snapshots (`dlt-ibapi snapshot SYMBOL --date YYYY-MM-DD`)
- Option bars for contracts before they expire (`dlt-ibapi backfill-options ...`)
- Equity bars (can be backfilled anytime: `dlt-ibapi backfill-equity ...`)

✅ **Validation System**:
- Pre-flight validation checks data availability before backtest
- Clear error messages about missing data
- Auto-filtering of dates without complete data

✅ **What This Enables**:
- Backtest earnings calendar spread strategies
- Test different DTE ranges and strike selections
- Validate historical strategy performance
- Analyze which earnings events had complete data

---

## Table of Contents

1. [Prerequisites](#prerequisites)
2. [Data Requirements](#data-requirements)
3. [Daily Data Collection Workflow](#daily-data-collection-workflow)
4. [Step 1: Verify Data Availability](#step-1-verify-data-availability)
5. [Step 2: Download Required Data](#step-2-download-required-data)
6. [Step 3: Run Backtest](#step-3-run-backtest)
7. [Step 4: Analyze Results](#step-4-analyze-results)
8. [Troubleshooting](#troubleshooting)
9. [Advanced Usage](#advanced-usage)

---

## Prerequisites

### Installation

```bash
# Navigate to dlt-ibapi directory
cd /Users/mohamedali/trading_project/dlt-ibapi

# Install dependencies (includes tools, matplotlib, etc.)
uv sync

# Verify installation
uv run dlt-ibapi version
```

### IB Gateway/TWS Setup

For data download, you need Interactive Brokers Gateway or TWS running:

```bash
# 1. Start IB Gateway (Paper Trading recommended for testing)
#    - Port: 4002 (Paper) or 4001 (Live)
#    - Enable API connections
#    - Disable read-only API

# 2. Test connection
uv run dlt-ibapi test-connection

# Expected output:
# ✓ Successfully connected to IB Gateway
# ✓ Account: DU1234567
# ✓ Connection time: 1.23s
```

---

## Data Requirements

Options backtesting requires **three types of data**:

| Data Type | Purpose | Example Location |
|-----------|---------|------------------|
| **Equity Bars** | Underlying spot prices | `./data/stocks/**/*.parquet` |
| **Option Bars** | Option OHLCV prices | `./data/options/**/*.parquet` |
| **Option Chains** | Complete chain snapshots | `./data/option_chains/**/*.parquet` |
| **Earnings Calendar** | Earnings dates/times | `./data/earnings_calendar/**/*.parquet` |

**Note**: The backtest calculates Greeks on-the-fly from option prices, so no pre-computed Greeks are needed.

---

## Daily Data Collection Workflow

### Three-Component Data Model

The backtest requires three types of data collected **daily and proactively**:

#### 1. Option Chain Snapshots (Metadata Only)
- **What**: Available strikes and expirations for each underlying
- **Contains**: Contract IDs, strikes, expiration dates, DTE
- **Does NOT contain**: Prices, bid/ask, volume, open interest
- **Collection**: `dlt-ibapi snapshot SYMBOL --date YYYY-MM-DD --min-dte 7 --max-dte 90`
- **Critical**: Must be collected daily; cannot be retrieved retroactively for expired options

#### 2. Option Bars (Price Data)
- **What**: OHLCV price data for specific option contracts
- **Contains**: Open, high, low, close, volume for each contract
- **Collection**: `dlt-ibapi backfill-options SYMBOL STRIKE --mode atm --dte-range 7 90`
- **Critical**: Must be collected before options expire

#### 3. Equity Bars (Underlying Prices)
- **What**: Historical OHLCV for underlying stocks
- **Contains**: Spot price, volume
- **Collection**: `dlt-ibapi backfill-equity SYMBOL --start-date YYYY-MM-DD`
- **Flexible**: Can be backfilled at any time (no expiration constraint)

### How the Backtest Uses This Data

```python
# For each backtest date:
for date in backtest_dates:
    # 1. Check if we have option chain snapshot for this date
    snapshot = option_chain_reader.get_available_snapshots(symbol)
    if date not in snapshot:
        continue  # Skip - no snapshot available

    # 2. Get available expirations from snapshot
    expirations = option_chain_reader.get_available_expirations(
        underlying=symbol,
        as_of=date,
        min_dte=7,
        max_dte=90,
    )

    # 3. Determine contracts using DTE rules
    front_month = find_expiry_in_dte_range(expirations, 14, 21)
    back_month = find_expiry_in_dte_range(expirations, 35, 50)

    # 4. Get spot price to find ATM strike
    spot = equity_reader.get_bars(symbol, date)["close"]
    strike = find_atm_strike(snapshot, spot)

    # 5. Check if we have option bars for selected contracts
    front_bars = option_bars_reader.get_bars(symbol, strike, front_month, "C", date)
    back_bars = option_bars_reader.get_bars(symbol, strike, back_month, "C", date)

    # 6. If all data available, execute trade
    if front_bars and back_bars:
        execute_calendar_spread(front_bars, back_bars)
    else:
        log_skip(f"Missing option bars for {symbol} on {date}")
```

### Data Collection Strategy

**Daily Forward-Looking Collection** (Recommended):
```bash
# Run daily at market close
TODAY=$(date +%Y-%m-%d)

# 1. Snapshot option chains (captures what's available today)
uv run dlt-ibapi snapshot AAPL MSFT GOOGL --date $TODAY --min-dte 7 --max-dte 90

# 2. Collect option bars for contracts expiring soon
uv run dlt-ibapi backfill-options AAPL 150.0 --mode atm --dte-range 7 90

# 3. Backfill equity bars (can run weekly)
uv run dlt-ibapi backfill-equity AAPL MSFT GOOGL --start-date 2024-01-01
```

**Backfill for Historical Period** (Limited):
```bash
# WARNING: Can only backfill for non-expired options
# For expired options, you need historical snapshots collected before expiration

# What you CAN backfill:
uv run dlt-ibapi backfill-equity AAPL --start-date 2023-01-01  # ✅ Works anytime

# What you CANNOT backfill:
# ❌ Option chain snapshots for past dates (if options have expired)
# ❌ Option bars for expired contracts

# Solution: Start collecting daily data NOW for future backtesting
```

### Why Daily Collection Matters

**IB API Constraint**: Option data for expired contracts is not accessible via the API. This means:

- ✅ **Today**: Can get option chain + prices for contracts expiring in 90 days
- ❌ **91 days from now**: Cannot retroactively get option chain snapshot for "today"
- ❌ **After expiration**: Cannot get any historical data for expired contracts

**Implication**: To backtest strategies, you must **collect data before options expire**.

### Validation Before Backtest

Always validate data availability before running a backtest:

```python
from dlt_ibapi.backtest import BacktestDataValidator
from dlt_ibapi.backtest.earnings_loader import EarningsCalendarLoader
from dlt_ibapi.backtest.data_providers import BacktestDataRequirements
from dlt_ibapi.repositories import (
    EquityBarsReader,
    OptionBarsReader,
    OptionChainSnapshotReader,
)

# 1. Load earnings events
loader = EarningsCalendarLoader()
events = loader.load_file("earnings_2024-10-22.txt")

# 2. Initialize readers
equity_reader = EquityBarsReader("./data", "stocks")
option_bars_reader = OptionBarsReader("./data", "options")
option_chain_reader = OptionChainSnapshotReader("./data", "option_chains")

# 3. Create validator
validator = BacktestDataValidator(
    equity_reader=equity_reader,
    option_bars_reader=option_bars_reader,
    option_chain_reader=option_chain_reader,
)

# 4. Define requirements
requirements = BacktestDataRequirements(
    front_month_dte=(14, 21),
    back_month_dte=(35, 50),
    min_equity_coverage=0.90,
    min_option_bars_coverage=0.95,
)

# 5. Validate
report = validator.validate_all(events, requirements)

# 6. Review results
print(f"✓ Valid events: {report.valid_events}/{report.total_events}")
print(f"✗ Invalid events: {report.invalid_events}")

if report.skip_reasons:
    print("\nReasons for skipping events:")
    for reason, count in report.skip_reasons.items():
        print(f"  - {reason}: {count} events")

if report.invalid_symbols:
    print("\nSymbols with missing data:")
    for symbol, reason in report.invalid_symbols.items():
        print(f"  - {symbol}: {reason}")
```

### Working with Collected Data

Once you've collected data, query it using the repository classes:

```python
from dlt_ibapi.repositories import (
    EquityBarsReader,
    OptionBarsReader,
    OptionChainSnapshotReader,
)
from datetime import date

# Equity bars
equity_reader = EquityBarsReader("./data", "stocks")
bars = equity_reader.get_bars(
    symbol="AAPL",
    bar_size="1 day",
    start_date=date(2024, 1, 1),
    end_date=date(2024, 12, 31),
)

# Option bars for specific contract
option_reader = OptionBarsReader("./data", "options")
option_bars = option_reader.get_bars(
    underlying="AAPL",
    strike=150.0,
    expiry=date(2024, 12, 20),
    right="C",
    bar_size="1 day",
    start_date=date(2024, 11, 1),
    end_date=date(2024, 11, 13),
)

# Option chain snapshot
chain_reader = OptionChainSnapshotReader("./data", "option_chains")

# Check which dates have snapshots
available_dates = chain_reader.get_available_snapshots("AAPL")
print(f"Snapshots available: {len(available_dates)} dates")

# Get expirations available on a specific date
expirations = chain_reader.get_available_expirations(
    underlying="AAPL",
    as_of=date(2024, 10, 22),
    min_dte=7,
    max_dte=90,
)
print(f"Expirations on 2024-10-22: {expirations}")
```

### Key Principles

1. **Proactive Collection**: Start collecting data daily NOW for future backtesting
2. **Three-Component Model**: Snapshots (metadata) + Option Bars (prices) + Equity Bars (spot)
3. **Validation First**: Always validate before backtest to know which dates have complete data
4. **Gap Awareness**: The validation system tells you exactly what's missing and why
5. **Clear Error Messages**: When data is missing, you get actionable guidance on what to collect

---

## Step 1: Verify Data Availability

Before running a backtest, **verify you have sufficient data** for your target symbols and date range.

### Check Database Statistics

```bash
# Check all datasets
uv run dlt-ibapi stats ./data

# Check specific dataset
uv run dlt-ibapi stats ./data --dataset stocks
uv run dlt-ibapi stats ./data --dataset options
uv run dlt-ibapi stats ./data --dataset option_chains
```

**Example Output**:
```
📊 Database Statistics

Dataset: stocks
  Location: ./data/stocks
  Tables: 1

equity_bars_1_day
  Rows: 12,450
  Date range: 2023-01-03 to 2024-12-31

Dataset: options
  Location: ./data/options
  Tables: 1

option_bars_1_day
  Rows: 245,890
  Date range: 2023-01-03 to 2024-12-31

Dataset: option_chains
  Location: ./data/option_chains
  Tables: 1

option_chain_snapshots
  Rows: 89,234
  Date range: 2023-01-03 to 2024-12-31
```

### Verify Symbol Coverage

```bash
# Check available symbols in equity data
uv run python -c "
from dlt_ibapi.repositories import EquityBarsReader
reader = EquityBarsReader('./data', 'stocks')
symbols = reader.get_available_symbols('1 day')
print(f'Available symbols ({len(symbols)}): {sorted(symbols)}')
"

# Expected output:
# Available symbols (4): ['AAPL', 'GOOGL', 'MSFT', 'TSLA']
```

### Check Date Coverage for Symbol

```bash
# Check date range for specific symbol
uv run python -c "
from dlt_ibapi.repositories import EquityBarsReader
from datetime import date

reader = EquityBarsReader('./data', 'stocks')
start, end = reader.get_date_range('AAPL', '1 day')
print(f'AAPL data: {start} to {end}')
print(f'Days: {(end - start).days}')
"

# Expected output:
# AAPL data: 2023-01-03 to 2024-12-31
# Days: 728
```

---

## Step 2: Download Required Data

If you don't have sufficient data, download it using the backfill commands.

### 2.1 Download Equity Bars (Underlying Prices)

```bash
# Download equity bars for multiple symbols
uv run dlt-ibapi backfill-equity \
    AAPL MSFT GOOGL AMZN \
    --start-date 2023-01-01 \
    --end-date 2024-12-31 \
    --bar-size "1 day" \
    --pipeline-name stocks_backfill

# Options:
#   --bar-size: "1 day", "1 hour", "5 mins" (default: "1 day")
#   --pipeline-name: DLT pipeline name (optional)
#   --data-dir: Data directory (default: ./data)
```

**Expected Output**:
```
✓ Backfill complete for AAPL: 252 bars (2023-01-03 → 2024-12-29)
✓ Backfill complete for MSFT: 252 bars (2023-01-03 → 2024-12-29)
✓ Backfill complete for GOOGL: 252 bars (2023-01-03 → 2024-12-29)
✓ Backfill complete for AMZN: 252 bars (2023-01-03 → 2024-12-29)

Total: 1,008 bars written to ./data/stocks
```

### 2.2 Download Option Bars (Option Prices)

```bash
# Download option bars for a symbol
uv run dlt-ibapi backfill-options \
    AAPL \
    150.0 \
    --mode atm \
    --k-strikes 5 \
    --dte-range 7 90 \
    --start-date 2023-01-01 \
    --end-date 2024-12-31 \
    --bar-size "1 day" \
    --pipeline-name options_backfill

# Options:
#   AAPL: Symbol
#   150.0: Strike price (reference for ATM mode)
#   --mode: "atm", "fixed", "all" (default: "atm")
#   --k-strikes: Number of strikes around ATM (default: 3)
#   --dte-range: Min/max days to expiration (default: 7 60)
#   --bar-size: "1 day", "1 hour", "5 mins" (default: "1 day")
```

**Note**: Option bars are typically large datasets. Start with fewer symbols and narrow DTE ranges for testing.

### 2.3 Download Option Chain Snapshots

```bash
# Snapshot option chains (daily)
uv run dlt-ibapi snapshot \
    AAPL \
    --min-dte 7 \
    --max-dte 90 \
    --pipeline-name option_chains_snapshot

# For backtesting, you need daily snapshots over the backtest period
# Run this daily or use a loop:

# Download snapshots for date range
for symbol in AAPL MSFT GOOGL; do
    uv run dlt-ibapi snapshot \
        $symbol \
        --min-dte 7 \
        --max-dte 90 \
        --pipeline-name option_chains_${symbol}
done
```

**Alternative**: Use Dagster pipeline for automated daily snapshots (see `dagster-ib-pipeline` repo).

### 2.4 Download Earnings Calendar

```bash
# Navigate to earnings-calendar-dlt
cd /Users/mohamedali/trading_project/earnings-calendar-dlt

# Download earnings calendar
uv run python -m earnings_calendar.pipeline \
    --start-date 2023-01-01 \
    --end-date 2024-12-31

# This creates: ./data/earnings_calendar/*.parquet
```

**Note**: Earnings calendar is optional but **highly recommended** for `pre_earnings` and `iv_based` strategies.

---

## Step 3: Run Backtest

Once you've verified data availability, run the backtest.

### Basic Command

```bash
# Run IV-based earnings calendar spread backtest
uv run dlt-ibapi backtest-earnings-spreads \
    --strategy iv_based \
    --symbols AAPL MSFT GOOGL \
    --start-date 2023-01-01 \
    --end-date 2024-12-31 \
    --capital 100000
```

### Available Strategy Types

```bash
# 1. Generic Calendar (baseline, no earnings timing)
uv run dlt-ibapi backtest-earnings-spreads \
    --strategy generic_calendar \
    --symbols AAPL \
    --start-date 2023-01-01 \
    --end-date 2024-12-31

# 2. Pre-Earnings Calendar (timed around earnings)
uv run dlt-ibapi backtest-earnings-spreads \
    --strategy pre_earnings \
    --symbols AAPL MSFT \
    --start-date 2023-01-01 \
    --end-date 2024-12-31

# 3. IV-Based Entry (most selective, strict IV criteria)
uv run dlt-ibapi backtest-earnings-spreads \
    --strategy iv_based \
    --symbols AAPL MSFT GOOGL AMZN \
    --start-date 2023-01-01 \
    --end-date 2024-12-31
```

### All Command-Line Options

```bash
uv run dlt-ibapi backtest-earnings-spreads \
    --strategy iv_based \              # Strategy: generic_calendar, pre_earnings, iv_based
    --symbols AAPL MSFT \               # Underlying symbols (space-separated)
    --start-date 2023-01-01 \           # Backtest start date (YYYY-MM-DD)
    --end-date 2024-12-31 \             # Backtest end date (YYYY-MM-DD)
    --capital 100000 \                  # Initial capital (USD)
    --data-path ./data \                # Path to Parquet data directory
    --earnings-path ./data/earnings_calendar \  # Path to earnings calendar data
    --output ./backtest_results         # Output directory for results
```

### Expected Output (During Execution)

```
📊 Earnings Calendar Spread Backtest

Loading modules... ✓
Initializing data providers... ✓
Configuring iv_based strategy... ✓

┏━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━┓
┃ Parameter        ┃ Value                  ┃
┡━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━┩
│ Strategy         │ iv_based               │
│ Symbols          │ AAPL, MSFT, GOOGL      │
│ Start Date       │ 2023-01-01             │
│ End Date         │ 2024-12-31             │
│ Initial Capital  │ $100,000               │
│ Data Path        │ ./data                 │
└──────────────────┴────────────────────────┘

Running backtest...

📈 Backtest Results

┏━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━┓
┃ Metric                ┃ Value            ┃
┡━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━┩
│ Initial Capital       │ $100,000         │
│ Final Value           │ $115,234         │
│ Total Return          │ $15,234.50       │
│ Total Return %        │ 15.23%           │
│                       │                  │
│ Number of Trades      │ 42               │
│ Winning Trades        │ 28               │
│ Losing Trades         │ 14               │
│ Win Rate              │ 66.7%            │
│                       │                  │
│ Average Win           │ $1,234.56        │
│ Average Loss          │ -$567.89         │
│ Profit Factor         │ 2.17             │
│                       │                  │
│ Max Drawdown          │ $4,567.89        │
│ Max Drawdown %        │ 4.57%            │
└───────────────────────┴──────────────────┘

Exporting results to ./backtest_results...
  ✓ Summary: backtest_results/summary_iv_based_2023-01-01_2024-12-31.json
  ✓ Equity curve: backtest_results/equity_curve_iv_based_2023-01-01_2024-12-31.csv
  ✓ Trades: backtest_results/trades_iv_based_2023-01-01_2024-12-31.csv
  ✓ Equity curve plot: backtest_results/equity_curve_iv_based_2023-01-01_2024-12-31.png

✓ Backtest complete! Results saved to ./backtest_results
```

---

## Step 4: Analyze Results

### Output Files

The backtest generates **4 files** in the output directory:

#### 1. Summary JSON (`summary_*.json`)

```json
{
  "initial_capital": 100000.0,
  "final_value": 115234.5,
  "total_return": 15234.5,
  "total_return_pct": 15.23,
  "num_trades": 42,
  "winning_trades": 28,
  "losing_trades": 14,
  "win_rate": 66.67,
  "avg_win": 1234.56,
  "avg_loss": -567.89,
  "profit_factor": 2.17,
  "max_drawdown": 4567.89,
  "max_drawdown_pct": 4.57
}
```

#### 2. Equity Curve CSV (`equity_curve_*.csv`)

```csv
timestamp,portfolio_value,cash,num_positions
2023-01-03 00:00:00,100000.0,100000.0,0
2023-01-04 00:00:00,100000.0,100000.0,0
2023-01-10 00:00:00,98500.0,98500.0,1
2023-01-17 00:00:00,99200.0,99200.0,1
...
```

**Load in Python**:
```python
import polars as pl
equity = pl.read_csv("equity_curve_*.csv")
print(equity)
```

#### 3. Trades CSV (`trades_*.csv`)

```csv
position_id,position_type,entry_date,exit_date,exit_reason,entry_cost,pnl,return_pct,num_legs,underlying
pos_001,CALENDAR_SPREAD,2023-01-10,2023-01-17,strategy_exit,-1500.0,450.0,30.0,2,AAPL
pos_002,CALENDAR_SPREAD,2023-01-24,2023-01-31,strategy_exit,-1800.0,-400.0,-22.2,2,MSFT
...
```

**Load in Python**:
```python
import polars as pl
trades = pl.read_csv("trades_*.csv")

# Analyze by symbol
trades.group_by("underlying").agg([
    pl.count("position_id").alias("num_trades"),
    pl.mean("pnl").alias("avg_pnl"),
    pl.sum("pnl").alias("total_pnl"),
])
```

#### 4. Equity Curve Plot (`equity_curve_*.png`)

Visual representation of portfolio value over time (300 DPI PNG).

### Advanced Analysis in Python

```python
import polars as pl
import json

# Load all results
summary = json.load(open("summary_*.json"))
equity = pl.read_csv("equity_curve_*.csv")
trades = pl.read_csv("trades_*.csv")

# Calculate Sharpe ratio (annualized)
returns = equity.select([
    pl.col("portfolio_value").pct_change().alias("return")
]).drop_nulls()

sharpe = (
    returns["return"].mean() / returns["return"].std()
) * (252 ** 0.5)  # Annualized
print(f"Sharpe Ratio: {sharpe:.2f}")

# Analyze trades by exit reason
trades.group_by("exit_reason").agg([
    pl.count("position_id").alias("count"),
    pl.mean("pnl").alias("avg_pnl"),
])

# Monthly returns
equity_monthly = equity.with_columns([
    pl.col("timestamp").cast(pl.Date).alias("date")
]).with_columns([
    pl.col("date").dt.truncate("1mo").alias("month")
]).group_by("month").agg([
    pl.col("portfolio_value").last().alias("end_value")
]).sort("month")

print(equity_monthly)
```

---

## Troubleshooting

### Issue: "No data available for symbol X"

**Cause**: Missing equity bars, option bars, or option chains for the symbol.

**Solution**:
```bash
# 1. Check what data exists
uv run dlt-ibapi stats ./data --dataset stocks

# 2. Download missing data
uv run dlt-ibapi backfill-equity X --start-date YYYY-MM-DD --end-date YYYY-MM-DD
uv run dlt-ibapi backfill-options X 100.0 --mode atm --k-strikes 5
uv run dlt-ibapi snapshot X --min-dte 7 --max-dte 90
```

### Issue: "No valid rebalancing timestamps"

**Cause**: Backtest start date is before available data or insufficient lookback data.

**Solution**:
```bash
# Check earliest available date
uv run python -c "
from dlt_ibapi.repositories import EquityBarsReader
reader = EquityBarsReader('./data', 'stocks')
start, _ = reader.get_date_range('AAPL', '1 day')
print(f'Earliest data: {start}')
"

# Adjust backtest start date to be at least 252 days after earliest data
# (strategies need lookback for IV calculations)
```

### Issue: "ModuleNotFoundError: No module named 'tools'"

**Cause**: The `tools` package is not installed.

**Solution**:
```bash
# Ensure tools is in pyproject.toml dependencies
grep "tools" pyproject.toml

# Should show:
# tools>=0.1.0

# Sync dependencies
uv sync

# Verify tools is installed
uv pip list | grep tools
```

### Issue: "No earnings data found"

**Cause**: `pre_earnings` or `iv_based` strategies require earnings calendar data.

**Solution**:
```bash
# Download earnings calendar
cd /Users/mohamedali/trading_project/earnings-calendar-dlt
uv run python -m earnings_calendar.pipeline \
    --start-date 2023-01-01 \
    --end-date 2024-12-31

# Verify earnings data
uv run dlt-ibapi stats ./data/earnings_calendar
```

**Alternative**: Use `generic_calendar` strategy (doesn't require earnings data).

### Issue: "Backtest runs but generates 0 trades"

**Possible causes**:
1. **Strategy too selective**: `iv_based` has strict IV criteria
2. **Insufficient option chain data**: Missing snapshots
3. **No earnings in date range**: For `pre_earnings` strategy

**Solution**:
```bash
# 1. Try less selective strategy first
uv run dlt-ibapi backtest-earnings-spreads \
    --strategy generic_calendar \
    --symbols AAPL \
    --start-date 2023-01-01 \
    --end-date 2023-03-31

# 2. Check option chain coverage
uv run dlt-ibapi stats ./data --dataset option_chains

# 3. Verify earnings data for symbols
cd /Users/mohamedali/trading_project/earnings-calendar-dlt
uv run python -c "
import polars as pl
df = pl.read_parquet('./data/earnings_calendar/**/*.parquet')
print(df.filter(pl.col('symbol').is_in(['AAPL', 'MSFT'])))
"
```

---

## Advanced Usage

### Custom Strategy Configuration (Python API)

```python
from datetime import date
from tools.strategies.options import (
    IVBasedCalendarSpreadStrategy,
    IVBasedConfig,
)
from dlt_ibapi.backtest import (
    IBBacktestDataProvider,
    EarningsCalendarProvider,
    OptionsChainProvider,
    OptionsBacktestRunner,
)

# Create data providers
data_provider = IBBacktestDataProvider("./data")
earnings_provider = EarningsCalendarProvider("./data/earnings_calendar")
chain_provider = OptionsChainProvider(data_provider.option_chain_reader)

# Configure strategy with custom parameters
config = IVBasedConfig(
    underlying_symbols=["AAPL", "MSFT", "GOOGL"],

    # Earnings timing
    entry_window=(15, 30),          # Enter 15-30 days before earnings
    exit_buffer=3,                   # Exit 3 days before earnings

    # Option selection
    front_dte_range=(14, 21),       # Front leg: 14-21 DTE
    back_dte_range=(35, 50),        # Back leg: 35-50 DTE
    option_type="C",                 # Calls only
    strike_selection="ATM",          # ATM strikes

    # IV criteria (strict)
    iv_contango_min=0.07,            # Minimum 7% IV contango
    iv_percentile_max=40.0,          # Front IV below 40th percentile
    min_iv_rank=30.0,                # IV rank between 30-70
    max_iv_rank=70.0,

    # Risk management
    profit_target=0.40,              # 40% profit target
    stop_loss=-0.60,                 # -60% stop loss
    delta_limit=0.25,                # Close if |delta| > 0.25
)

# Create strategy
strategy = IVBasedCalendarSpreadStrategy(config)

# Create backtest runner with validation
runner = OptionsBacktestRunner(
    strategy=strategy,
    data_provider=data_provider,
    option_chain_provider=chain_provider,
    initial_capital=100000,
    commission_per_contract=0.65,           # $0.65 per contract
    earnings_calendar_provider=earnings_provider,  # For validation
)

# Run backtest with pre-flight validation
result = runner.run(
    start_date=date(2023, 1, 1),
    end_date=date(2024, 12, 31),
    validate_data=True,  # Pre-flight validation enabled
)

# Analyze results
print(f"Total Return: {result.total_return_pct:.2f}%")
print(f"Win Rate: {result.winning_trades / result.num_trades * 100:.1f}%")
print(f"Profit Factor: {abs(result.avg_win / result.avg_loss):.2f}")
print(f"Max Drawdown: {result.max_drawdown_pct:.2f}%")

# Export results
result.equity_curve.write_csv("custom_equity_curve.csv")

import polars as pl
import json
pl.DataFrame(result.trades).write_csv("custom_trades.csv")

with open("custom_summary.json", "w") as f:
    json.dump(result.to_dict(), f, indent=2)
```

### Parallel Backtests for Multiple Configurations

```python
from multiprocessing import Pool
from functools import partial

def run_backtest_with_params(iv_min, symbols):
    """Run backtest with specific IV contango threshold."""
    config = IVBasedConfig(
        underlying_symbols=symbols,
        iv_contango_min=iv_min,
        # ... other params
    )

    strategy = IVBasedCalendarSpreadStrategy(config, earnings_provider)
    runner = OptionsBacktestRunner(strategy, data_provider, chain_provider, 100000)
    result = runner.run(date(2023, 1, 1), date(2024, 12, 31))

    return {
        'iv_contango_min': iv_min,
        'return_pct': result.total_return_pct,
        'num_trades': result.num_trades,
        'win_rate': result.winning_trades / result.num_trades * 100,
    }

# Test different IV thresholds
iv_thresholds = [0.03, 0.05, 0.07, 0.10]
symbols = ["AAPL", "MSFT", "GOOGL"]

with Pool(4) as pool:
    results = pool.starmap(run_backtest_with_params,
                          [(iv, symbols) for iv in iv_thresholds])

# Find best configuration
best = max(results, key=lambda x: x['return_pct'])
print(f"Best IV threshold: {best['iv_contango_min']}")
print(f"Return: {best['return_pct']:.2f}%")
```

### Compare All Three Strategies

```bash
# Run all three strategies for comparison
for strategy in generic_calendar pre_earnings iv_based; do
    uv run dlt-ibapi backtest-earnings-spreads \
        --strategy $strategy \
        --symbols AAPL MSFT GOOGL \
        --start-date 2023-01-01 \
        --end-date 2024-12-31 \
        --capital 100000 \
        --output ./results_${strategy}
done

# Compare results
uv run python -c "
import json
import polars as pl

strategies = ['generic_calendar', 'pre_earnings', 'iv_based']
results = []

for s in strategies:
    with open(f'./results_{s}/summary_{s}_2023-01-01_2024-12-31.json') as f:
        data = json.load(f)
        results.append({
            'strategy': s,
            'return_pct': data['total_return_pct'],
            'num_trades': data['num_trades'],
            'win_rate': data['win_rate'],
            'max_drawdown_pct': data['max_drawdown_pct'],
        })

df = pl.DataFrame(results)
print(df)
"
```

---

## Complete Workflow Example

```bash
# ============================================
# Complete workflow from scratch
# ============================================

# 1. Install dependencies
cd /Users/mohamedali/trading_project/dlt-ibapi
uv sync

# 2. Start IB Gateway (Paper Trading, Port 4002)
# (Do this manually in IB Gateway application)

# 3. Test connection
uv run dlt-ibapi test-connection

# 4. Download equity bars
uv run dlt-ibapi backfill-equity \
    AAPL MSFT GOOGL \
    --start-date 2023-01-01 \
    --end-date 2024-12-31 \
    --bar-size "1 day" \
    --pipeline-name equity_backfill

# 5. Download option bars (takes longer)
for symbol in AAPL MSFT GOOGL; do
    uv run dlt-ibapi backfill-options \
        $symbol \
        150.0 \
        --mode atm \
        --k-strikes 5 \
        --dte-range 7 90 \
        --start-date 2023-01-01 \
        --end-date 2024-12-31 \
        --bar-size "1 day" \
        --pipeline-name options_${symbol}
done

# 6. Snapshot option chains
for symbol in AAPL MSFT GOOGL; do
    uv run dlt-ibapi snapshot \
        $symbol \
        --min-dte 7 \
        --max-dte 90 \
        --pipeline-name chains_${symbol}
done

# 7. Download earnings calendar
cd /Users/mohamedali/trading_project/earnings-calendar-dlt
uv run python -m earnings_calendar.pipeline \
    --start-date 2023-01-01 \
    --end-date 2024-12-31

# 8. Verify all data
cd /Users/mohamedali/trading_project/dlt-ibapi
uv run dlt-ibapi stats ./data --dataset stocks
uv run dlt-ibapi stats ./data --dataset options
uv run dlt-ibapi stats ./data --dataset option_chains

# 9. Run backtest
uv run dlt-ibapi backtest-earnings-spreads \
    --strategy iv_based \
    --symbols AAPL MSFT GOOGL \
    --start-date 2023-01-01 \
    --end-date 2024-12-31 \
    --capital 100000 \
    --output ./backtest_results

# 10. View results
cat backtest_results/summary_iv_based_2023-01-01_2024-12-31.json
open backtest_results/equity_curve_iv_based_2023-01-01_2024-12-31.png
```

---

## Next Steps

- **Add More Symbols**: Expand to more tickers for diversification
- **Optimize Parameters**: Use the Python API to test different configurations
- **Live Trading**: Once satisfied with backtest results, consider live paper trading
- **Automated Pipeline**: Set up Dagster for automated daily data collection

---

## Additional Resources

- **Full Documentation**: `BACKTEST_IMPLEMENTATION_SUMMARY.md`
- **Architecture Guide**: `CLAUDE.md`
- **API Reference**: `docs/API_REFERENCE.md`
- **Backfill Guide**: `docs/BACKFILL_GUIDE.md`

---

**Last Updated**: 2025-11-13
