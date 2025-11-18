# dlt-ibapi

**Production-ready market data pipeline for Interactive Brokers** built on [dlt](https://dlthub.com/) (Data Load Tool).

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

A modern data engineering solution for ingesting Interactive Brokers market data into Parquet files with gap-aware backfilling, deduplication, and efficient storage.

## ✨ Key Features

- **📊 Parquet-First Storage** - 10x compression with Hive partitioning for cloud-ready storage
- **🔄 Gap-Aware Backfilling** - Idempotent data loading with business day calendar awareness
- **✅ Automatic Deduplication** - Query-time and post-load deduplication built-in
- **🎯 Contract Resolution** - Smart caching system for IB contract lookups
- **🔌 Modular CLI** - Clean separation of presentation, business logic, and data layers
- **📈 Earnings Calendar** - Load and query earnings announcement data
- **🧪 Comprehensive Testing** - Unit and integration test suites

## 📋 Table of Contents

- [Installation](#installation)
- [Quick Start](#quick-start)
- [Documentation](#documentation)
- [Architecture](#architecture)
- [CLI Commands](#cli-commands)
- [Python API](#python-api)
- [Data Organization](#data-organization)
- [Development](#development)
- [Troubleshooting](#troubleshooting)

## 🚀 Installation

### Prerequisites

- Python 3.10+
- IB Gateway or TWS running and configured
- API connections enabled in IB settings

### Install

```bash
# Clone repository
git clone https://github.com/yourusername/dlt-ibapi.git
cd dlt-ibapi

# Install dependencies (uses uv for fast dependency resolution)
uv sync

# Verify installation
uv run dlt-ibapi version
```

## ⚡ Quick Start

### 1. Initialize Configuration

```bash
# Create default configuration file
uv run dlt-ibapi init

# Test IB Gateway connection
uv run dlt-ibapi test-connection
```

### 2. Backfill Historical Data

```bash
# Backfill equity bars (daily OHLCV data)
uv run dlt-ibapi backfill-equity AAPL --bar-size "1 day"

# Backfill option bars for ATM strikes
uv run dlt-ibapi backfill-options AAPL 180.0 --mode atm --k-strikes 3

# Snapshot option chain
uv run dlt-ibapi snapshot AAPL --min-dte 7 --max-dte 60
```

### 3. Query Data with Python

```python
from dlt_ibapi.repositories import EquityBarsReader
from datetime import date

# Initialize reader
reader = EquityBarsReader(database_path="./data", dataset_name="stocks")

# Query bars
bars_df = reader.get_bars(
    symbol="AAPL",
    bar_size="1 day",
    start_date=date(2025, 1, 1),
    end_date=date(2025, 10, 20),
)

print(f"Loaded {len(bars_df)} bars")
print(bars_df.head())
```

## 📚 Documentation

### Getting Started
- **[Backfill Guide](docs/BACKFILL_GUIDE.md)** - Complete guide to historical data backfilling with gap detection
- **[Earnings Guide](docs/EARNINGS_GUIDE.md)** - Load and query earnings calendar data
- **[Earnings Snapshot Workflow](docs/EARNINGS_SNAPSHOT_WORKFLOW.md)** - Batch snapshot option chains for stocks with earnings

### Technical Documentation
- **[API Reference](docs/API_REFERENCE.md)** - Complete Python API documentation
- **[Architecture](docs/ARCHITECTURE.md)** - System architecture and design patterns
- **[CLI Architecture](docs/CLI_ARCHITECTURE.md)** - CLI refactoring and modular design
- **[Parquet Migration](docs/PARQUET_MIGRATION.md)** - Parquet-first storage architecture
- **[Logging Guide](docs/LOGGING_GUIDE.md)** - Structured logging with structlog

### Maintenance
- **[Data Quality Guide](docs/DATA_QUALITY.md)** - Deduplication and validation strategies

## 🏗️ Architecture

```
┌─────────────────────────────────────────┐
│ CLI Layer (src/dlt_ibapi/cli_app.py)   │
│ - Command interface                     │
│ - Typer framework                       │
└─────────────────┬───────────────────────┘
                  │
┌─────────────────▼───────────────────────┐
│ DLT Resources (backfill/resources.py)  │
│ - snapshot_option_chain()               │
│ - backfill_option_bars()                │
│ - backfill_equity_bars()                │
│ - DLT @resource decorators              │
└─────────────────┬───────────────────────┘
                  │
┌─────────────────▼───────────────────────┐
│ Business Logic                          │
│ - Gap Detection (gap_detection.py)     │
│ - Contract Selection (contract_*)      │
│ - Transformers (transformers.py)       │
└─────────────────┬───────────────────────┘
                  │
┌─────────────────▼───────────────────────┐
│ Repository Layer (repositories/)        │
│ - EquityBarsReader                      │
│ - OptionBarsReader                      │
│ - OptionChainSnapshotReader             │
│ - ParquetReaderBase (DuckDB + PyArrow)  │
└─────────────────┬───────────────────────┘
                  │
┌─────────────────▼───────────────────────┐
│ Storage Layer                           │
│ - Parquet files (data/{dataset}/*.pqt) │
│ - Contract cache (.dlt-ibapi/cache/)   │
│ - DLT metadata (_dlt_*)                │
└─────────────────────────────────────────┘
```

### Design Principles

1. **DLT-First** - All data writes go through DLT resources
2. **Gap Detection** - Idempotent backfills only fetch missing data
3. **Separation of Concerns** - Clear boundaries between layers
4. **Type Safety** - Pydantic models throughout
5. **Reader/Writer Split** - Resources write, Repositories read
6. **Parquet Standard** - Hive-style partitioning for optimal queries

## 🛠️ CLI Commands

### Data Ingestion

```bash
# Backfill equity bars
dlt-ibapi backfill-equity AAPL --bar-size "1 day" --start-date 2025-01-01

# Backfill option bars (ATM mode)
dlt-ibapi backfill-options AAPL 180.0 --mode atm --k-strikes 3

# Backfill option bars (earnings batch mode)
dlt-ibapi backfill-options --earnings-date 2025-11-13 --k-expirations 6

# Snapshot option chain
dlt-ibapi snapshot AAPL --min-dte 7 --max-dte 60
```

### Earnings Calendar

```bash
# Load earnings from Nasdaq JSON
dlt-ibapi load-earnings earnings.json --start-date 2025-11-01

# List upcoming earnings
dlt-ibapi list-earnings --days-ahead 30 --symbols AAPL MSFT

# List snapshots
dlt-ibapi list-snapshots --days-back 7
```

### Contract Resolution

```bash
# Pre-populate contract cache (prevents API errors)
dlt-ibapi resolve-contracts AAPL MSFT GOOGL
dlt-ibapi resolve-contracts --earnings-date 2025-11-13
dlt-ibapi resolve-contracts --earnings-file earnings.json
```

### Data Quality

```bash
# Show dataset statistics
dlt-ibapi stats ./data --dataset stocks

# Validate data (check for duplicates)
dlt-ibapi validate --dataset options

# Deduplicate data (with automatic backup)
dlt-ibapi deduplicate --dataset options --dry-run
dlt-ibapi deduplicate --dataset options  # Execute
```

### Configuration

```bash
# Initialize config file
dlt-ibapi init

# Show current config
dlt-ibapi show-config

# Test IB Gateway connection
dlt-ibapi test-connection
```

### Logging Options

All commands support structured logging:

```bash
# Debug logging
dlt-ibapi backfill-equity AAPL --verbose

# Quiet mode (warnings/errors only)
dlt-ibapi backfill-equity AAPL --quiet

# JSON structured logs (for monitoring)
dlt-ibapi backfill-equity AAPL --json-logs

# Log to file with rotation
dlt-ibapi backfill-equity AAPL --log-file logs/backfill.log
```

## 🐍 Python API

### Historical Equity Bars

```python
import dlt
from dlt_ibapi import ib_historical_bars
from dlt_ibapi.config import IBConnectionConfig, IBHistoricalConfig

# Configure IB connection
ib_config = IBConnectionConfig(
    host="127.0.0.1",
    port=4002,  # IB Gateway paper trading
    client_id=1,
)

# Create pipeline
pipeline = dlt.pipeline(
    pipeline_name="ib_market_data",
    destination=dlt.destinations.filesystem(bucket_url="./data"),
    dataset_name="stocks",
)

# Fetch data
data = ib_historical_bars(
    symbol="AAPL",
    exchange="SMART",
    currency="USD",
    connection_config=ib_config,
    hist_config=IBHistoricalConfig(bar_size="1 day", duration="30 D"),
)

# Run pipeline (write as Parquet)
info = pipeline.run(data, loader_file_format="parquet")
```

### Gap-Aware Backfill

```python
from datetime import date
from dlt_ibapi.backfill.resources import backfill_equity_bars

# Backfill with automatic gap detection
backfill_data = backfill_equity_bars(
    symbol="AAPL",
    database_path="./data",
    dataset_name="stocks",
    start_date=date(2025, 1, 1),
    end_date=date(2025, 10, 20),
    bar_size="1 day",
    connection_config=ib_config,
)

# Run pipeline (idempotent - only fetches gaps)
info = pipeline.run(backfill_data, loader_file_format="parquet")
```

### Query Data

```python
from dlt_ibapi.repositories import EquityBarsReader, OptionBarsReader
from datetime import date

# Initialize readers
equity_reader = EquityBarsReader(database_path="./data", dataset_name="stocks")
option_reader = OptionBarsReader(database_path="./data", dataset_name="options")

# Query equity bars
equity_bars = equity_reader.get_bars(
    symbol="AAPL",
    bar_size="1 day",
    start_date=date(2025, 1, 1),
    end_date=date(2025, 10, 20),
)

# Query option bars
option_bars = option_reader.get_bars(
    underlying="AAPL",
    expiry=date(2025, 12, 20),
    strike=180.0,
    right="C",
    bar_size="5 mins",
    start_date=date(2025, 11, 1),
    end_date=date(2025, 11, 15),
)

# Metadata queries
symbols = equity_reader.get_available_symbols("1 day")
date_range = equity_reader.get_date_range("AAPL", "1 day")
```

### Example Analysis

```python
from dlt_ibapi.strategies import calculate_option_metrics

# Calculate metrics for an option contract
metrics = calculate_option_metrics(
    database_path="./data",
    underlying="AAPL",
    expiry=date(2025, 12, 20),
    strike=180.0,
    right="C",
    start_date=date(2025, 11, 1),
    end_date=date(2025, 11, 15),
)

if metrics:
    print(f"Average volume: {metrics.avg_volume:,.0f}")
    print(f"Average spread: {metrics.avg_spread:.2%}")
    print(f"Price range: ${metrics.price_range:.2f}")
```

## 📁 Data Organization

### Dataset Structure

```
data/
├── stocks/           # Equity bars
│   └── date=YYYY-MM-DD/
│       └── symbol=AAPL/
│           └── *.parquet
├── options/          # Option bars
│   └── date=YYYY-MM-DD/
│       └── underlying=AAPL/
│           └── *.parquet
├── option_chains/    # Option chain snapshots
│   └── as_of=YYYY-MM-DD/
│       └── underlying=AAPL/
│           └── *.parquet
└── earnings/         # Earnings calendar
    └── earnings_date=YYYY-MM-DD/
        └── symbol=AAPL/
            └── *.parquet
```

### Datasets

| Dataset | Purpose | CLI Commands | Primary Keys |
|---------|---------|--------------|--------------|
| `stocks` | Equity bars (spot prices) | `backfill-equity` | `[symbol, bar_size, time]` |
| `options` | Option bars (OHLCV) | `backfill-options` | `[underlying, expiry, strike, right, bar_size, time]` |
| `option_chains` | Option chain metadata | `snapshot` | `[underlying, as_of, exchange, trading_class]` |
| `earnings` | Earnings calendar | `load-earnings` | `[symbol, earnings_date]` |

## 🧪 Development

### Running Tests

```bash
# All tests
uv run pytest

# Unit tests only
uv run pytest tests/unit/

# Integration tests (requires IB Gateway)
uv run pytest tests/integration/

# With coverage
uv run pytest --cov=src/dlt_ibapi
```

### Code Quality

```bash
# Format code
uv run ruff format .

# Lint
uv run ruff check .

# Auto-fix issues
uv run ruff check --fix .
```

## 🐛 Troubleshooting

### IB Gateway Connection Issues

```bash
# Test connection
dlt-ibapi test-connection

# Check config
dlt-ibapi show-config
```

**Common issues:**
- Port mismatch (4002 for paper, 4001 for live)
- Client ID already in use
- API connections not enabled in IB settings

### "No security definition" Errors

```bash
# Pre-populate contract cache before large operations
dlt-ibapi resolve-contracts --earnings-date 2025-11-13
```

### Duplicate Data

```bash
# Check for duplicates
dlt-ibapi validate --dataset options

# Deduplicate (creates backup automatically)
dlt-ibapi deduplicate --dataset options
```

## 📖 Additional Resources

- **[DLT Documentation](https://dlthub.com/docs)** - Data Load Tool docs
- **[IB API Reference](https://interactivebrokers.github.io/tws-api/)** - Interactive Brokers API
- **[Parquet Format](https://parquet.apache.org/)** - Apache Parquet specification

## 📄 License

MIT License - see [LICENSE](LICENSE) for details.

## 🤝 Contributing

Contributions welcome! Please:

1. Fork the repository
2. Create a feature branch
3. Add tests for new features
4. Run `uv run ruff format . && uv run pytest`
5. Submit a pull request

## 🙏 Acknowledgments

Built with:
- [dlt](https://dlthub.com/) - Data Load Tool
- [ib-connector](https://github.com/yourusername/ib-connector) - IB Gateway wrapper
- [Typer](https://typer.tiangolo.com/) - CLI framework
- [Pydantic](https://docs.pydantic.dev/) - Data validation
- [structlog](https://www.structlog.org/) - Structured logging
