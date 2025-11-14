# Calendar Spread Backtesting Guide

Complete guide for backtesting earnings-based calendar spread strategies using `dlt-ibapi`.

## Table of Contents

1. [Overview](#overview)
2. [Data Requirements](#data-requirements)
3. [Strategy Variants](#strategy-variants)
4. [Complete Workflow](#complete-workflow)
5. [Running Backtests](#running-backtests)
6. [Understanding Results](#understanding-results)
7. [Data Collection Details](#data-collection-details)
8. [Troubleshooting](#troubleshooting)

---

## Overview

### What is a Calendar Spread?

A **calendar spread** (time spread) profits from:
- **Time decay differential** between near-term and longer-term options
- **Implied volatility (IV) expansion** before earnings and contraction after

**Position Structure:**
```
SELL: Front-month option (14-25 DTE) - expires shortly after earnings
BUY:  Back-month option (35-60 DTE) - expires well after earnings
Strike: ATM or near current price
Type: Usually calls
```

**Key Insight:** Exit BEFORE earnings announcement to capture IV expansion without gap risk.

---

## Data Requirements

### ✅ What You Need to Collect

| Data Type | Purpose | Collection Method | Status |
|-----------|---------|-------------------|--------|
| **Earnings Calendar** | Event dates/times | `load-earnings` | ✅ Ready |
| **Option Chain Snapshots** | Available strikes/expirations | `snapshot` | ✅ Ready |
| **Option Bars (OHLCV)** | Option pricing | `backfill-options` | ✅ Ready |
| **Equity Bars (OHLCV)** | Underlying prices | `backfill-equity` | ✅ Ready |
| **Greeks** | Risk metrics (delta, gamma, vega, theta) | Calculated on-the-fly | ✅ Automatic |

### ⚠️ Important: Greeks Calculation

**Greeks are NOT stored** - they're calculated dynamically during backtesting:

```python
Process:
1. Read option mid-price from option bars: (high + low) / 2
2. Read underlying spot price from equity bars
3. Calculate IV by reverse-engineering Black-Scholes from market price
4. Calculate Greeks using IV and Black-Scholes model
```

**Why this works:**
- Uses actual market prices (reflects reality)
- No need to store massive datasets
- Accurate enough for strategy validation
- Black-Scholes approximation (acceptable for short-dated options)

---

## Strategy Variants

The backtest supports three calendar spread strategies:

### 1. Generic Calendar Spread

**When to use:** Baseline strategy without earnings timing.

**Configuration:**
```python
CalendarSpreadConfig(
    underlying_symbols=["AAPL", "MSFT", "GOOGL"],
    front_dte_range=(10, 20),      # Sell 10-20 DTE
    back_dte_range=(30, 50),       # Buy 30-50 DTE
    strike_selection="ATM",        # At-the-money
    option_type="C",               # Calls
    profit_target=0.30,            # Exit at 30% gain
    stop_loss=-0.50,               # Cut loss at -50%
)
```

**Entry:** Anytime (no earnings timing)
**Exit:** Profit target or stop loss

---

### 2. Pre-Earnings Calendar Spread

**When to use:** Time trades around earnings announcements.

**Configuration:**
```python
PreEarningsConfig(
    underlying_symbols=["AAPL", "MSFT", "GOOGL"],
    entry_window=(10, 25),         # Enter 10-25 days before earnings
    exit_buffer=2,                 # Exit 2 days before announcement
    front_dte_range=(14, 25),      # Front leg crosses earnings
    back_dte_range=(35, 60),       # Back leg after earnings
    option_type="C",
    profit_target=0.30,
)
```

**Entry:** 10-25 days before earnings (when IV starts ramping)
**Exit:** 2 days before earnings (capture IV expansion, avoid gap risk)

**Key Behavior:**
- Automatically finds earnings events from calendar
- Times entry to capture IV ramp-up phase
- Exits before announcement to avoid assignment/gap risk

---

### 3. IV-Based Calendar Spread (Most Sophisticated)

**When to use:** Add strict IV filtering for better entries.

**Configuration:**
```python
IVBasedConfig(
    underlying_symbols=["AAPL", "MSFT", "GOOGL"],
    entry_window=(10, 25),
    exit_buffer=2,
    iv_contango_min=0.05,          # Require 5% term structure slope
    iv_percentile_max=50.0,        # Only enter when IV < median
    front_dte_range=(14, 25),
    back_dte_range=(35, 60),
    option_type="C",
)
```

**Additional Entry Filters:**

1. **IV Term Structure (Contango):**
   ```
   Require: Back-month IV > Front-month IV by at least 5%

   Example:
   Front (21 DTE): 35% IV
   Back (49 DTE):  40% IV  ← 5% higher (OK to enter)

   Avoid inverted term structure:
   Front: 60% IV  ← Already inflated!
   Back:  42% IV  ← Too low differential
   ```

2. **IV Percentile Filter:**
   ```
   Only enter when current IV < historical 50th percentile
   Ensures "room" for IV to expand before earnings
   ```

---

## Complete Workflow

### Step 1: Load Earnings Calendar

```bash
# Download earnings data (Nasdaq JSON format)
# See EARNINGS_SNAPSHOT_WORKFLOW.md for data sources

# Load into Parquet
dlt-ibapi load-earnings ./earnings_2025-11-13.json \
  --start-date 2025-11-13 \
  --end-date 2025-12-31

# Verify loaded data
dlt-ibapi list-earnings --days-ahead 30
```

**Output Location:** `./data/earnings/earnings_calendar/*.parquet`

---

### Step 2: Resolve Contracts (Pre-populate Cache)

```bash
# Validate symbols before expensive data collection
dlt-ibapi resolve-contracts --earnings-date 2025-11-13
```

**What this does:**
- Checks which symbols exist in IB's database
- Pre-populates contract cache (`.dlt-ibapi/cache/contracts/`)
- Identifies invalid/delisted symbols early
- Saves time during subsequent operations

---

### Step 3: Capture Option Chain Snapshots

```bash
# Snapshot for upcoming earnings (captures available strikes/expirations)
dlt-ibapi snapshot --earnings-date 2025-11-13 \
  --min-dte 7 \
  --max-dte 60

# Or snapshot specific symbols
dlt-ibapi snapshot AAPL --min-dte 7 --max-dte 60
dlt-ibapi snapshot MSFT --min-dte 7 --max-dte 60
```

**Output Location:** `./data/option_chains/option_chain_snapshot/*.parquet`

**What's captured:**
- Available strikes (e.g., 140, 145, 150, 155, ...)
- Available expirations (e.g., 20251115, 20251220, ...)
- Snapshot date (when metadata was captured)

**NOT captured:** Prices, IV, Greeks (these come from option bars)

---

### Step 4: Backfill Option Bars (Historical Prices)

```bash
# Backfill options for earnings symbols
# You need BOTH front-leg and back-leg expirations

# Example: AAPL at $180
dlt-ibapi backfill-options AAPL 180.0 \
  --start 2024-01-01 \
  --end 2024-12-31 \
  --mode atm \
  --k-strikes 5 \
  --min-dte 7 \
  --max-dte 60 \
  --bar-size "1 day"

# Repeat for other symbols
dlt-ibapi backfill-options MSFT 420.0 --mode atm --k-strikes 5
dlt-ibapi backfill-options GOOGL 170.0 --mode atm --k-strikes 5
```

**Output Location:** `./data/options/option_bars/*.parquet`

**What's captured:**
- Daily OHLCV for specific option contracts
- Underlying symbol, strike, expiry, right (C/P)
- Bar size (1 day recommended)
- Volume and weighted average price (WAP)

**Critical:** You need historical bars for BOTH:
- Front-leg contracts (14-25 DTE at entry)
- Back-leg contracts (35-60 DTE at entry)

---

### Step 5: Backfill Equity Bars (Underlying Prices)

```bash
# Backfill underlying stock prices
dlt-ibapi backfill-equity AAPL MSFT GOOGL \
  --start 2024-01-01 \
  --end 2024-12-31 \
  --bar-size "1 day"
```

**Output Location:** `./data/stocks/equity_bars/*.parquet`

**What's captured:**
- Daily OHLCV for underlying stocks
- Used for: Strike selection (ATM), Greeks calculation

---

### Step 6: Verify Data Completeness

```bash
# Check all datasets
dlt-ibapi stats ./data --dataset earnings
dlt-ibapi stats ./data --dataset option_chains
dlt-ibapi stats ./data --dataset options
dlt-ibapi stats ./data --dataset stocks
```

**Expected Output:**
```
earnings:
  Rows: 500 earnings events
  Symbols: AAPL, MSFT, GOOGL, ...
  Date range: 2025-11-13 to 2025-12-31

option_chains:
  Rows: 15 snapshots
  Symbols: AAPL, MSFT, GOOGL

options:
  Rows: 50,000+ option bars
  Symbols: AAPL, MSFT, GOOGL
  Date range: 2024-01-01 to 2024-12-31

stocks:
  Rows: 750+ equity bars
  Symbols: AAPL, MSFT, GOOGL
  Date range: 2024-01-01 to 2024-12-31
```

---

## Running Backtests

### CLI Command (Easiest)

```bash
# Run IV-based calendar spread backtest
dlt-ibapi backtest-earnings-spreads \
  --strategy iv_based \
  --symbols AAPL MSFT GOOGL \
  --start-date 2024-01-01 \
  --end-date 2024-12-31 \
  --capital 100000 \
  --output ./backtest_results
```

**Output Files:**
```
./backtest_results/
  summary_iv_based_2024-01-01_2024-12-31.json     # Performance metrics
  equity_curve_iv_based_2024-01-01_2024-12-31.csv # Daily portfolio value
  equity_curve_iv_based_2024-01-01_2024-12-31.png # Chart
  trades_iv_based_2024-01-01_2024-12-31.csv       # Individual trade log
```

**Strategy Options:**
- `--strategy generic_calendar` - Baseline strategy
- `--strategy pre_earnings` - Earnings-timed strategy
- `--strategy iv_based` - IV-filtered strategy (recommended)

---

### Python API (Advanced)

```python
from datetime import date
from dlt_ibapi.backtest import (
    IBBacktestDataProvider,
    EarningsCalendarProvider,
    OptionsChainProvider,
    OptionsBacktestRunner,
)
from tools.strategies.options import (
    IVBasedCalendarSpreadStrategy,
    IVBasedConfig,
)

# 1. Initialize data providers
data_provider = IBBacktestDataProvider("./data")
chain_provider = OptionsChainProvider(data_provider.option_chain_reader)
earnings_provider = EarningsCalendarProvider("./data", "earnings")

# 2. Configure strategy
config = IVBasedConfig(
    underlying_symbols=["AAPL", "MSFT", "GOOGL"],
    entry_window=(10, 25),         # Enter 10-25 days before earnings
    exit_buffer=2,                 # Exit 2 days before
    iv_contango_min=0.05,          # Require 5% term structure slope
    iv_percentile_max=50.0,        # Only enter when IV < median
    front_dte_range=(14, 25),
    back_dte_range=(35, 60),
    option_type="C",
)

strategy = IVBasedCalendarSpreadStrategy(config, earnings_provider)

# 3. Create backtest runner
runner = OptionsBacktestRunner(
    strategy=strategy,
    data_provider=data_provider,
    option_chain_provider=chain_provider,
    initial_capital=100000,
    commission_per_contract=0.65,  # $0.65 per contract
    earnings_calendar_provider=earnings_provider,
)

# 4. Run backtest with validation
result = runner.run(
    start_date=date(2024, 1, 1),
    end_date=date(2024, 12, 31),
    validate_data=True,  # Pre-flight data availability check
)

# 5. Analyze results
print(f"Total Return: ${result.total_return:,.2f} ({result.total_return_pct:.2f}%)")
print(f"Win Rate: {result.win_rate:.1f}%")
print(f"Number of Trades: {result.num_trades}")
print(f"Profit Factor: {result.profit_factor:.2f}")
print(f"Max Drawdown: ${result.max_drawdown:,.2f} ({result.max_drawdown_pct:.2f}%)")
```

---

## Understanding Results

### Summary Metrics (JSON)

```json
{
  "initial_capital": 100000,
  "final_value": 115000,
  "total_return": 15000,
  "total_return_pct": 15.0,
  "num_trades": 45,
  "winning_trades": 30,
  "losing_trades": 15,
  "win_rate": 66.7,
  "avg_win": 750.0,
  "avg_loss": -350.0,
  "profit_factor": 2.14,
  "max_drawdown": -8500,
  "max_drawdown_pct": -7.5,
  "sharpe_ratio": 1.25,
  "start_date": "2024-01-01",
  "end_date": "2024-12-31"
}
```

**Key Metrics:**
- **Total Return %**: Overall gain/loss
- **Win Rate**: % of profitable trades
- **Profit Factor**: Gross profit / Gross loss (> 1.0 is profitable)
- **Max Drawdown**: Largest peak-to-trough decline
- **Sharpe Ratio**: Risk-adjusted return (> 1.0 is good, > 2.0 is excellent)

---

### Equity Curve (CSV)

```csv
timestamp,portfolio_value,cash,positions_value,daily_return_pct
2024-01-01,100000,100000,0,0.0
2024-01-15,100250,98500,1750,0.25
2024-01-30,101500,99200,2300,1.25
2024-02-14,101200,99800,1400,-0.30
...
```

**Columns:**
- `timestamp`: Date
- `portfolio_value`: Total account value
- `cash`: Available cash
- `positions_value`: Market value of open positions
- `daily_return_pct`: Daily return percentage

---

### Trade Log (CSV)

```csv
entry_date,exit_date,symbol,strike,front_expiry,back_expiry,entry_price,exit_price,pnl,pnl_pct,days_held,exit_reason
2024-01-15,2024-02-10,AAPL,180.0,2024-02-16,2024-03-15,2.50,3.25,75.0,30.0,26,profit_target
2024-02-01,2024-02-26,MSFT,420.0,2024-03-01,2024-04-19,3.10,2.80,-30.0,-9.7,25,stop_loss
...
```

**Columns:**
- `entry_date`: When spread was opened
- `exit_date`: When spread was closed
- `symbol`: Underlying
- `strike`: Common strike price
- `front_expiry`: Front leg expiration
- `back_expiry`: Back leg expiration
- `entry_price`: Net debit paid to enter
- `exit_price`: Net credit received to exit
- `pnl`: Profit/loss in dollars
- `pnl_pct`: Profit/loss percentage
- `days_held`: Holding period
- `exit_reason`: Why trade closed (profit_target, stop_loss, earnings_buffer, expiration)

---

## Data Collection Details

### Data Collection Timeline

For a backtest covering **2024-01-01 to 2024-12-31**, you need:

1. **Earnings Calendar**
   - Load events from 2023-12-15 to 2025-01-15
   - Reason: Need 15 days before/after for entry window

2. **Option Chain Snapshots**
   - Capture daily snapshots throughout 2024
   - **Critical:** Cannot backfill expired snapshots
   - Must be collected in real-time or historical data source

3. **Option Bars**
   - Backfill from 2023-12-01 to 2024-12-31
   - Reason: Need pricing data before first earnings event
   - Include contracts with expirations through 2025-02-28
   - Reason: Back-leg expires 35-60 days after last earnings event

4. **Equity Bars**
   - Backfill from 2023-12-01 to 2024-12-31
   - Used for strike selection and Greeks

---

### Data Volume Estimates

For **3 symbols, 12 months, daily bars:**

| Dataset | Approximate Size | Row Count |
|---------|------------------|-----------|
| Earnings | 5 MB | 500-1000 events |
| Option Chains | 50 MB | 500-1000 snapshots |
| Option Bars | 500 MB - 2 GB | 50,000-200,000 bars |
| Equity Bars | 5 MB | 750-1000 bars |

**Total:** ~1-3 GB for complete backtest dataset

---

### Missing Data Handling

The backtest has built-in validation:

```python
# Pre-flight validation checks:
1. Earnings events exist for date range
2. Option chain snapshots exist for entry dates
3. Option bars exist for front and back legs
4. Equity bars exist for underlying
```

**If data is missing:**
- Trade is skipped (not entered)
- Warning logged
- Backtest continues with remaining trades

**Validation Report Example:**
```
Data Validation Report:
✓ Earnings calendar: 45 events found
✓ Option chain snapshots: 42/45 (93% coverage)
⚠ Option bars: 38/45 (84% coverage) - 7 missing
✓ Equity bars: 45/45 (100% coverage)

Missing Data:
  2024-03-15 AAPL: No option bars for back leg (expiry 2024-05-17)
  2024-06-20 MSFT: No option chain snapshot
  ...

Proceeding with 38 valid earnings events.
```

---

## Troubleshooting

### Issue: "No option bars found for contract"

**Cause:** Option bars not backfilled for required strikes/expirations.

**Solution:**
```bash
# Backfill wider strike range
dlt-ibapi backfill-options AAPL 180.0 \
  --mode atm \
  --k-strikes 7 \  # Increase from 5 to 7
  --min-dte 7 \
  --max-dte 75     # Increase from 60 to 75
```

---

### Issue: "Greeks calculation failed"

**Cause:** Missing underlying price or invalid option price.

**Solution:**
1. Verify equity bars exist:
   ```bash
   dlt-ibapi stats ./data --dataset stocks
   ```

2. Check option bars have valid prices:
   ```python
   from dlt_ibapi.repositories import OptionBarsReader
   reader = OptionBarsReader("./data", "options")
   bars = reader.get_bars("AAPL", 180.0, date(2024, 3, 15), "C", "2024-04-19")
   print(bars[['date', 'close', 'volume']])
   ```

3. Ensure close prices > 0 and volume > 0

---

### Issue: "IV calculation convergence error"

**Cause:** Option price too far from Black-Scholes model (deep ITM/OTM, low volume).

**Solution:**
- This is expected for illiquid contracts
- Backtest skips these trades automatically
- Focus on liquid stocks (AAPL, MSFT, GOOGL, etc.)
- Filter by minimum volume in option bars

---

### Issue: "No earnings events found in date range"

**Cause:** Earnings calendar not loaded or date filter excludes data.

**Solution:**
```bash
# Check earnings data
dlt-ibapi list-earnings --days-ahead 365

# Reload with broader date range
dlt-ibapi load-earnings earnings.json  # No date filters
```

---

### Issue: "Validation shows low coverage"

**Cause:** Missing snapshots or option bars for many dates.

**Solution:**

1. **Missing Snapshots:**
   - Cannot backfill (metadata disappears at expiry)
   - Must be collected in real-time going forward
   - For historical testing: Use dates where you have snapshots

2. **Missing Option Bars:**
   - Backfill expired contracts (if still available in IB):
     ```bash
     dlt-ibapi backfill-options AAPL 180.0 --start 2024-01-01 --end 2024-12-31
     ```
   - For very old data: May not be available from IB

---

## Best Practices

### 1. Start Small

```bash
# Test with 1 symbol, 1 month first
dlt-ibapi backtest-earnings-spreads \
  --symbols AAPL \
  --start-date 2024-11-01 \
  --end-date 2024-11-30 \
  --capital 10000
```

---

### 2. Focus on Liquid Stocks

**Recommended symbols:**
- AAPL, MSFT, GOOGL, AMZN, TSLA (mega-cap tech)
- META, NVDA, AMD (high IV tech)
- SPY, QQQ (ETFs - very liquid)

**Avoid:**
- Small-cap stocks (< $1B market cap)
- Low volume options (< 100 contracts/day)
- Penny stocks

---

### 3. Collect Data Regularly

```bash
# Daily cron job for ongoing data collection
# Run at market close (4:30 PM ET)

# 1. Update earnings calendar (weekly)
dlt-ibapi load-earnings latest_earnings.json

# 2. Snapshot upcoming earnings (daily)
dlt-ibapi snapshot --earnings-date $(date -d '+14 days' +%Y-%m-%d) --min-dte 7 --max-dte 60

# 3. Backfill new option contracts (daily)
dlt-ibapi backfill-options AAPL 180.0 --mode atm --k-strikes 5
```

---

### 4. Validate Before Long Backtests

```python
# Always use validate_data=True
result = runner.run(
    start_date=start,
    end_date=end,
    validate_data=True,  # Pre-flight check
)
```

This prevents wasting hours on incomplete data.

---

## Next Steps

1. **Collect Earnings Data:**
   - Follow [EARNINGS_SNAPSHOT_WORKFLOW.md](./EARNINGS_SNAPSHOT_WORKFLOW.md)

2. **Run Your First Backtest:**
   ```bash
   dlt-ibapi backtest-earnings-spreads \
     --symbols AAPL \
     --start-date 2024-11-01 \
     --end-date 2024-11-30
   ```

3. **Analyze Results:**
   - Review summary metrics
   - Plot equity curve
   - Analyze individual trades

4. **Iterate:**
   - Adjust strategy parameters
   - Try different symbols
   - Compare strategy variants

---

## Related Documentation

- [EARNINGS_SNAPSHOT_WORKFLOW.md](./EARNINGS_SNAPSHOT_WORKFLOW.md) - Earnings data collection
- [BACKTEST_QUICKSTART.md](./BACKTEST_QUICKSTART.md) - General backtesting guide
- [API_REFERENCE.md](./API_REFERENCE.md) - Complete API documentation
- [README.md](../README.md) - Main project documentation
