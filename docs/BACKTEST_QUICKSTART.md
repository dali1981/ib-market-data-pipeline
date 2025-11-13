# Options Backtesting - Quick Start Guide

**Complete guide to running earnings calendar spread backtests with dlt-ibapi**

---

## ⚠️ CRITICAL: Current Implementation Status

**THE BACKTEST IS CURRENTLY NON-FUNCTIONAL** due to fundamental IB API limitations.

### What's Broken

The backtest was implemented assuming the IB API provides historical option chain snapshots (bid/ask prices, volume, open interest for all options on past dates). **This assumption is incorrect.**

**IB API Limitation** (from [official docs](https://interactivebrokers.github.io/tws-api/historical_limitations.html)):
> "End of Day (EOD) data for options, FOPs, warrants and structured products" **cannot be retrieved**.

> "Expired options, FOPs, warrants and structured products" have **no historical data** accessible.

### What This Means

❌ **You CANNOT**:
- Get complete option chains for historical dates
- Screen all available options for "best spread" on past dates
- Get historical bid/ask spreads or volume/open interest
- Backtest strategies requiring expired options data

✅ **You CAN**:
- Get historical OHLCV bars for SPECIFIC option contracts (non-expired)
- Backtest using deterministic option selection rules (ATM, DTE range)
- Validate data availability before attempting backtest

### Current Workaround

Until properly reimplemented:

1. **Use the Validation System** to check data availability:
   ```python
   from dlt_ibapi.backtest import BacktestDataValidator, EarningsCalendarLoader

   loader = EarningsCalendarLoader()
   events = loader.load_file("earnings_2024-10-22.txt")

   validator = BacktestDataValidator(equity_reader, option_bars_reader)
   report = validator.validate_all(events, requirements)

   print(f"Valid events: {report.valid_events}/{report.total_events}")
   ```

2. **Manually implement earnings-driven logic** using option bars directly

3. **Contribute a fix** (see [GitHub issues](https://github.com/anthropics/claude-code/issues))

---

## Table of Contents

1. [Prerequisites](#prerequisites)
2. [Data Requirements](#data-requirements)
3. [IB API Data Limitations](#ib-api-data-limitations) 👈 **READ THIS FIRST**
4. [Step 1: Verify Data Availability](#step-1-verify-data-availability)
4. [Step 2: Download Required Data](#step-2-download-required-data)
5. [Step 3: Run Backtest](#step-3-run-backtest)
6. [Step 4: Analyze Results](#step-4-analyze-results)
7. [Troubleshooting](#troubleshooting)
8. [Advanced Usage](#advanced-usage)

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

## IB API Data Limitations

### Understanding What Data IS Available

The IB API provides **limited historical data** for options. Understanding these limitations is critical for backtest implementation.

#### ✅ Data You CAN Get

1. **Equity Bars (Historical OHLCV)**
   - Available for all past dates
   - All bar sizes supported (1 day, 1 hour, 5 mins, etc.)
   - Example:
   ```python
   from dlt_ibapi.repositories import EquityBarsReader

   reader = EquityBarsReader("./data", "stocks")
   bars = reader.get_bars(
       symbol="AAPL",
       bar_size="1 day",
       start_date=date(2023, 1, 1),
       end_date=date(2024, 12, 31),
   )
   ```

2. **Option Bars (Individual Contract OHLCV)**
   - Available for **specific non-expired options** only
   - Must know exact contract (strike, expiration, right)
   - Cannot query expired options
   - Example:
   ```python
   from dlt_ibapi.repositories import OptionBarsReader

   reader = OptionBarsReader("./data", "options")

   # Works: Get bars for specific non-expired contract
   bars = reader.get_bars(
       symbol="AAPL",
       strike=150.0,
       expiration=date(2024, 12, 20),
       right="C",  # Call
       bar_size="1 day",
       start_date=date(2024, 11, 1),
       end_date=date(2024, 11, 13),
   )
   ```

3. **Current Option Chain Parameters (Live Only)**
   - Available for current day only
   - Contains: Available strikes, expirations, contract IDs
   - Does NOT contain: Historical bid/ask, volume, open interest
   - Used for: Real-time option discovery, not backtesting

#### ❌ Data You CANNOT Get

From [IB API official documentation](https://interactivebrokers.github.io/tws-api/historical_limitations.html):

> **"End of Day (EOD) data for options, FOPs, warrants and structured products cannot be retrieved."**

> **"Expired options, FOPs, warrants and structured products have no historical data accessible."**

**What This Means**:

1. **No Historical Option Chain Snapshots**
   - Cannot retrieve "all available options with prices" for past dates
   - Cannot screen for "best spread" on historical dates
   - Cannot see bid/ask/volume/OI for past dates

2. **No Expired Options Data**
   - Once an option expires, ALL historical data becomes inaccessible
   - Cannot backtest strategies requiring expired contracts
   - Must collect data BEFORE expiration

3. **No EOD Option Data**
   - Cannot get historical closing prices for option chains
   - Cannot reconstruct complete option surfaces for past dates
   - Cannot validate historical IV calculations against snapshots

### Implications for Backtesting

**Traditional Approach (DOES NOT WORK)**:
```python
# ❌ This approach is impossible with IB API
for date in backtest_dates:
    # Get all available options on this date
    option_chain = get_historical_option_chain(date)  # NOT AVAILABLE

    # Screen for best spread
    best_spread = find_best_spread(option_chain)  # IMPOSSIBLE

    # Execute
    execute_spread(best_spread)
```

**Required Approach (WORKS)**:
```python
# ✅ This approach works with IB API limitations
for earnings_event in earnings_calendar:
    # 1. Determine options using RULES (not screening)
    front_month_options = find_options_by_dte_range(
        underlying=earnings_event.symbol,
        spot_price=get_spot_price(earnings_event.date),
        dte_range=(14, 21),  # Deterministic selection
        strike_selection="ATM",  # Rule-based
    )

    back_month_options = find_options_by_dte_range(
        underlying=earnings_event.symbol,
        spot_price=get_spot_price(earnings_event.date),
        dte_range=(35, 50),
        strike_selection="ATM",
    )

    # 2. Check if we collected option bars for these specific contracts
    if has_option_bars(front_month_options) and has_option_bars(back_month_options):
        # 3. Execute spread using pre-collected bars
        execute_spread(front_month_options, back_month_options)
    else:
        # 4. Skip - insufficient data
        log_skip_reason(f"Missing option bars for {earnings_event.symbol}")
```

### Data Collection Workflow

To backtest options strategies, you must:

**1. Identify Events in Advance**
   - Load earnings calendar from external source (Nasdaq)
   - File format: `/Users/mohamedali/Desktop/earnings_[date].txt`
   - Example structure:
   ```json
   {
     "data": {
       "rows": [
         {
           "symbol": "AAPL",
           "companyName": "Apple Inc.",
           "earningsDate": "2024-10-22",
           "earningsTime": "AMC",
           "epsForecast": "$0.41"
         }
       ]
     }
   }
   ```

**2. Determine Options Using Rules**
   - Select strikes: ATM, OTM by X%, etc.
   - Select expirations: Front month (14-21 DTE), back month (35-50 DTE)
   - No screening required - use deterministic rules

**3. Collect Option Bars BEFORE Expiration**
   ```bash
   # For each earnings event, collect option bars for selected contracts
   uv run dlt-ibapi backfill-options \
       AAPL \
       150.0 \
       --mode atm \
       --k-strikes 5 \
       --dte-range 7 90 \
       --start-date 2024-01-01 \
       --end-date 2024-12-31 \
       --bar-size "1 day"
   ```

**4. Validate Data Availability**
   ```python
   from dlt_ibapi.backtest import BacktestDataValidator, EarningsCalendarLoader
   from dlt_ibapi.repositories import EquityBarsReader, OptionBarsReader

   # Load earnings events
   loader = EarningsCalendarLoader()
   events = loader.load_file("earnings_2024-10-22.txt")

   # Create validator
   equity_reader = EquityBarsReader("./data", "stocks")
   option_bars_reader = OptionBarsReader("./data", "options")

   validator = BacktestDataValidator(equity_reader, option_bars_reader)

   # Validate all events
   report = validator.validate_all(events, requirements)

   print(f"Valid events: {report.valid_events}/{report.total_events}")
   print(f"Invalid events: {report.invalid_events}")

   # Review skip reasons
   for event_report in report.events_reports:
       if not event_report.is_valid:
           print(f"{event_report.symbol}: {event_report.skip_reason}")

   # Export detailed report
   validator.export_validation_report(report, "./validation_report.json")
   ```

**5. Run Backtest (Only on Validated Events)**
   - Backtest uses validation to filter events
   - Only trades on events with sufficient data
   - Logs comprehensive skip reasons for invalid events

### Working with Option Bars Directly

Since option chain snapshots are not available, use `OptionBarsReader` to query specific contracts:

```python
from dlt_ibapi.repositories import OptionBarsReader
from datetime import date

reader = OptionBarsReader("./data", "options")

# Example 1: Get bars for specific contract
bars = reader.get_bars(
    symbol="AAPL",
    strike=150.0,
    expiration=date(2024, 12, 20),
    right="C",
    bar_size="1 day",
    start_date=date(2024, 11, 1),
    end_date=date(2024, 11, 13),
)

print(f"Retrieved {len(bars)} bars")
print(bars[["time", "open", "high", "low", "close", "volume"]])

# Example 2: Check if contract has sufficient coverage
available_dates = reader.get_available_dates(
    symbol="AAPL",
    strike=150.0,
    expiration=date(2024, 12, 20),
    right="C",
    bar_size="1 day",
)

required_dates = get_trading_days(date(2024, 11, 1), date(2024, 11, 13))
coverage = len(available_dates) / len(required_dates)

if coverage >= 0.95:
    print("✓ Sufficient coverage for backtest")
else:
    print(f"✗ Insufficient coverage: {coverage:.1%}")

# Example 3: Query multiple contracts (calendar spread)
front_month = reader.get_bars(
    symbol="AAPL", strike=150.0, expiration=date(2024, 11, 20),
    right="C", bar_size="1 day",
    start_date=date(2024, 11, 1), end_date=date(2024, 11, 13),
)

back_month = reader.get_bars(
    symbol="AAPL", strike=150.0, expiration=date(2024, 12, 20),
    right="C", bar_size="1 day",
    start_date=date(2024, 11, 1), end_date=date(2024, 11, 13),
)

# Calculate calendar spread value
spread_value = back_month["close"] - front_month["close"]
print(f"Spread P&L: ${spread_value.sum():.2f}")
```

### Key Takeaways

1. **You CANNOT backtest** strategies that require:
   - Historical option chain screening
   - Expired options data
   - Historical bid/ask spreads or volume/OI

2. **You CAN backtest** strategies that use:
   - Deterministic option selection (ATM, DTE rules)
   - Pre-collected option bars for specific contracts
   - Earnings events as entry triggers

3. **Data collection must be proactive**:
   - Collect option bars BEFORE options expire
   - Use external earnings calendar (Nasdaq)
   - Validate data availability before backtesting

4. **Use validation system** to:
   - Check data coverage for each earnings event
   - Filter invalid events with detailed reasons
   - Generate JSON reports for debugging

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
strategy = IVBasedCalendarSpreadStrategy(config, earnings_provider)

# Create backtest runner
runner = OptionsBacktestRunner(
    strategy=strategy,
    data_provider=data_provider,
    option_chain_provider=chain_provider,
    initial_capital=100000,
    commission_per_contract=0.65,    # $0.65 per contract
)

# Run backtest
result = runner.run(
    start_date=date(2023, 1, 1),
    end_date=date(2024, 12, 31),
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
