 # dlt-ibapi

DLT connector for Interactive Brokers - ingest market data from IB Gateway/TWS into data pipelines.

## Table of Contents

- [Overview](#overview)
- [Installation](#installation)
- [Quick Start](#quick-start)
- [Documentation](#documentation)
- [Features](#features)
  - [Data Storage](#data-storage)
  - [Historical Data Backfilling](#historical-data-backfilling)
  - [Orchestration with Dagster](#orchestration-with-dagster)
  - [Backtesting](#backtesting)
- [Configuration](#configuration)
- [Dataset Organization](#dataset-organization)
- [Data Quality & Deduplication](#data-quality--deduplication)
- [Notebooks](#notebooks)
- [Development](#development)
- [Troubleshooting](#troubleshooting)

## Documentation

Detailed documentation is available in the `docs/` directory:

**Getting Started:**
- **[Backfill Guide](docs/BACKFILL_GUIDE.md)** - Complete guide to historical data backfilling with gap detection
- **[Earnings Snapshot Workflow](docs/EARNINGS_SNAPSHOT_WORKFLOW.md)** - Batch snapshot option chains for stocks with earnings
- **[Earnings Guide](docs/EARNINGS_GUIDE.md)** - Load and query earnings calendar data

**Automation:**
- **[Automated Calendar Spread Workflow](docs/AUTOMATED_CALENDAR_SPREAD_WORKFLOW.md)** - Complete automated data collection pipeline for calendar spreads

**Backtesting:**
- **[Calendar Spread Backtest Guide](docs/CALENDAR_SPREAD_BACKTEST_GUIDE.md)** - Complete guide to backtesting earnings calendar spreads
- **[Backtest Quick Reference](docs/BACKTEST_QUICK_REFERENCE.md)** - Fast reference for running backtests
- **[Backtest Quick Start](docs/BACKTEST_QUICKSTART.md)** - Options backtesting guide with daily data collection workflow

**Technical:**
- **[API Reference](docs/API_REFERENCE.md)** - Complete Python API documentation
- **[Architecture](docs/ARCHITECTURE.md)** - DLT vs Dagster layer separation
- **[CLI Architecture](docs/CLI_ARCHITECTURE.md)** - CLI refactoring and modular design
- **[Parquet Migration](docs/PARQUET_MIGRATION.md)** - Parquet-first storage architecture
- **[Batch Tick Backfill Improvements](docs/BATCH_TICK_BACKFILL_IMPROVEMENTS.md)** - Earnings timing filter and flexible batch processing
- **[Earnings Timing Calendar Fix](docs/EARNINGS_TIMING_CALENDAR_FIX.md)** - Market calendar bug fix for weekend/holiday handling

## Overview

`dlt-ibapi` is a [dlt](https://dlthub.com/) source connector that allows you to easily extract market data from Interactive Brokers and load it into any destination (DuckDB, PostgreSQL, Snowflake, BigQuery, etc.).

Built on top of `ib-connector`, it provides clean, composable DLT resources for:
- Historical bar data (OHLCV)
- Contract details and specifications
- Option chains and parameters
- Market data snapshots

## Installation

```bash
# Install from source (development)
cd /path/to/ib-connector
uv sync

cd /path/to/dlt-ibapi
uv sync

# Or install as a dependency in your project
uv add dlt-ibapi

# Verify installation
dlt-ibapi version
```

After installation, the `dlt-ibapi` CLI command will be available.

## Prerequisites

1. **IB Gateway or TWS** running locally or remotely
2. **API connections enabled** in IB Gateway/TWS settings
3. **Python >= 3.10**

## Quick Start

### Basic Historical Data Pipeline

```python
import dlt
from dlt_ibapi import ib_historical_bars

# Create a pipeline to Parquet files (recommended)
pipeline = dlt.pipeline(
    pipeline_name="ib_market_data",
    destination=dlt.destinations.filesystem(bucket_url="data"),
    dataset_name="stocks",
)

# Fetch AAPL historical bars
data = ib_historical_bars(
    symbol="AAPL",
    exchange="SMART",
    currency="USD",
)

# Run the pipeline - data saved as Parquet with Hive partitioning
info = pipeline.run(data, loader_file_format="parquet")
print(info)

# Query the data using DuckDB
import duckdb
conn = duckdb.connect(":memory:")
df = conn.execute("""
    SELECT * FROM parquet_scan('data/stocks/**/*.parquet', hive_partitioning=true)
    WHERE symbol = 'AAPL'
    ORDER BY time DESC
    LIMIT 10
""").df()
print(df)
```

> **Note**: As of version 0.2.0, `dlt-ibapi` uses Parquet files with Hive-style partitioning by default for better performance and storage efficiency. Data is partitioned by date and symbol for optimized queries.

### Multiple Symbols Pipeline

```python
import dlt
from dlt_ibapi import ib_source

# Define symbols to track
symbols = ["AAPL", "GOOGL", "MSFT", "TSLA"]

# Create combined source
source = ib_source(
    symbols=symbols,
    include_historical=True,
    include_contract_details=True,
)

# Load to PostgreSQL
pipeline = dlt.pipeline(
    pipeline_name="ib_stocks",
    destination="postgres",
    dataset_name="market_data",
)

info = pipeline.run(source)
print(info)
```

### Contract Details

```python
from dlt_ibapi import ib_contract_details

# Fetch contract specifications
contracts = ib_contract_details(
    symbols=["AAPL", "GOOGL"],
    exchange="SMART",
    currency="USD",
)

pipeline = dlt.pipeline(
    pipeline_name="ib_contracts",
    destination="duckdb",
    dataset_name="reference_data",
)

pipeline.run(contracts)
```

### Option Chain Data

```python
from dlt_ibapi import ib_option_chain

# Fetch option chain for AAPL (you need the contract ID)
options = ib_option_chain(
    symbol="AAPL",
    conid=265598,  # AAPL contract ID
    exchange="SMART",
)

pipeline.run(options)
```

## Features

### Data Storage

`dlt-ibapi` uses **Parquet files with Hive-style partitioning** for optimal storage and query performance.

### Partitioning Strategy

Data is automatically partitioned by:
- **date**: ISO format (YYYY-MM-DD) for time-based filtering
- **symbol**: Stock/underlying symbol for symbol-based filtering

Directory structure:
```
data/
├── stocks/
│   └── equity_bars_backfill/
│       └── date=2025-10-20/
│           ├── symbol=AAPL/*.parquet
│           └── symbol=MSFT/*.parquet
└── options/
    ├── option_bars_backfill/
    │   └── date=2025-10-20/
    │       └── symbol=AAPL/*.parquet
    └── option_chain_snapshot/
        └── date=2025-10-20/
            └── underlying=AAPL/*.parquet
```

### Querying Parquet Data

Use DuckDB for efficient querying:

```python
import duckdb

# Query equity bars
conn = duckdb.connect(":memory:")
df = conn.execute("""
    SELECT * FROM parquet_scan('data/stocks/**/*.parquet', hive_partitioning=true)
    WHERE symbol = 'AAPL' AND date >= '2025-10-01'
    ORDER BY time
""").df()
```

**Benefits**:
- **10x compression**: Parquet typically achieves 10x better compression than raw databases
- **Predicate pushdown**: Only reads relevant partitions (fast filtering on date/symbol)
- **Hybrid query support**: Small queries use DuckDB, large scans use PyArrow
- **Cloud-ready**: Works with S3, GCS, Azure Blob Storage

### Reader Repositories

For convenience, use the provided readers:

```python
from dlt_ibapi.repositories import EquityBarsReader, OptionBarsReader

# Initialize reader (points to Parquet directory)
reader = EquityBarsReader("data", "stocks")

# Get bars with automatic PyArrow optimization
bars = reader.get_bars(
    symbol="AAPL",
    bar_size="1 day",
    start_date=date(2025, 10, 1),
    end_date=date(2025, 10, 20),
)

# Metadata queries use DuckDB
symbols = reader.get_available_symbols("1 day")
date_range = reader.get_date_range("AAPL", "1 day")
```

### Historical Data Backfilling

`dlt-ibapi` provides comprehensive backfill infrastructure for **gap-aware historical data collection** with intelligent contract selection for options.

> **📖 See [Backfill Guide](docs/BACKFILL_GUIDE.md) for complete documentation**

### Key Features

- **Gap Detection**: Only fetches missing data (idempotent backfills)
- **Contract Selection**: Flexible strategies for option contracts (ATM, moneyness, delta)
- **CLI & Python API**: Choose your interface
- **Multiple Bar Sizes**: From 1-second to daily bars

### Quick Start: Equity Backfill

```python
import dlt
from datetime import date, timedelta
from dlt_ibapi import backfill_equity_bars

# Create pipeline with Parquet storage
pipeline = dlt.pipeline(
    pipeline_name="ib_stocks",
    destination=dlt.destinations.filesystem(bucket_url="data"),
    dataset_name="stocks",
)

# Backfill AAPL daily bars (last 30 days)
data = backfill_equity_bars(
    symbol="AAPL",
    database_path="data",  # Points to Parquet directory
    dataset_name="stocks",
    start_date=date.today() - timedelta(days=30),
    end_date=date.today(),
    bar_size="1 day",
)

# Run pipeline
info = pipeline.run(data)
```

**CLI equivalent:**
```bash
dlt-ibapi backfill-equity AAPL --bar-size "1 day"
```

### Option Bars Backfill

Option backfilling requires two steps:

**Step 1: Capture Option Chain Snapshot**

```python
from dlt_ibapi import snapshot_option_chain

# Capture available strikes and expirations
snapshot_data = snapshot_option_chain(
    underlying="AAPL",
    snapshot_date=date.today(),
    min_dte=7,   # At least 7 days to expiration
    max_dte=60,  # At most 60 days to expiration
)

pipeline.run(snapshot_data, write_disposition="replace")
```

**Step 2: Backfill Option Bars**

```python
from dlt_ibapi import backfill_option_bars
from dlt_ibapi.backfill import OptionBackfillConfig, ContractSelectionMode

# Configure backfill with ATM contract selection
config = OptionBackfillConfig(
    start_date=date.today() - timedelta(days=7),
    end_date=date.today(),
    bar_size="1 day",
    selection_mode=ContractSelectionMode.K_AROUND_ATM,
    k_strikes=3,  # 3 strikes on each side of ATM
    min_dte=7,
    max_dte=60,
)

# Backfill with gap detection
backfill_data = backfill_option_bars(
    underlying="AAPL",
    spot_price=150.0,  # Current AAPL price
    database_path="ib_option_chains.duckdb",
    dataset_name="options",
    backfill_config=config,
)

pipeline.run(backfill_data, write_disposition="append")
```

**CLI equivalent:**
```bash
# Step 1: Capture snapshot
dlt-ibapi snapshot AAPL --min-dte 7 --max-dte 60

# Step 2: Backfill
dlt-ibapi backfill-options AAPL 150.0 --mode atm --k-strikes 3

# Batch backfill all symbols with earnings on specific date
# Automatically selects spot prices based on earnings timing (pre-market vs after-hours)
dlt-ibapi backfill-options --earnings-date 2025-11-13 \
  --k-expirations 6 --k-strikes 5 \
  --bar-size "5 mins"

# Filter specific symbols when using --earnings-date
dlt-ibapi backfill-options --earnings-date 2025-11-13 \
  --symbols AAPL,MSFT,GOOGL \
  --k-expirations 6 --k-strikes 5 \
  --bar-size "5 mins"
```

### Contract Selection Modes

#### K_AROUND_ATM (Most Common)
Select k strikes on each side of ATM for each expiration.

```python
selection_mode=ContractSelectionMode.K_AROUND_ATM,
k_strikes=3,  # 7 total contracts per expiry (3 below + ATM + 3 above)
```

#### MONEYNESS
Select strikes by moneyness ratio (strike / spot).

```python
selection_mode=ContractSelectionMode.MONEYNESS,
moneyness_levels=[0.90, 0.95, 1.0, 1.05, 1.10],  # 10% OTM to 10% ITM
```

#### DELTA
Select strikes by option delta (Black-Scholes).

```python
selection_mode=ContractSelectionMode.DELTA,
target_deltas=[0.25, 0.50, 0.75],  # 25, 50, 75 delta calls
```

### Gap Detection (Idempotency)

Running the same backfill multiple times is safe:

```python
# First run: Fetches all missing data
info = pipeline.run(data)

# Second run: Finds no gaps, makes ZERO API calls
info = pipeline.run(data)  # Instant, no IB API calls
```

Gap detection:
1. Queries existing data from database
2. Calculates missing business days
3. Only fetches gaps
4. Deduplicates via DLT primary keys

### Querying Backfilled Data

```python
from dlt_ibapi.repositories import EquityBarsReader, OptionBarsReader

# Query equity bars
equity_reader = EquityBarsReader("ib_stocks.duckdb", "stocks")
bars = equity_reader.get_bars(
    symbol="AAPL",
    bar_size="1 day",
    start_date=date(2024, 1, 1),
    end_date=date(2024, 12, 31),
)
print(bars[['time', 'open', 'high', 'low', 'close', 'volume']])

# Query option bars
option_reader = OptionBarsReader("ib_options.duckdb", "options")
contracts = option_reader.get_contracts_for_underlying("AAPL", "1 day")
print(contracts[['expiry', 'strike', 'right', 'bar_count']])
```

### CLI Commands

The CLI has been refactored with enhanced features for production use:

**New Features** (v0.2.0+):
- **Progress bars** - Visual feedback for long operations
- **Logging options** - `--verbose`, `--quiet`, `--log-file`, `--json-logs`
- **Dry-run mode** - `--dry-run` to preview without executing
- **Confirmation prompts** - Prevents accidental large operations
- **Structured errors** - Better error messages with optional tracebacks

```bash
# Equity backfill (with new options)
dlt-ibapi backfill-equity AAPL MSFT GOOGL --bar-size "1 day"
dlt-ibapi backfill-equity AAPL --verbose --log-file backfill.log
dlt-ibapi backfill-equity AAPL MSFT --dry-run  # Preview without executing

# Option snapshot
dlt-ibapi snapshot AAPL --min-dte 7 --max-dte 60
dlt-ibapi snapshot AAPL --verbose  # DEBUG logging

# Option backfill
dlt-ibapi backfill-options AAPL 150.0 --mode atm --k-strikes 3
dlt-ibapi backfill-options AAPL 150.0 --dry-run  # Preview

# List snapshots
dlt-ibapi list-snapshots AAPL

# Database statistics
dlt-ibapi stats ./data --dataset stocks
```

**Common Options** (available on most commands):
- `--verbose, -v` - Enable DEBUG logging
- `--quiet, -q` - Suppress INFO logs (show warnings/errors only)
- `--log-file FILE` - Write logs to file with rotation
- `--json-logs` - Output structured JSON logs
- `--dry-run` - Show what would be done without executing (backfill commands)

### Documentation

For comprehensive documentation:
- **User Guide**: [docs/BACKFILL_GUIDE.md](docs/BACKFILL_GUIDE.md) - Complete backfill workflows
- **API Reference**: [docs/API_REFERENCE.md](docs/API_REFERENCE.md) - Full API documentation
- **Examples**: [examples/](examples/) - Working code samples
- **Notebooks**: [notebooks/](notebooks/) - Interactive Jupyter notebooks

### Orchestration with Dagster

For production deployments with scheduling, monitoring, and automation, use the **Dagster orchestration layer**:

> **📖 See [Architecture Guide](docs/ARCHITECTURE.md) for DLT vs Dagster layer separation**

```bash
cd ../dagster-ib-pipeline
```

### Key Features

- **Native DLT Integration**: Wraps dlt-ibapi sources as Dagster assets
- **Automated Scheduling**: Built-in schedules for ingestion and deduplication
- **Parquet Deduplication**: DuckDB-based dedup on primary keys
- **Asset Lineage**: Visual data flow tracking
- **Local Development UI**: Web interface for monitoring and execution

### Quick Start

```bash
cd ../dagster-ib-pipeline

# Install dependencies (includes dlt-ibapi)
uv sync

# Start Dagster UI
uv run dagster dev -m dagster_ib_pipeline
```

Open http://localhost:3000

### Documentation

- **[dagster-ib-pipeline/README.md](../dagster-ib-pipeline/README.md)** - Overview and features
- **[dagster-ib-pipeline/GETTING_STARTED.md](../dagster-ib-pipeline/GETTING_STARTED.md)** - Installation and usage guide
- **[dagster-ib-pipeline/ORCHESTRATION_STRATEGY.md](../dagster-ib-pipeline/ORCHESTRATION_STRATEGY.md)** - Architecture decisions

### Data Flow

```
IB API → DLT Ingestion (dlt-ibapi) → Raw Parquet
         ↓
         Dagster Schedules (every 15 min)
         ↓
         Deduplication (DuckDB) → Clean Parquet
```

**Benefits**:
- Separation of concerns: dlt-ibapi handles ingestion, Dagster handles orchestration
- Idempotent: Re-runs don't create duplicates
- Schedulable: Automated data collection during market hours
- Monitorable: Track asset materialization and data quality

### Automated Calendar Spread Data Collection

`dlt-ibapi` provides a **fully automated pipeline** for collecting calendar spread backtest data. Perfect for daily cron jobs that handle 300+ earnings symbols with zero manual intervention.

> **📖 See [Automated Calendar Spread Workflow](docs/AUTOMATED_CALENDAR_SPREAD_WORKFLOW.md) for complete documentation**

**What it does (7 automated steps):**
1. Load earnings symbols for specified date
2. Resolve contracts (pre-populate cache)
3. Capture option chain snapshots
4. Backfill equity bars (for spot prices)
5. Select front/back leg expirations based on DTE
6. Backfill option bars (parallel processing)
7. Validate data completeness

**Quick Start:**
```bash
# One-time collection for specific earnings date
python scripts/collect_calendar_spread_data.py 2025-11-13 --workers 5

# Daily automation (add to cron at 6 PM after market close)
./scripts/collect_daily.sh
```

**Features:**
- Parallel processing: 300+ symbols in ~48 minutes (vs 4 hours sequential)
- Automatic spot price extraction from equity bars
- DTE-based expiration selection from snapshots
- Graceful error handling (skip failed symbols, continue)
- Detailed logging and JSON summary output
- Production-ready bash wrapper for cron jobs

### Backtesting

> **📋 Data Requirements**: The backtest requires **daily-collected data** to function:
>
> 1. **Option Chain Snapshots** - Daily metadata (strikes, expirations) collected via `dlt-ibapi snapshot`
> 2. **Option Bars** - OHLCV data for specific contracts collected before expiration
> 3. **Equity Bars** - Underlying spot prices (can be backfilled anytime)
>
> **📖 See [Backtest Quick Start](docs/BACKTEST_QUICKSTART.md) for complete guide** on:
> - Daily data collection workflow
> - Pre-flight validation system
> - Running backtests with auto-filtering of incomplete data
> - Analyzing results and performance metrics

`dlt-ibapi` includes an **options backtesting framework** for earnings calendar spread strategies with built-in data validation and gap-aware execution.

### Features

- **Three Strategy Variants**:
  - `generic_calendar` - Baseline calendar spreads with IV term structure checks
  - `pre_earnings` - Calendar spreads timed around earnings announcements
  - `iv_based` - Most selective strategy with strict IV filtering

- **Complete Execution Engine**:
  - Multi-leg spread execution with atomic fills
  - Greeks tracking (Delta, Gamma, Vega, Theta, Rho, IV)
  - Position monitoring and automated exits
  - Expiration handling
  - Commission tracking ($0.65/contract default)

- **Results Export**:
  - Performance summary (JSON)
  - Equity curve (CSV)
  - Individual trades (CSV)
  - Equity curve plot (PNG)

### Quick Start

```bash
# 1. Verify you have required data
uv run dlt-ibapi stats ./data --dataset stocks
uv run dlt-ibapi stats ./data --dataset options
uv run dlt-ibapi stats ./data --dataset option_chains

# 2. Run backtest
uv run dlt-ibapi backtest-earnings-spreads \
    --strategy iv_based \
    --symbols AAPL MSFT GOOGL \
    --start-date 2023-01-01 \
    --end-date 2024-12-31 \
    --capital 100000

# 3. View results
cat backtest_results/summary_*.json
open backtest_results/equity_curve_*.png
```

### Performance Metrics

- Total Return (%, $)
- Win Rate (%)
- Profit Factor
- Maximum Drawdown (%, $)
- Average Win/Loss
- Number of Trades

### Example Output

```
📈 Backtest Results

┏━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━┓
┃ Metric                ┃ Value            ┃
┡━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━┩
│ Initial Capital       │ $100,000         │
│ Final Value           │ $115,234         │
│ Total Return          │ $15,234.50       │
│ Total Return %        │ 15.23%           │
│ Number of Trades      │ 42               │
│ Win Rate              │ 66.7%            │
│ Profit Factor         │ 2.17             │
│ Max Drawdown %        │ 4.57%            │
└───────────────────────┴──────────────────┘

Exporting results to ./backtest_results...
  ✓ Summary: summary_iv_based_2023-01-01_2024-12-31.json
  ✓ Equity curve: equity_curve_iv_based_2023-01-01_2024-12-31.csv
  ✓ Trades: trades_iv_based_2023-01-01_2024-12-31.csv
  ✓ Equity curve plot: equity_curve_iv_based_2023-01-01_2024-12-31.png
```

### Documentation

- **[docs/BACKTEST_QUICKSTART.md](docs/BACKTEST_QUICKSTART.md)** - Complete guide with data download, verification, and troubleshooting
- **[BACKTEST_IMPLEMENTATION_SUMMARY.md](BACKTEST_IMPLEMENTATION_SUMMARY.md)** - Technical implementation details
- **[BACKTEST_IMPLEMENTATION_PLAN.md](BACKTEST_IMPLEMENTATION_PLAN.md)** - Architecture and design patterns

### Python API

```python
from datetime import date
from tools.strategies.options import IVBasedCalendarSpreadStrategy, IVBasedConfig
from dlt_ibapi.backtest import (
    IBBacktestDataProvider,
    EarningsCalendarProvider,
    OptionsChainProvider,
    OptionsBacktestRunner,
)

# Initialize data providers
data_provider = IBBacktestDataProvider("./data")
earnings_provider = EarningsCalendarProvider("./data/earnings_calendar")
chain_provider = OptionsChainProvider(data_provider.option_chain_reader)

# Configure strategy
config = IVBasedConfig(
    underlying_symbols=["AAPL", "MSFT", "GOOGL"],
    entry_window=(10, 25),
    exit_buffer=2,
    iv_contango_min=0.05,
    profit_target=0.30,
)

strategy = IVBasedCalendarSpreadStrategy(config)

# Run backtest with validation
runner = OptionsBacktestRunner(
    strategy=strategy,
    data_provider=data_provider,
    option_chain_provider=chain_provider,
    initial_capital=100000,
    earnings_calendar_provider=earnings_provider,  # For validation
)
result = runner.run(
    start_date=date(2023, 1, 1),
    end_date=date(2024, 12, 31),
    validate_data=True,  # Pre-flight validation
)

# Analyze results
print(f"Return: {result.total_return_pct:.2f}%")
print(f"Win Rate: {result.winning_trades / result.num_trades * 100:.1f}%")
```

### Architecture

The backtesting framework extends the shared `tools/` backtesting infrastructure with options-specific capabilities:

```
┌─────────────────────────────────────────┐
│ tools/ (Shared Framework)              │
│ - Portfolio manager with options       │
│ - Multi-leg spread executor             │
│ - Greeks models and calculations        │
│ - Strategy base classes                 │
└─────────────────┬───────────────────────┘
                  │
┌─────────────────▼───────────────────────┐
│ dlt-ibapi/ (IB Integration)            │
│ - Data providers (Parquet → tools/)    │
│ - Options backtest runner               │
│ - CLI command                           │
└─────────────────────────────────────────┘
```

**Key Features**:
- ✅ No code duplication (DRY principle)
- ✅ Type-safe with Pydantic models
- ✅ Backward compatible with equity strategies
- ✅ Clean separation of concerns

## Notebooks

Interactive Jupyter notebooks for learning and exploration:

### [01_quickstart.ipynb](notebooks/01_quickstart.ipynb)
- Setting up IB Gateway connection
- Fetching historical equity bars
- Capturing option chain snapshots
- Historical data backfilling with gap detection
- Querying and visualizing data

### [02_reading_data.ipynb](notebooks/02_reading_data.ipynb)
- Understanding Parquet file structure
- Querying with DuckDB SQL
- Using Reader Repositories (Python API)
- Advanced PyArrow queries with predicate pushdown
- Performance comparison and best practices

**Get Started**:
```bash
# Install with notebook dependencies
uv add jupyter matplotlib pandas

# Start Jupyter
jupyter lab

# Open notebooks/01_quickstart.ipynb
```

See [notebooks/README.md](notebooks/README.md) for detailed information.

## Configuration

`dlt-ibapi` supports multiple ways to configure your connection and data requests:

1. **YAML config files** (recommended for projects)
2. **Environment variables** (recommended for secrets/deployment)
3. **Python code** (Pydantic models)
4. **CLI commands** (for quick testing)

### Configuration Hierarchy

Settings are loaded with the following priority (highest to lowest):

1. **Explicitly passed config objects** in Python code
2. **Environment variables** (`IB_HOST`, `IB_PORT`, etc.)
3. **User project config** (`.dlt-ibapi/ib_gateway.yaml` in project root)
4. **Default config** (shipped with package)

---

### Method 1: YAML Configuration (Recommended)

Initialize a config file in your project:

```bash
# Create .dlt-ibapi/ib_gateway.yaml in current directory
dlt-ibapi init

# Or specify a different directory
dlt-ibapi init --dir /path/to/project
```

This creates `.dlt-ibapi/ib_gateway.yaml`:

```yaml
connection:
  host: 127.0.0.1
  port: 4002        # IB Gateway Paper Trading
  client_id: 1
  ready_timeout: 10.0

historical:
  duration: "1 D"
  bar_size: "1 min"
  what_to_show: "TRADES"
  use_rth: true
  timeout: 20.0

market_data:
  generic_ticks: ""
  snapshot: true
  timeout: 10.0

option_chain:
  exchange: ""
  timeout: 10.0
```

**Using YAML config in Python:**

```python
import dlt
from dlt_ibapi import ib_historical_bars

# Config is automatically loaded from .dlt-ibapi/ib_gateway.yaml
data = ib_historical_bars(symbol="AAPL")

pipeline = dlt.pipeline(
    pipeline_name="ib_market_data",
    destination="duckdb",
    dataset_name="stocks",
)

pipeline.run(data)
```

**View your current configuration:**

```bash
dlt-ibapi show-config
```

---

### Method 2: Environment Variables

Set environment variables to override config file settings:

```bash
# Connection settings
export IB_HOST=127.0.0.1
export IB_PORT=4002
export IB_CLIENT_ID=1
export IB_READY_TIMEOUT=10.0

# Historical data settings
export IB_HIST_DURATION="1 W"
export IB_HIST_BAR_SIZE="5 mins"
export IB_HIST_WHAT_TO_SHOW="TRADES"
export IB_HIST_USE_RTH=true
export IB_HIST_TIMEOUT=20.0

# Market data settings
export IB_MARKET_GENERIC_TICKS=""
export IB_MARKET_SNAPSHOT=true
export IB_MARKET_TIMEOUT=10.0

# Option chain settings
export IB_OPTION_EXCHANGE=""
export IB_OPTION_TIMEOUT=10.0
```

**Using environment variables in Python:**

```python
# Environment variables are automatically loaded
from dlt_ibapi import ib_historical_bars

# Will use IB_HOST, IB_PORT, etc. from environment
data = ib_historical_bars(symbol="AAPL")
```

---

### Method 3: Python Configuration (Pydantic Models)

For programmatic control, use Pydantic config models directly:

```python
from dlt_ibapi import ib_historical_bars
from dlt_ibapi.config import IBConnectionConfig, IBHistoricalConfig

# Connection config
conn_config = IBConnectionConfig(
    host="127.0.0.1",
    port=7497,  # TWS Paper Trading
    client_id=1,
    ready_timeout=10.0,
)

# Historical data config
hist_config = IBHistoricalConfig(
    duration="1 W",           # 1 week of data
    bar_size="5 mins",        # 5-minute bars
    what_to_show="TRADES",    # Trade data
    use_rth=True,             # Regular trading hours only
    timeout=30.0,
)

# Pass configs explicitly (overrides YAML and env vars)
data = ib_historical_bars(
    symbol="AAPL",
    connection_config=conn_config,
    hist_config=hist_config,
)
```

**Using the config loader:**

```python
from dlt_ibapi.config_loader import get_connection_config, get_historical_config

# Load from YAML + env vars
conn_config = get_connection_config()
hist_config = get_historical_config()

# Use configs
data = ib_historical_bars(
    symbol="AAPL",
    connection_config=conn_config,
    hist_config=hist_config,
)
```

---

### Method 4: CLI Commands

The CLI provides commands for testing and quick data fetching:

**Test your connection:**

```bash
# Test with config file settings
dlt-ibapi test-connection

# Override connection settings
dlt-ibapi test-connection --host 127.0.0.1 --port 7497 --client-id 2
```

**Fetch data manually:**

```bash
# Fetch historical data for symbols
dlt-ibapi fetch AAPL GOOGL MSFT

# Save to file
dlt-ibapi fetch AAPL --output aapl_data.json

# Fetch contract details
dlt-ibapi fetch AAPL GOOGL --type contract -o contracts.json

# Use custom config file
dlt-ibapi fetch TSLA --config /path/to/custom_config.yaml
```

**View CLI help:**

```bash
dlt-ibapi --help
dlt-ibapi init --help
dlt-ibapi fetch --help
```

## Dataset Organization

`dlt-ibapi` organizes data into four primary datasets, each with a specific purpose:

| Dataset | Purpose | CLI Commands | Location |
|---------|---------|--------------|----------|
| `stocks` | Equity bars (underlying spot prices) | `backfill-equity` | `./data/stocks/` |
| `options` | Option bars (OHLCV for specific contracts) | `backfill-options` | `./data/options/` |
| `option_chains` | Option chain snapshots (contract metadata) | `snapshot`, `list-snapshots` | `./data/option_chains/` |
| `earnings` | Earnings calendar (announcement dates/times) | `load-earnings`, `list-earnings` | `./data/earnings/` |

### Key Concepts

**Dataset vs Pipeline:**
- **Dataset**: Logical grouping of related tables (e.g., all equity data goes into `stocks` dataset)
- **Pipeline**: DLT execution instance with a unique name (e.g., `ib_snapshots`, `my_backfill`)
- **Directory structure**: `./data/{dataset}/{table}/*.parquet`

**Data Separation:**
- **`stocks/`** contains spot prices for underlying equities (for backtesting reference prices)
- **`options/`** contains pricing data (OHLCV) for specific option contracts
- **`option_chains/`** contains metadata about available contracts (strikes, expirations, DTE) - not prices
- **`earnings/`** contains earnings calendar data (announcement dates, times, forecasts) for strategy timing

### Example Workflow

```bash
# 1. Load earnings calendar (from Nasdaq JSON file)
dlt-ibapi load-earnings /path/to/earnings.json --start-date 2025-11-01
# → Saves to ./data/earnings/earnings_calendar/

# 2. Capture option chain snapshot (contract metadata)
dlt-ibapi snapshot AAPL --min-dte 7 --max-dte 60
# → Saves to ./data/option_chains/option_chain_snapshot/

# 3. Backfill option bars (pricing data for contracts)
dlt-ibapi backfill-options AAPL 150.0 --mode atm --k-strikes 3
# → Saves to ./data/options/option_bars/

# 4. Backfill equity bars (underlying spot prices)
dlt-ibapi backfill-equity AAPL --bar-size "1 day"
# → Saves to ./data/stocks/historical_bars/

# 5. View statistics for any dataset
dlt-ibapi stats ./data --dataset stocks
dlt-ibapi stats ./data --dataset options
dlt-ibapi stats ./data --dataset option_chains
dlt-ibapi stats ./data --dataset earnings
```

## Data Quality & Deduplication

`dlt-ibapi` includes **systematic deduplication** to ensure data quality across all datasets:

### Automatic Query-Time Deduplication

All reader methods automatically deduplicate data by primary key:
- **Equity bars**: Deduplicates by `[symbol, bar_size, time]`
- **Option bars**: Deduplicates by `[underlying, expiry, strike, right, bar_size, time]`
- **Option chains**: Deduplicates by `[underlying, as_of, exchange, trading_class]`
- **Earnings calendar**: Deduplicates by `[symbol, earnings_date]`

When duplicates exist, the most recent load is kept (`_dlt_load_id DESC`).

### Validate Data Quality

Check for duplicates across datasets:

```bash
# Validate specific dataset
dlt-ibapi validate --dataset options
dlt-ibapi validate --dataset stocks

# Shows duplicate statistics table:
# - Total rows vs unique rows
# - Duplicate count and percentage
# - Status indicators (✓ clean, ⚠ duplicates found)
```

### Deduplicate Existing Data

Remove duplicates from stored data:

```bash
# Dry-run (preview only, no changes)
dlt-ibapi deduplicate --dataset options --dry-run

# Execute deduplication (creates backup automatically)
dlt-ibapi deduplicate --dataset options

# Deduplicate specific table
dlt-ibapi deduplicate --dataset options --table option_bars_backfill

# Skip backup (faster, less safe)
dlt-ibapi deduplicate --dataset options --no-backup
```

**Features:**
- ✅ Atomic operations (Delta Lake transactions)
- ✅ Automatic backups before changes
- ✅ Preserves partition schemes
- ✅ Detailed statistics and progress reporting
- ✅ Dry-run mode for safety

### Validation Methods (Python API)

```python
from dlt_ibapi.repositories import OptionBarsReader

reader = OptionBarsReader(database_path="./data", dataset_name="options")

# Check for duplicates
if reader.has_duplicates(underlying="AAPL"):
    print("Duplicates detected!")

# Get duplicate statistics
stats = reader.get_duplicate_stats(underlying="AAPL")
print(f"Total: {stats['total_rows']}, Unique: {stats['unique_rows']}")

# Get sample duplicate rows for inspection
duplicates = reader.get_duplicates(limit=10, underlying="AAPL")
print(duplicates)
```

### Why Deduplication Matters

Duplicates can occur when:
- Running the same backfill command multiple times
- Pipeline failures with retries
- Concurrent writes to the same dataset
- Manual data corrections

**Impact without deduplication:**
- ❌ Inflated bar counts and volume metrics
- ❌ Incorrect aggregations (SUM, AVG, COUNT)
- ❌ Misleading backtest results
- ❌ Wasted storage space

**With systematic deduplication:**
- ✅ Queries always return clean data
- ✅ Accurate analytics and aggregations
- ✅ Reliable backtest results
- ✅ Efficient storage usage

### Customizing Dataset Names

All commands accept `--dataset` to override defaults:

```bash
# Use custom dataset names
dlt-ibapi backfill-equity AAPL --dataset my_stocks
dlt-ibapi snapshot AAPL --dataset my_option_chains
dlt-ibapi backfill-options AAPL 150.0 --dataset my_options
```

### Why Separate Datasets?

This separation enables:
1. **Clear data organization**: Spot prices vs option prices vs contract metadata
2. **Efficient queries**: Filter by dataset without scanning unrelated tables
3. **Flexible backtesting**: Load only the data types you need
4. **Modular pipelines**: Run snapshots, equity backfills, and option backfills independently

### File Locations

All data is stored as **Parquet files** in the following structure:

```
./data/
├── stocks/                          # Equity bars dataset
│   ├── historical_bars/             # Table: equity OHLCV data
│   │   └── *.parquet               # Parquet files with timestamps
│   ├── _dlt_loads/                  # DLT metadata (load tracking)
│   │   └── *.jsonl
│   └── _dlt_pipeline_state/         # Pipeline state
│       └── *.jsonl
│
├── options/                         # Option bars dataset
│   ├── option_bars/                 # Table: option OHLCV data
│   │   └── *.parquet
│   └── _dlt_loads/
│       └── *.jsonl
│
├── option_chains/                   # Option chain snapshots dataset
│   ├── option_chain_snapshot/       # Table: main snapshot data
│   │   └── *.parquet
│   ├── option_chain_snapshot__expirations/  # Table: expiration details
│   │   └── *.parquet
│   ├── option_chain_snapshot__strikes/      # Table: strike details
│   │   └── *.parquet
│   └── _dlt_loads/
│       └── *.jsonl
│
└── earnings/                        # Earnings calendar dataset
    ├── earnings_calendar/           # Table: earnings announcements
    │   └── *.parquet
    └── _dlt_loads/
        └── *.jsonl
```

**With Hive Partitioning (Optional):**

You can enable Hive-style partitioning for better query performance on large datasets:

```
./data/stocks/historical_bars/
├── date=2025-01-15/                 # Hive partition by date
│   ├── symbol=AAPL/                 # Nested partition by symbol
│   │   └── *.parquet
│   └── symbol=MSFT/
│       └── *.parquet
└── date=2025-01-16/
    └── ...
```

**Key Points:**
- **Parquet format**: Compressed columnar format (~10x smaller than CSV)
- **Schema evolution**: DLT handles schema changes automatically
- **DLT metadata**: `_dlt_loads` tracks pipeline runs and data lineage
- **File naming**: Timestamps in filenames (e.g., `1761044219.827749.eb57dba027.parquet`)
- **Hive partitioning**: Enable via DLT column hints for large datasets (see API docs)

### Data Discovery

Explore your data using CLI commands:

#### 1. **View Dataset Statistics**

```bash
# See all tables in a dataset with row counts, date ranges, and symbols
dlt-ibapi stats ./data --dataset stocks

# Output:
# historical_bars
#   Rows: 456
#   Date range: 2025-09-09 to 2025-10-21
#   Symbols: AAPL, GOOGL, MSFT
#   Columns: 16
```

```bash
# Analyze specific table
dlt-ibapi stats ./data --dataset option_chains --table option_chain_snapshot

# Check all datasets
dlt-ibapi stats ./data --dataset stocks
dlt-ibapi stats ./data --dataset options
dlt-ibapi stats ./data --dataset option_chains
dlt-ibapi stats ./data --dataset earnings
```

#### 2. **List Available Snapshots**

```bash
# List all option chain snapshots
dlt-ibapi list-snapshots

# List snapshots for specific symbol
dlt-ibapi list-snapshots AAPL

# Use custom dataset location
dlt-ibapi list-snapshots --data-dir ./data --dataset option_chains
```

#### 3. **List Upcoming Earnings**

```bash
# List earnings for next 7 days
dlt-ibapi list-earnings

# List earnings for next 30 days
dlt-ibapi list-earnings --days-ahead 30

# Filter by symbols
dlt-ibapi list-earnings --symbols AAPL MSFT GOOGL

# Filter by earnings time
dlt-ibapi list-earnings --time PRE_MARKET
dlt-ibapi list-earnings --time AFTER_HOURS

# Use custom dataset location
dlt-ibapi list-earnings --data-dir ./data --dataset earnings
```

#### 4. **Query Data with DuckDB**

Use DuckDB to explore Parquet files directly:

```bash
# Interactive DuckDB shell
duckdb

# Query equity bars
SELECT symbol, date, close, volume
FROM parquet_scan('./data/stocks/historical_bars/**/*.parquet', hive_partitioning=true)
WHERE symbol = 'AAPL'
  AND date >= '2025-01-01'
ORDER BY date DESC
LIMIT 10;

# Aggregate statistics
SELECT
    symbol,
    COUNT(*) as bar_count,
    MIN(date) as first_date,
    MAX(date) as last_date,
    AVG(volume) as avg_volume
FROM parquet_scan('./data/stocks/historical_bars/**/*.parquet', hive_partitioning=true)
GROUP BY symbol
ORDER BY symbol;

# Query option chain snapshots
SELECT
    underlying,
    as_of,
    COUNT(*) as total_contracts
FROM parquet_scan('./data/option_chains/option_chain_snapshot/**/*.parquet', hive_partitioning=true)
GROUP BY underlying, as_of
ORDER BY as_of DESC;

# Query earnings calendar
SELECT
    symbol,
    earnings_date,
    earnings_time,
    company_name,
    eps_forecast
FROM parquet_scan('./data/earnings/earnings_calendar/**/*.parquet', hive_partitioning=true)
WHERE earnings_date >= CURRENT_DATE
  AND earnings_date <= CURRENT_DATE + INTERVAL '30 days'
ORDER BY earnings_date, symbol;

# Count earnings by time of day
SELECT
    earnings_time,
    COUNT(*) as count
FROM parquet_scan('./data/earnings/earnings_calendar/**/*.parquet', hive_partitioning=true)
WHERE earnings_date >= CURRENT_DATE
GROUP BY earnings_time
ORDER BY count DESC;
```

#### 5. **Query Data with Python**

Use the built-in Reader API for type-safe queries:

```python
from dlt_ibapi.repositories import EquityBarsReader
from datetime import date

# Initialize reader
reader = EquityBarsReader(database_path="./data", dataset_name="stocks")

# Get bars for a symbol
df = reader.get_bars(
    symbol="AAPL",
    bar_size="1 day",
    start_date=date(2025, 1, 1),
    end_date=date(2025, 10, 20)
)
print(df.head())

# Get available symbols
symbols = reader.get_available_symbols(bar_size="1 day")
print(f"Available symbols: {symbols}")

# Get date range for a symbol
min_date, max_date = reader.get_date_range("AAPL", "1 day")
print(f"AAPL data from {min_date} to {max_date}")
```

```python
from dlt_ibapi.repositories import OptionChainSnapshotReader
from datetime import date

# Query option chain snapshots
reader = OptionChainSnapshotReader(database_path="./data", dataset_name="option_chains")

# Get chain for specific date
chain = reader.get_chain_for_date(
    underlying="AAPL",
    as_of_date=date(2025, 11, 13),
    min_dte=7,
    max_dte=60
)
print(chain)

# List available snapshots
snapshots = reader.get_available_snapshots("AAPL")
print(f"AAPL snapshots: {snapshots}")
```

```python
from dlt_ibapi.repositories import EarningsCalendarReader
from datetime import date

# Query earnings calendar
reader = EarningsCalendarReader(database_path="./data", dataset_name="earnings")

# Get upcoming earnings
upcoming = reader.get_upcoming_earnings(
    days_ahead=30,
    symbols=["AAPL", "MSFT", "GOOGL"]
)
print(upcoming[['symbol', 'earnings_date', 'earnings_time', 'company_name']])

# Get all earnings for a symbol
aapl_earnings = reader.get_earnings_for_symbol(
    symbol="AAPL",
    start_date=date(2025, 1, 1),
    end_date=date(2025, 12, 31)
)
print(f"AAPL has {len(aapl_earnings)} earnings in 2025")

# Check if specific date has earnings
earnings_today = reader.get_earnings_on_date(date.today())
print(f"{len(earnings_today)} companies reporting earnings today")

# Get available symbols
symbols = reader.get_available_symbols()
print(f"Earnings data for {len(symbols)} symbols")
```

#### 6. **Explore File System**

```bash
# List all datasets
ls -la ./data/

# See Hive partitions for equity bars
find ./data/stocks/historical_bars -type d | head -20

# Count Parquet files
find ./data -name "*.parquet" | wc -l

# Check file sizes by dataset
du -sh ./data/stocks ./data/options ./data/option_chains

# View DLT metadata (load history)
cat ./data/stocks/_dlt_loads/*.jsonl | jq '.'
```

**Pro Tips:**
- Use `hive_partitioning=true` in DuckDB queries for partition pruning
- Reader API handles Hive partitioning automatically
- Stats command is the fastest way to see what data exists
- Parquet files are compressed (~10x smaller than CSV)

## API Reference

> **📖 See [API Reference](docs/API_REFERENCE.md) for complete Python API documentation**

### Resources (Quick Reference)

#### `ib_historical_bars`
Fetches OHLCV bar data for a single symbol.

```python
@dlt.resource(name="historical_bars")
def ib_historical_bars(
    symbol: str,
    exchange: str = "SMART",
    currency: str = "USD",
    sec_type: str = "STK",
    end_date: Optional[str] = None,
    connection_config: Optional[IBConnectionConfig] = None,
    hist_config: Optional[IBHistoricalConfig] = None,
) -> Iterator[dict]
```

**Parameters:**
- `symbol` (str): Stock symbol (e.g., "AAPL", "GOOGL")
- `exchange` (str): Exchange routing (default: "SMART")
- `currency` (str): Currency code (default: "USD")
- `sec_type` (str): Security type (default: "STK" for stocks)
- `end_date` (str, optional): End date for historical data (format: "YYYYMMDD HH:mm:ss" or empty for now)
- `connection_config` (IBConnectionConfig, optional): IB connection settings
- `hist_config` (IBHistoricalConfig, optional): Historical data request settings

**Returns:** Iterator yielding normalized bar records (see Data Schema below)

**Example:**
```python
data = ib_historical_bars(
    symbol="TSLA",
    exchange="SMART",
    currency="USD",
    end_date="20250115 16:00:00",
)
```

---

#### `ib_contract_details`
Fetches detailed contract specifications for multiple symbols.

```python
@dlt.resource(name="contract_details")
def ib_contract_details(
    symbols: List[str],
    exchange: str = "SMART",
    currency: str = "USD",
    sec_type: str = "STK",
    connection_config: Optional[IBConnectionConfig] = None,
) -> Iterator[dict]
```

**Parameters:**
- `symbols` (List[str]): List of symbols to fetch
- `exchange` (str): Exchange (default: "SMART")
- `currency` (str): Currency (default: "USD")
- `sec_type` (str): Security type (default: "STK")
- `connection_config` (IBConnectionConfig, optional): IB connection settings

**Returns:** Iterator yielding contract detail records

**Example:**
```python
contracts = ib_contract_details(
    symbols=["AAPL", "MSFT", "GOOGL"],
    exchange="SMART",
    currency="USD",
)
```

---

#### `ib_option_chain`
Fetches option chain parameters including strikes and expirations.

```python
@dlt.resource(name="option_chain")
def ib_option_chain(
    symbol: str,
    conid: int,
    sec_type: str = "STK",
    exchange: str = "",
    connection_config: Optional[IBConnectionConfig] = None,
    option_config: Optional[IBOptionChainConfig] = None,
) -> Iterator[dict]
```

**Parameters:**
- `symbol` (str): Underlying symbol
- `conid` (int): Contract ID of underlying asset (get from contract_details)
- `sec_type` (str): Security type (default: "STK")
- `exchange` (str): Exchange (default: "")
- `connection_config` (IBConnectionConfig, optional): IB connection settings
- `option_config` (IBOptionChainConfig, optional): Option chain request settings

**Returns:** Iterator yielding option parameter records

**Example:**
```python
options = ib_option_chain(
    symbol="AAPL",
    conid=265598,
    exchange="SMART",
)
```

---

#### `ib_market_data_snapshot`
Fetches market data snapshots for multiple symbols.

```python
@dlt.resource(name="market_data_snapshot")
def ib_market_data_snapshot(
    symbols: List[str],
    exchange: str = "SMART",
    currency: str = "USD",
    connection_config: Optional[IBConnectionConfig] = None,
    market_config: Optional[IBMarketDataConfig] = None,
) -> Iterator[dict]
```

**Parameters:**
- `symbols` (List[str]): List of stock symbols
- `exchange` (str): Exchange (default: "SMART")
- `currency` (str): Currency (default: "USD")
- `connection_config` (IBConnectionConfig, optional): IB connection settings
- `market_config` (IBMarketDataConfig, optional): Market data request settings

**Returns:** Iterator yielding snapshot records

**Example:**
```python
snapshots = ib_market_data_snapshot(
    symbols=["SPY", "QQQ", "DIA"],
    exchange="SMART",
)
```

---

### Sources

#### `ib_source`
Combined DLT source that orchestrates multiple resources.

```python
@dlt.source(name="ib_source")
def ib_source(
    symbols: List[str],
    include_historical: bool = True,
    include_contract_details: bool = True,
    include_option_chain: bool = False,
    connection_config: Optional[IBConnectionConfig] = None,
) -> List[Any]
```

**Parameters:**
- `symbols` (List[str]): List of symbols to fetch
- `include_historical` (bool): Include historical bars (default: True)
- `include_contract_details` (bool): Include contract details (default: True)
- `include_option_chain` (bool): Include option chain data (default: False)
- `connection_config` (IBConnectionConfig, optional): IB connection settings

**Returns:** List of DLT resources to be loaded

**Example:**
```python
source = ib_source(
    symbols=["AAPL", "GOOGL"],
    include_historical=True,
    include_contract_details=True,
)
pipeline.run(source)
```

---

### Configuration Classes

#### `IBConnectionConfig`
Configuration for IB Gateway/TWS connection.

```python
class IBConnectionConfig(BaseModel):
    host: str = "127.0.0.1"           # IB Gateway/TWS host
    port: int = 7497                  # IB Gateway/TWS port
    client_id: int = 1                # Client ID for connection
    ready_timeout: float = 10.0       # Timeout for connection ready (seconds)
```

**Common Port Numbers:**
- `7497`: TWS Paper Trading
- `7496`: TWS Live Trading
- `4002`: IB Gateway Paper Trading
- `4001`: IB Gateway Live Trading

---

#### `IBHistoricalConfig`
Configuration for historical data requests.

```python
class IBHistoricalConfig(BaseModel):
    duration: str = "1 D"              # Duration string
    bar_size: str = "1 min"            # Bar size
    what_to_show: str = "TRADES"       # Data type
    use_rth: bool = True               # Regular trading hours only
    timeout: float = 20.0              # Request timeout (seconds)
```

**Duration Options:** "1 D", "1 W", "1 M", "1 Y", etc.
**Bar Size Options:** "1 secs", "5 secs", "10 secs", "15 secs", "30 secs", "1 min", "2 mins", "3 mins", "5 mins", "10 mins", "15 mins", "20 mins", "30 mins", "1 hour", "2 hours", "3 hours", "4 hours", "8 hours", "1 day", "1 week", "1 month"
**What to Show Options:** "TRADES", "MIDPOINT", "BID", "ASK", "BID_ASK", "HISTORICAL_VOLATILITY", "OPTION_IMPLIED_VOLATILITY"

---

#### `IBMarketDataConfig`
Configuration for market data snapshots.

```python
class IBMarketDataConfig(BaseModel):
    generic_ticks: str = ""            # Generic tick types
    snapshot: bool = True              # Request snapshot only
    timeout: float = 10.0              # Request timeout (seconds)
```

---

#### `IBOptionChainConfig`
Configuration for option chain requests.

```python
class IBOptionChainConfig(BaseModel):
    exchange: str = ""                 # Exchange for option params
    timeout: float = 10.0              # Request timeout (seconds)
```

## Data Schema

All data is normalized and cleaned by transformer functions before loading. Timestamps are in ISO format, and all numeric fields are properly typed.

### Historical Bars
Output schema from `ib_historical_bars()`:

```python
{
    "symbol": str,              # Stock symbol (e.g., "AAPL")
    "exchange": str,            # Exchange (e.g., "SMART")
    "currency": str,            # Currency code (e.g., "USD")
    "timestamp": str,           # ISO format timestamp
    "open": float,              # Opening price
    "high": float,              # High price
    "low": float,               # Low price
    "close": float,             # Closing price
    "volume": int,              # Volume traded
    "wap": float | None,        # Weighted average price (optional)
    "bar_count": int | None,    # Number of trades in bar (optional)
}
```

**Example Record:**
```python
{
    "symbol": "AAPL",
    "exchange": "SMART",
    "currency": "USD",
    "timestamp": "2025-01-15 09:30:00",
    "open": 185.50,
    "high": 186.20,
    "low": 185.30,
    "close": 186.00,
    "volume": 1250000,
    "wap": 185.85,
    "bar_count": 3420
}
```

---

### Contract Details
Output schema from `ib_contract_details()`:

```python
{
    "symbol": str,              # Stock symbol
    "contract_id": int,         # IB contract ID (conId)
    "local_symbol": str,        # Local trading symbol
    "trading_class": str,       # Trading class
    "sec_type": str,            # Security type (e.g., "STK")
    "exchange": str,            # Exchange
    "primary_exchange": str,    # Primary exchange
    "currency": str,            # Currency
    "long_name": str,           # Full company name
    "category": str,            # Industry category
    "subcategory": str,         # Industry subcategory
    "industry": str | None,     # Industry (optional)
    "min_tick": float,          # Minimum price tick
    "price_magnifier": int,     # Price magnifier
    "order_types": str,         # Allowed order types (comma-separated)
    "valid_exchanges": str,     # Valid exchanges (comma-separated)
    "market_name": str,         # Market name
    "fetched_at": str,          # ISO format timestamp when fetched
}
```

**Example Record:**
```python
{
    "symbol": "AAPL",
    "contract_id": 265598,
    "local_symbol": "AAPL",
    "trading_class": "NMS",
    "sec_type": "STK",
    "exchange": "SMART",
    "primary_exchange": "NASDAQ",
    "currency": "USD",
    "long_name": "APPLE INC",
    "category": "Technology",
    "subcategory": "Computers",
    "industry": "Computer Hardware",
    "min_tick": 0.01,
    "price_magnifier": 1,
    "order_types": "ACTIVETIM,AD,ADJUST...",
    "valid_exchanges": "SMART,AMEX,NYSE...",
    "market_name": "NMS",
    "fetched_at": "2025-01-15T14:30:00.123456"
}
```

---

### Option Chain Parameters
Output schema from `ib_option_chain()`:

```python
{
    "underlying_symbol": str,   # Underlying stock symbol
    "underlying_conid": int,    # Underlying contract ID
    "exchange": str,            # Exchange
    "trading_class": str,       # Trading class
    "multiplier": str,          # Contract multiplier
    "expirations": List[str],   # List of expiration dates
    "strikes": List[float],     # List of strike prices
    "expiration_count": int,    # Number of expirations
    "strike_count": int,        # Number of strikes
    "fetched_at": str,          # ISO format timestamp when fetched
}
```

**Example Record:**
```python
{
    "underlying_symbol": "AAPL",
    "underlying_conid": 265598,
    "exchange": "SMART",
    "trading_class": "AAPL",
    "multiplier": "100",
    "expirations": ["20250117", "20250124", "20250131"],
    "strikes": [170.0, 175.0, 180.0, 185.0, 190.0],
    "expiration_count": 3,
    "strike_count": 5,
    "fetched_at": "2025-01-15T14:30:00.123456"
}
```

---

### Market Data Snapshot
Output schema from `ib_market_data_snapshot()`:

```python
{
    "symbol": str,              # Stock symbol
    "exchange": str,            # Exchange
    "currency": str,            # Currency
    "contract_id": int,         # Contract ID
    "local_symbol": str,        # Local symbol
    "long_name": str,           # Company name
    "timestamp": str,           # ISO format timestamp
}
```

**Example Record:**
```python
{
    "symbol": "AAPL",
    "exchange": "SMART",
    "currency": "USD",
    "contract_id": 265598,
    "local_symbol": "AAPL",
    "long_name": "APPLE INC",
    "timestamp": "2025-01-15T14:30:00.123456"
}
```

## Working with Loaded Data

Once data is loaded, you can query it using the **Reader API**, SQL, or pandas.

### Method 1: Reader API (Recommended)

The `dlt_ibapi.read` module provides a convenient Python API for querying Parquet data:

```python
from dlt_ibapi.read import EquityBarsReader
from datetime import date, timedelta

# Initialize reader
reader = EquityBarsReader(
    database_path="./data",
    dataset_name="stocks"
)

# Get available symbols
symbols = reader.get_available_symbols(bar_size="1 day")
print(f"Available symbols: {symbols}")

# Get bars for a symbol
bars = reader.get_bars(
    symbol="AAPL",
    bar_size="1 day",
    start_date=date.today() - timedelta(days=30),
    end_date=date.today()
)
print(bars)

# Get date range for a symbol
min_date, max_date = reader.get_date_range("AAPL", "1 day")
print(f"Data range: {min_date} to {max_date}")

# Get summary for all symbols
summary = reader.get_symbols_summary(bar_size="1 day")
print(summary)
```

**Available Readers:**
- `EquityBarsReader` - Query historical equity bars
- `OptionBarsReader` - Query option bars
- `OptionChainSnapshotReader` - Query option chain snapshots

See `notebooks/02_reading_data.ipynb` for detailed examples.

### Method 2: Query with DuckDB

For SQL queries and aggregations, use DuckDB directly:

```python
import duckdb

# Connect to DuckDB in-memory
conn = duckdb.connect(":memory:")

# Query Parquet files with Hive partitioning
result = conn.execute("""
    SELECT
        symbol,
        time::DATE as date,
        close,
        volume
    FROM parquet_scan('./data/stocks/**/*.parquet', hive_partitioning=true)
    WHERE symbol = 'AAPL'
      AND date >= CURRENT_DATE - INTERVAL '10 days'
    ORDER BY time DESC
""").df()

print(result)
```

### Method 3: Query with Pandas

Load data into pandas DataFrame for analysis:

```python
import duckdb
import pandas as pd

# Query into pandas
conn = duckdb.connect(":memory:")
df = conn.execute("""
    SELECT *
    FROM parquet_scan('./data/stocks/**/*.parquet', hive_partitioning=true)
    WHERE symbol = 'AAPL'
""").df()

# Analyze with pandas
print(df.describe())
print(df.groupby('symbol')['volume'].mean())
```

### Incremental Loading

For ongoing data collection, use DLT's incremental loading:

```python
import dlt
from dlt_ibapi import ib_historical_bars

# Use write_disposition for incremental loading
data = ib_historical_bars(
    symbol="AAPL",
    exchange="SMART",
)

pipeline = dlt.pipeline(
    pipeline_name="ib_incremental",
    destination="duckdb",
    dataset_name="stocks",
)

# Append new data without duplicates
info = pipeline.run(data, write_disposition="append")
```

---

## Data Transformation

The connector uses transformer functions in `src/dlt_ibapi/transformers.py` to normalize IB API data:

### Available Transformers

#### `normalize_bar_data()`
Transforms raw bar data from IB API into clean OHLCV records with consistent types and timestamps.

**Location:** `src/dlt_ibapi/transformers.py:7`

#### `normalize_contract_details()`
Extracts contract information from IB ContractDetails objects into flat, queryable dictionaries.

**Location:** `src/dlt_ibapi/transformers.py:35`

#### `normalize_option_params()`
Structures option chain data including strikes, expirations, and multipliers.

**Location:** `src/dlt_ibapi/transformers.py:70`

#### `normalize_tick_data()`
Handles various tick types (price, size, string, option) and structures them appropriately.

**Location:** `src/dlt_ibapi/transformers.py:96`

All transformers ensure:
- Consistent data types (floats, ints, strings)
- ISO format timestamps
- Null handling for optional fields
- Flat structure for easy querying

---

## Architecture

> **📖 See [Architecture Guide](docs/ARCHITECTURE.md) for DLT vs Dagster layer separation**
> **📖 See [CLI Architecture](docs/CLI_ARCHITECTURE.md) for CLI design patterns**

```
dlt-ibapi (DLT connector)
    ↓ depends on
ib-connector (IB Gateway/TWS wrapper)
    ↓ depends on
ibapi (Official IB API)
```

### Component Layers

1. **DLT Resources** (`sources.py`): DLT-decorated functions that yield data
2. **Transformers** (`transformers.py`): Normalize raw IB data to clean schemas
3. **Configuration** (`config.py`): Pydantic models for type-safe config
4. **IB Connector**: Handles IB Gateway/TWS communication
5. **Official IB API**: Low-level Interactive Brokers API

### Design Principles

1. **Separation of Concerns**: `ib-connector` handles IB API, `dlt-ibapi` handles DLT integration
2. **Stateless**: Resources are stateless and can be composed
3. **Modular**: Use only what you need
4. **Type-Safe**: Pydantic models for configuration
5. **Testable**: Each layer can be tested independently
6. **Data Normalization**: All data is cleaned and typed before loading

## CLI Reference

The `dlt-ibapi` command-line interface provides utilities for configuration, testing, and data fetching.

### Available Commands

```bash
# Configuration
dlt-ibapi init              # Initialize config file
dlt-ibapi show-config       # Display current configuration
dlt-ibapi test-connection   # Test IB Gateway/TWS connection

# Data Operations
dlt-ibapi backfill-equity   # Backfill equity bars with gap detection
dlt-ibapi backfill-options  # Backfill option bars with gap detection
dlt-ibapi snapshot          # Capture option chain snapshot
dlt-ibapi list-snapshots    # List available snapshots

# Utilities
dlt-ibapi stats             # Database/Parquet statistics
dlt-ibapi fetch             # Manual data fetching
dlt-ibapi version           # Show version
```

### Enhanced CLI Features (v0.2.0+)

All major commands now support:

**Logging Options** (see [Logging Guide](docs/LOGGING_GUIDE.md) for details):
```bash
--verbose, -v          # Enable DEBUG logging
--quiet, -q            # Suppress INFO logs (warnings/errors only)
--log-file FILE        # Write logs to file with rotation (10MB max, 5 backups)
--json-logs            # Output structured JSON logs (for monitoring/aggregation)
```

**Operational Safety**:
```bash
--dry-run              # Preview without executing (backfill commands)
```

**Example**:
```bash
# Verbose logging with file output
dlt-ibapi backfill-equity AAPL --verbose --log-file backfill.log

# Quiet mode (warnings/errors only)
dlt-ibapi backfill-equity AAPL MSFT GOOGL --quiet

# Preview what would happen
dlt-ibapi backfill-equity AAPL MSFT --dry-run

# JSON structured logs
dlt-ibapi backfill-options AAPL 150.0 --json-logs
```

### Command Details

#### `init` - Initialize Configuration

Creates `.dlt-ibapi/ib_gateway.yaml` in your project:

```bash
# Create config in current directory
dlt-ibapi init

# Create in specific directory
dlt-ibapi init --dir /path/to/project

# Overwrite existing config
dlt-ibapi init --force
```

#### `show-config` - Display Configuration

Shows merged configuration from all sources (defaults, user config, env vars):

```bash
# Show config from auto-detected user config
dlt-ibapi show-config

# Show config from specific file
dlt-ibapi show-config --config /path/to/config.yaml
```

Output example:
```
Configuration Sources:
  Default: /path/to/package/config_files/ib_gateway.yaml
  User:    /path/to/project/.dlt-ibapi/ib_gateway.yaml ✓
  Env:     IB_HOST, IB_PORT, etc.

Connection Settings
┏━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━┓
┃ Setting       ┃ Value       ┃
┡━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━┩
│ Host          │ 127.0.0.1   │
│ Port          │ 4002        │
│ Client ID     │ 1           │
│ Ready Timeout │ 10.0s       │
└───────────────┴─────────────┘
```

#### `test-connection` - Test IB Connection

Verifies connection to IB Gateway/TWS:

```bash
# Test with config file settings
dlt-ibapi test-connection

# Override settings
dlt-ibapi test-connection --host 127.0.0.1 --port 7497 --client-id 2

# Use custom config file
dlt-ibapi test-connection --config /path/to/config.yaml
```

#### `fetch` - Fetch Data

Fetch market data and optionally save to JSON:

```bash
# Fetch historical bars for symbols
dlt-ibapi fetch AAPL GOOGL MSFT

# Save to file
dlt-ibapi fetch AAPL --output aapl_bars.json

# Fetch contract details
dlt-ibapi fetch AAPL GOOGL --type contract --output contracts.json

# Use custom config
dlt-ibapi fetch TSLA --config /path/to/config.yaml --output tsla.json
```

**Options:**
- `--output, -o`: Output file path (JSON format)
- `--type, -t`: Data type (`historical` or `contract`)
- `--config, -c`: Path to config file

---

## Development

```bash
# Install dev dependencies
uv sync --dev

# Run tests
uv run pytest

# Run specific test file
uv run pytest tests/unit/test_gap_detection.py

# Run with coverage
uv run pytest --cov=src/dlt_ibapi --cov-report=html

# Format code
uv run ruff format .

# Lint
uv run ruff check .

# Auto-fix linting issues
uv run ruff check --fix .
```

### CLI Development

The CLI uses a modular architecture for maintainability and testability:

**Business Logic** (testable without CLI framework):
```python
from dlt_ibapi.cli import BackfillEquityParams, execute_backfill_equity

params = BackfillEquityParams(
    symbols=["AAPL"],
    start_date=date(2025, 1, 1),
    end_date=date(2025, 1, 31),
    bar_size="1 day",
    pipeline_name="test",
)

result = execute_backfill_equity(params)
assert result.success
```

**Testing Pattern**:
```python
def test_backfill_equity_validation():
    """Test Pydantic catches invalid params."""
    with pytest.raises(ValueError):
        BackfillEquityParams(
            symbols=["AAPL"],
            start_date=date(2025, 1, 31),
            end_date=date(2025, 1, 1),  # Invalid: before start
            bar_size="1 day",
            pipeline_name="test",
        )

def test_backfill_equity_with_mock():
    """Test business logic with mocked dependencies."""
    params = BackfillEquityParams(...)
    mock_pipeline = Mock()
    result = execute_backfill_equity(
        params,
        pipeline_factory=lambda _: mock_pipeline
    )
    assert result.success
```

## Project Structure

```
src/dlt_ibapi/
├── cli/                        # CLI business logic (NEW v0.2.0)
│   ├── __init__.py            # Public API
│   ├── models.py              # Pydantic models (params + results)
│   ├── backfill.py            # Backfill business logic
│   ├── snapshot.py            # Snapshot business logic
│   └── stats.py               # Stats business logic
├── utils/                      # Utilities (NEW v0.2.0)
│   ├── __init__.py
│   └── logging.py             # Structured logging
├── backfill/                   # Backfill infrastructure
│   ├── resources.py           # DLT resources with gap detection
│   ├── gap_detection.py       # Gap calculation logic
│   ├── contract_selection.py  # Option contract selection
│   └── market_calendar.py     # Business day calculations
├── repositories/               # Read API (Parquet queries)
│   ├── base.py                # Base reader classes
│   ├── parquet_reader.py      # ParquetReaderBase
│   ├── equity_bars.py         # EquityBarsReader
│   ├── option_bars.py         # OptionBarsReader
│   └── option_chain.py        # OptionChainSnapshotReader
├── sources.py                  # Basic DLT resources
├── transformers.py             # Data normalization
├── config.py                   # Pydantic config models
├── config_loader.py            # Config hierarchy loader
└── cli.py                      # CLI commands (presentation)
```

## Examples

See the `examples/` directory for complete usage examples:

- **`basic_pipeline.py`** - Simple historical data pipeline using config loader
- **`multi_symbol.py`** - Multiple symbols with DuckDB, demonstrates `ib_source`
- **`contract_details.py`** - Fetch contract specifications and query results
- **`config_example.py`** - All configuration methods (YAML, env vars, code)

Each example includes:
- Configuration loading from YAML/env vars
- Setup instructions
- Both explicit and auto-load config patterns

**Before running examples:**

```bash
# 1. Initialize config in examples directory
cd examples
dlt-ibapi init

# 2. Edit config to match your IB Gateway setup
vim .dlt-ibapi/ib_gateway.yaml

# 3. Test connection
dlt-ibapi test-connection

# 4. Run an example
uv run python basic_pipeline.py
```

## Troubleshooting

### Connection Errors
- Ensure IB Gateway/TWS is running
- Check port number (7497 for paper, 4002 for IB Gateway paper)
- Verify API connections are enabled in TWS settings
- Check client_id is not already in use

### Timeout Errors
- Increase `ready_timeout` in connection config
- Increase resource-specific timeouts
- Check network connectivity to IB Gateway

### No Data Returned
- Verify symbol exists and is correct
- Check exchange and currency parameters
- Ensure market is open or use historical data during market hours
- Check IB account permissions for data

## License

MIT

## Related Projects

- [ib-connector](../ib-connector) - Standalone IB Gateway/TWS connector
- [dlt](https://dlthub.com/) - Data load tool
- [ibapi](https://interactivebrokers.github.io/) - Official IB API
