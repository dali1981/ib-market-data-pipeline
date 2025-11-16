# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

`dlt-ibapi` is a DLT (Data Load Tool) source connector for Interactive Brokers that ingests market data from IB Gateway/TWS into data pipelines. Built on top of `ib-connector`, it provides gap-aware historical data backfilling with Parquet-first storage architecture.

**Key Features:**
- Historical bars (equity + options) with gap detection
- Option chain snapshots with contract selection strategies
- Parquet files with Hive-style partitioning (date/symbol)
- Reader API for querying loaded data
- CLI tools and Python API

## Architecture

### Layer Separation

```
┌─────────────────────────────────────────┐
│ CLI Layer (src/dlt_ibapi/cli_app.py)   │
│ - Command interface                     │
│ - Uses --pipeline-name (new)           │
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
│ - ParquetReaderBase (filesystem)        │
└─────────────────┬───────────────────────┘
                  │
┌─────────────────▼───────────────────────┐
│ Storage Layer                           │
│ - Parquet files (data/{dataset}/*.pqt) │
│ - Contract cache (.dlt-ibapi/cache/)   │
│ - DLT metadata (_dlt_*)                │
└─────────────────────────────────────────┘
```

### Dataset Organization

`dlt-ibapi` organizes data into four primary datasets:

| Dataset | Purpose | CLI Commands | Location |
|---------|---------|--------------|----------|
| `stocks` | Equity bars (underlying spot prices) | `backfill-equity` | `./data/stocks/` |
| `options` | Option bars (OHLCV for specific contracts) | `backfill-options` | `./data/options/` |
| `option_chains` | Option chain snapshots (contract metadata) | `snapshot`, `list-snapshots` | `./data/option_chains/` |
| `earnings` | Earnings calendar (announcement dates/times) | `load-earnings`, `list-earnings` | `./data/earnings/` |

**Key Concepts:**
- **Dataset**: Logical grouping of related tables (e.g., all equity data → `stocks`)
- **Pipeline**: DLT execution instance with unique name (e.g., `ib_snapshots`)
- **Directory structure**: `./data/{dataset}/{table}/*.parquet`

**Data Separation:**
- **stocks**: Spot prices for underlying equities (backtesting reference prices)
- **options**: Pricing data (OHLCV) for specific option contracts
- **option_chains**: Metadata about available contracts (strikes, expirations, DTE) - NOT prices
- **earnings**: Calendar data (announcement dates, times, forecasts) for strategy timing

**Example Workflow:**
```bash
# 1. Load earnings calendar
dlt-ibapi load-earnings earnings.json

# 2. Capture option chain snapshot
dlt-ibapi snapshot AAPL --min-dte 7 --max-dte 60

# 3. Backfill option bars (single symbol)
dlt-ibapi backfill-options AAPL 150.0 --mode atm --k-strikes 3

# 3b. Backfill option bars (earnings batch - all symbols)
dlt-ibapi backfill-options --earnings-date 2025-11-13 --k-expirations 6 --k-strikes 5

# 3c. Backfill option bars (earnings batch - filter specific symbols)
dlt-ibapi backfill-options --earnings-date 2025-11-13 --symbols AAPL,MSFT --k-expirations 6

# 4. Backfill equity bars
dlt-ibapi backfill-equity AAPL --bar-size "1 day"

# 5. Verify data
dlt-ibapi stats ./data --dataset stocks
dlt-ibapi stats ./data --dataset options
dlt-ibapi stats ./data --dataset option_chains
dlt-ibapi stats ./data --dataset earnings
```

### CLI Architecture (New - Modular Pattern)

**As of 2025-11-07**, the CLI has been refactored into a modular architecture inspired by crypto_options:

```
CLI Layer (Typer) → Pydantic Models → Business Logic → Pydantic Results → Display (Rich)
```

**Structure**:
- `cli_app.py` - Main CLI entry point (Typer commands, presentation layer)
- `cli/models.py` - Pydantic models for all CLI commands (params + results)
- `cli/backfill.py` - Backfill business logic (equity + options)
- `cli/snapshot.py` - Snapshot business logic
- `cli/stats.py` - Stats business logic
- `utils/logging.py` - Structured logging utilities

**Note**: The main CLI file is named `cli_app.py` (not `cli.py`) to avoid naming conflicts with the `cli/` package directory. Python prioritizes packages over modules when both have the same name.

**Pattern**:
```python
# CLI command (presentation only)
@app.command()
def backfill_equity(...):
    params = BackfillEquityParams(...)  # Pydantic validation
    result = execute_backfill_equity(params)  # Business logic
    console.print(result)  # Display with Rich

# Business logic (testable)
def execute_backfill_equity(
    params: BackfillEquityParams,
    connection_config: Optional[...] = None,  # Dependency injection
    pipeline_factory: Optional[...] = None,  # For mocking
) -> BackfillEquityResult:
    # Pure function, no CLI dependencies
    return BackfillEquityResult(success=True, ...)
```

**Benefits**:
- Testable: Business logic separated from CLI framework
- Type-safe: Pydantic validation catches errors early
- Maintainable: Clear separation of concerns
- Injectable: Mock dependencies for testing

### Component Responsibilities

**DLT Resources** (`sources.py`, `backfill/resources.py`):
- DLT-decorated functions that yield data
- Handle IB API interaction via `ib-connector`
- Transform raw IB data to clean schemas
- Primary keys and write dispositions

**Transformers** (`transformers.py`):
- Normalize raw IB API data (timestamps, types)
- Clean and structure output schemas

**Gap Detection** (`backfill/gap_detection.py`):
- Calculate missing date ranges using business calendars
- Returns only gaps that need fetching (idempotent backfills)

**Repositories** (`repositories/`):
- Query API for reading Parquet data
- `ParquetReaderBase`: Base class for Parquet readers (uses DuckDB + PyArrow)
- Reader classes: EquityBarsReader, OptionBarsReader, etc.

**Contract Resolution** (`resolution/`):
- `ContractResolver`: Resolves symbols to IB Contract objects with caching
- `ContractCache`: Parquet-based cache for resolved contracts (`.dlt-ibapi/cache/contracts/`)
- Workflow: Check cache → Call ContractDetails API → Save to cache
- **Critical**: Must resolve symbols to contracts before calling IB API functions
- Use `dlt-ibapi resolve-contracts` CLI command to pre-populate cache

**Configuration**:
- Pydantic models for type safety (`config.py`)
- Config loader with hierarchy: code > env vars > YAML > defaults (`config_loader.py`)

### Parquet-First Migration

**As of 2025-10-21**, the project uses Parquet files with Hive partitioning instead of DuckDB databases:

**Storage Model:**
- Market data: `data/{dataset}/**/*.parquet` with Hive partitioning (date=YYYY-MM-DD/symbol=XXX)
- Contract cache: `.dlt-ibapi/cache/*.parquet` (custom format)
- DLT metadata: `_dlt_*` (JSONL files)

**Querying:**
- Small queries: DuckDB in-memory with `parquet_scan()`
- Large scans: PyArrow with predicate pushdown
- Automatic selection based on query size in `ParquetReaderBase`

**Benefits:**
- 10x compression vs raw databases
- Predicate pushdown (fast filtering on partitions)
- Cloud-ready (S3, GCS, Azure)
- Standard format (no vendor lock-in)

## Development Workflow

### Installation

```bash
# Install dependencies (includes ib-connector from ../ib-connector)
uv sync

# Install with dev dependencies
uv sync --dev

# Verify CLI is available
uv run dlt-ibapi version
```

### Running Tests

```bash
# All tests
uv run pytest

# Unit tests only
uv run pytest tests/unit/

# Integration tests (requires IB Gateway running)
uv run pytest tests/integration/

# Specific test file
uv run pytest tests/unit/test_gap_detection.py

# With verbose output
uv run pytest -v

# With coverage
uv run pytest --cov=src/dlt_ibapi
```

### Code Quality

```bash
# Format code
uv run ruff format .

# Lint (check for issues)
uv run ruff check .

# Auto-fix issues
uv run ruff check --fix .
```

### Logging

dlt-ibapi uses [structlog](https://www.structlog.org/) for structured logging. See [docs/LOGGING_GUIDE.md](docs/LOGGING_GUIDE.md) for complete documentation.

**Common logging options**:
```bash
# Debug logging (see all details)
uv run dlt-ibapi backfill-options AAPL 150.0 --verbose

# Quiet mode (warnings/errors only)
uv run dlt-ibapi backfill-options AAPL 150.0 --quiet

# Log to file with rotation (10MB max, 5 backups)
uv run dlt-ibapi backfill-options AAPL 150.0 --log-file logs/backfill.log

# JSON structured logs (for monitoring)
uv run dlt-ibapi backfill-options AAPL 150.0 --json-logs

# Combine options
uv run dlt-ibapi backfill-options --earnings-date 2025-11-13 \
  --verbose --json-logs --log-file logs/earnings_batch.json
```

**Log levels**:
- `--verbose` (`-v`): DEBUG level (detailed diagnostics)
- Default: INFO level (normal operation info)
- `--quiet` (`-q`): WARNING/ERROR only (production use)

**Structured events**: Logs use key-value pairs for context:
```
spot_price_selected: symbol=AAPL, earnings_time=PRE_MARKET, spot_price_date=2025-11-12, spot_price=180.50
```

**File rotation**: Automatically rotates at 10MB (keeps 5 backup files)

### CLI Usage

```bash
# Initialize config
uv run dlt-ibapi init

# Test IB Gateway connection
uv run dlt-ibapi test-connection

# Show current config
uv run dlt-ibapi show-config

# Backfill equity bars
uv run dlt-ibapi backfill-equity AAPL --bar-size "1 day"

# Snapshot option chain
uv run dlt-ibapi snapshot AAPL --min-dte 7 --max-dte 60

# Backfill option bars
uv run dlt-ibapi backfill-options AAPL 150.0 --mode atm --k-strikes 3

# Load earnings calendar
uv run dlt-ibapi load-earnings /path/to/earnings.json --start-date 2025-11-01

# List upcoming earnings
uv run dlt-ibapi list-earnings --days-ahead 30 --symbols AAPL MSFT

# Resolve contracts (pre-populate cache)
uv run dlt-ibapi resolve-contracts AAPL MSFT GOOGL
uv run dlt-ibapi resolve-contracts --earnings-date 2025-11-13
uv run dlt-ibapi resolve-contracts --earnings-file earnings.json

# Database statistics
uv run dlt-ibapi stats ./data --dataset stocks
uv run dlt-ibapi stats ./data --dataset earnings
```

## Key Design Principles

1. **DLT-First**: All data writes go through DLT resources (schema evolution, deduplication)
2. **Gap Detection**: Backfills are idempotent - only fetch missing data
3. **Separation of Concerns**: Library handles ingestion, Dagster (separate repo) handles orchestration
4. **Type Safety**: Pydantic models for configuration and data validation
5. **Reader/Writer Split**: Resources write data, Repositories read data (different APIs)
6. **Parquet Standard**: Use Hive-style partitioning (date/symbol) for optimal queries
7. **Contract Resolution First**: Resolve symbols to IB Contract objects before API calls (use `resolve-contracts` command)

## Important Code Patterns

### Creating DLT Resources

```python
@dlt.resource(
    name="equity_bars_backfill",
    write_disposition="append",
    primary_key=["symbol", "time", "bar_size"],
    columns={
        "date": {"partition": True},  # Hive partition
        "symbol": {"partition": True},  # Secondary partition
    }
)
def backfill_equity_bars(
    symbol: str,
    database_path: str,
    dataset_name: str,
    start_date: date,
    end_date: date,
    bar_size: str = "1 day",
    connection_config: Optional[IBConnectionConfig] = None,
    hist_config: Optional[IBHistoricalConfig] = None,
) -> Iterator[dict]:
    # 1. Detect gaps
    reader = EquityBarsReader(database_path, dataset_name)
    gaps = missing_windows(...)

    # 2. Fetch only gaps
    for gap_start, gap_end in gaps:
        bars = fetch_historical_bars(...)
        for bar in bars:
            yield normalize_bar_data(bar)  # Clean data before yielding
```

### Using Readers (Query API)

```python
from dlt_ibapi.repositories import EquityBarsReader

# Initialize reader
reader = EquityBarsReader(database_path="./data", dataset_name="stocks")

# Query bars
bars_df = reader.get_bars(
    symbol="AAPL",
    bar_size="1 day",
    start_date=date(2025, 1, 1),
    end_date=date(2025, 10, 20),
)

# Metadata queries
symbols = reader.get_available_symbols("1 day")
date_range = reader.get_date_range("AAPL", "1 day")
```

### Gap Detection

```python
from dlt_ibapi.backfill.gap_detection import missing_windows

gaps = missing_windows(
    start_date=date(2025, 1, 1),
    end_date=date(2025, 10, 20),
    existing_dates=[date(2025, 1, 1), date(2025, 1, 2)],  # What we have
    bar_size="1 day",
)
# Returns: [(date(2025, 1, 3), date(2025, 10, 20))]
```

### Contract Selection (Options)

```python
from dlt_ibapi.backfill.contract_selection import filter_contracts_by_selection_mode
from dlt_ibapi.backfill.config import ContractSelectionMode

selected = filter_contracts_by_selection_mode(
    contracts=[...],  # List of strikes/expirations
    spot_price=150.0,
    selection_mode=ContractSelectionMode.K_AROUND_ATM,
    k_strikes=3,
)
```

### Loading Earnings Data

```python
import dlt
from datetime import date
from dlt_ibapi import load_earnings_from_json

# Create pipeline
pipeline = dlt.pipeline(
    pipeline_name="earnings_loader",
    destination=dlt.destinations.filesystem(bucket_url="./data"),
    dataset_name="earnings",
)

# Load earnings from Nasdaq JSON file
data = load_earnings_from_json(
    json_file="/path/to/earnings.json",
    start_date=date(2025, 11, 1),
    end_date=date(2025, 12, 31),
    symbols=["AAPL", "MSFT", "GOOGL"],  # Optional filter
)

# Run pipeline (write_disposition="replace" replaces existing data)
info = pipeline.run(data, write_disposition="replace", loader_file_format="parquet")
print(f"Loaded {info.metrics.get('rows', 0)} earnings events")
```

**Alternative: Snapshot Loading** (for historical tracking):
```python
from dlt_ibapi import load_earnings_snapshot

# Load with snapshot date tracking
snapshot_data = load_earnings_snapshot(
    json_file="/path/to/earnings_2025-11-13.json",
    snapshot_date=date(2025, 11, 13),  # When snapshot was captured
    start_date=date(2025, 11, 13),
    end_date=date(2026, 2, 28),
)

# Append mode preserves historical snapshots
info = pipeline.run(snapshot_data, write_disposition="append", loader_file_format="parquet")
```

**Primary Key Difference**:
- `load_earnings_from_json`: `[symbol, earnings_date]` (current earnings)
- `load_earnings_snapshot`: `[symbol, earnings_date, snapshot_date]` (historical tracking)

**Earnings Time Field**: The `earnings_time` field is critical for accurate option pricing:
- `PRE_MARKET`: Options priced at previous day's close (before market opens)
- `AFTER_HOURS`: Options priced at same day's close (after market closes)
- `UNKNOWN`: Defaults to same day's close (conservative)

When using `--earnings-date` for option backfills, spot prices are automatically selected based on this field. Pre-market earnings on Monday use previous Friday's close (skips weekends/holidays via NYSE calendar).

### Querying Earnings Data

```python
from dlt_ibapi.repositories import EarningsCalendarReader
from datetime import date

# Initialize reader
reader = EarningsCalendarReader(database_path="./data", dataset_name="earnings")

# Get upcoming earnings (next 30 days)
upcoming = reader.get_upcoming_earnings(
    days_ahead=30,
    from_date=date.today(),
    symbols=["AAPL", "MSFT"],      # Optional filter
    earnings_time="AFTER_HOURS"     # Optional: "PRE_MARKET", "AFTER_HOURS", or None
)
print(upcoming[['symbol', 'earnings_date', 'earnings_time', 'company_name']])

# Get all earnings for a symbol
aapl_earnings = reader.get_earnings_for_symbol(
    symbol="AAPL",
    start_date=date(2025, 1, 1),
    end_date=date(2025, 12, 31)
)

# Check if earnings on specific date
earnings_today = reader.get_earnings_on_date(date.today())
has_earnings = not earnings_today.empty

# Get available symbols with earnings data
symbols = reader.get_available_symbols()
print(f"Earnings data for {len(symbols)} symbols")

# Get date range of available data
min_date, max_date = reader.get_date_range()
print(f"Earnings data from {min_date} to {max_date}")
```

## Configuration System

**Hierarchy** (highest to lowest priority):
1. Explicitly passed config objects in Python code
2. Environment variables (`IB_HOST`, `IB_PORT`, etc.)
3. User project config (`.dlt-ibapi/ib_gateway.yaml`)
4. Package defaults

**Example YAML** (`.dlt-ibapi/ib_gateway.yaml`):
```yaml
connection:
  host: 127.0.0.1
  port: 4002  # IB Gateway Paper Trading
  client_id: 1
  ready_timeout: 10.0

historical:
  duration: "1 D"
  bar_size: "1 min"
  what_to_show: "TRADES"
  use_rth: true
  timeout: 20.0
```

## Testing Guidelines

**Unit Tests** (`tests/unit/`):
- Test pure functions (gap detection, transformers)
- No IB Gateway required
- Use mock data

**Integration Tests** (`tests/integration/`):
- Test DLT resources end-to-end
- Requires IB Gateway running
- Uses test databases/Parquet files
- Clean up after tests

**Test Structure**:
```python
def test_gap_detection_with_business_days():
    """Test gap detection respects market calendar"""
    # Given
    existing = [date(2025, 1, 2), date(2025, 1, 3)]  # Thu, Fri

    # When
    gaps = missing_windows(
        start_date=date(2025, 1, 2),
        end_date=date(2025, 1, 7),  # Includes weekend
        existing_dates=existing,
        bar_size="1 day",
    )

    # Then
    assert gaps == [(date(2025, 1, 6), date(2025, 1, 7))]  # Mon, Tue only
```

## Relationship to Other Projects

**ib-connector** (`../ib-connector`):
- Standalone IB Gateway/TWS wrapper
- Provides: IBRuntime, HistoricalService, ContractDetailsService, etc.
- `dlt-ibapi` depends on it

**dagster-ib-pipeline** (`../dagster-ib-pipeline`):
- Orchestration layer using Dagster
- Wraps `dlt-ibapi` DLT resources as Dagster assets
- Handles scheduling, monitoring, and deduplication
- See `ARCHITECTURE_CLARIFICATION.md` for layer separation

**Separation**: Library (dlt-ibapi) handles data ingestion, Orchestrator (Dagster) handles scheduling/monitoring

## Contract Resolution Workflow

**Critical**: IB API functions require valid `Contract` objects, not just symbol strings. The proper workflow is:

1. **Resolve symbol to contract** (ContractDetails API call)
2. **Cache contract for reuse** (Parquet storage in `.dlt-ibapi/cache/contracts/`)
3. **Use contract in API calls** (historical data, option chains, etc.)

### Manual Pre-Population (Recommended)

Use the `resolve-contracts` CLI command to pre-populate the cache before expensive operations:

```bash
# Before running snapshot/backfill, resolve contracts first
dlt-ibapi resolve-contracts --earnings-date 2025-11-13

# This will:
# - Load symbols from earnings calendar
# - Check cache for existing contracts
# - Call ContractDetails API for new symbols
# - Handle failures gracefully (log and continue)
# - Save results to .dlt-ibapi/cache/contracts/

# Then run snapshot (uses cached contracts, no API overhead)
dlt-ibapi snapshot --earnings-date 2025-11-13 --min-dte 7 --max-dte 60
```

### Automatic Resolution (Fallback)

If not pre-populated, DLT resources will resolve contracts on-demand during execution. However:
- **Slower**: API call + cache write during data pipeline
- **Less robust**: Errors may interrupt pipeline
- **Not recommended** for batch operations

### Cache Location

Contracts are stored in Parquet format at `.dlt-ibapi/cache/contracts/` with structure:
```
.dlt-ibapi/cache/contracts/
  sec_type=STK/
    snapshot=2025-11-13/
      *.parquet
```

### Handling Invalid Symbols

Some symbols from earnings data may not exist in IB (delisted, wrong exchange, futures, etc.):
- `resolve-contracts` handles these gracefully: logs error and continues
- Failed symbols are reported in output table
- Cached contracts are used for valid symbols
- Invalid symbols are skipped in subsequent operations

## Common Gotchas

1. **Contract Resolution Required**: Never pass raw symbol strings to IB API - always resolve to Contract objects first
   ```python
   # WRONG - will fail
   bars = fetch_historical_bars("AAPL", ...)

   # RIGHT - resolve first
   contract_info = resolver.resolve_symbol("AAPL")
   contract = make_stock("AAPL", exch=contract_info["exchange"], ...)
   bars = fetch_historical_bars(contract, ...)
   ```

2. **Parquet Partitioning**: Always use `hive_partitioning=true` in DuckDB queries
   ```sql
   SELECT * FROM parquet_scan('./data/stocks/**/*.parquet', hive_partitioning=true)
   WHERE symbol = 'AAPL'  -- Partition pruning works!
   ```

3. **PyArrow Date Filters**: Use `pa.scalar()` for date comparisons
   ```python
   filters = [
       ("date", ">=", pa.scalar(start_date, type=pa.date32())),
       ("date", "<=", pa.scalar(end_date, type=pa.date32())),
   ]
   ```

4. **Gap Detection Business Days**: Use `pandas_market_calendars` to respect market hours
   ```python
   from dlt_ibapi.backfill.market_calendar import get_valid_trading_days
   business_days = get_valid_trading_days(start_date, end_date, bar_size)
   ```

5. **DLT Write Dispositions**:
   - `replace`: Snapshots (option chains)
   - `append`: Backfills with deduplication via primary keys
   - `merge`: Not typically used (DLT handles dedup automatically)

6. **Pre-populate Contract Cache**: Use `resolve-contracts` before batch operations
   - Avoids "No security definition" errors during pipelines
   - Handles invalid symbols gracefully
   - Cache location: `.dlt-ibapi/cache/contracts/`

## File Locations

**Core Source Files**:
- `src/dlt_ibapi/sources.py` - Basic DLT resources (historical bars, contract details)
- `src/dlt_ibapi/backfill/resources.py` - Backfill DLT resources with gap detection
- `src/dlt_ibapi/earnings.py` - Earnings calendar DLT resources (load from JSON)
- `src/dlt_ibapi/transformers.py` - Data normalization functions
- `src/dlt_ibapi/cli_app.py` - CLI entry point (Typer commands)
- `src/dlt_ibapi/cli/` - CLI business logic package (models, execution functions)

**Configuration**:
- `src/dlt_ibapi/config.py` - Pydantic config models
- `src/dlt_ibapi/config_loader.py` - Config hierarchy loader
- `src/dlt_ibapi/config_files/ib_gateway.yaml` - Default config

**Backfill Infrastructure**:
- `src/dlt_ibapi/backfill/gap_detection.py` - Gap detection logic
- `src/dlt_ibapi/backfill/contract_selection.py` - Option contract selection strategies
- `src/dlt_ibapi/backfill/market_calendar.py` - Business day calculations

**Contract Resolution**:
- `src/dlt_ibapi/resolution/resolver.py` - ContractResolver (symbol → IB Contract)
- `src/dlt_ibapi/resolution/contract_cache.py` - ContractCache (Parquet storage)
- `src/dlt_ibapi/cli/resolve.py` - CLI business logic for resolve-contracts command

**Repositories (Read API)**:
- `src/dlt_ibapi/repositories/base.py` - Base reader classes
- `src/dlt_ibapi/repositories/parquet_reader.py` - ParquetReaderBase (DuckDB + PyArrow)
- `src/dlt_ibapi/repositories/equity_bars.py` - EquityBarsReader
- `src/dlt_ibapi/repositories/option_bars.py` - OptionBarsReader
- `src/dlt_ibapi/repositories/option_chain.py` - OptionChainSnapshotReader
- `src/dlt_ibapi/repositories/earnings_calendar.py` - EarningsCalendarReader
- `src/dlt_ibapi/repositories/dataset_stats.py` - DatasetStatsReader (generic stats)

**Documentation**:
- `README.md` - User-facing documentation
- `docs/BACKFILL_GUIDE.md` - Complete backfill guide
- `docs/EARNINGS_GUIDE.md` - Earnings calendar loading and querying guide
- `docs/API_REFERENCE.md` - API documentation
- `ARCHITECTURE_CLARIFICATION.md` - DLT vs Dagster separation
- `PARQUET_MIGRATION_COMPLETE.md` - Parquet migration notes

## Dependencies

**Core**:
- `dlt[filesystem,parquet,duckdb]>=0.4.0` - Data Load Tool
- `ib-connector>=0.1.0` - IB Gateway wrapper (local dependency from `../ib-connector`)
- `pydantic>=2.0.0` - Type-safe configuration
- `pyarrow>=21.0.0` - Parquet support
- `pandas-market-calendars>=5.1.1` - Business day calculations

**CLI**:
- `typer>=0.19.2` - CLI framework
- `rich>=14.2.0` - Terminal formatting

**Dev**:
- `pytest>=7.0.0` - Testing framework
- `ruff>=0.1.0` - Linting and formatting

## Port Numbers (IB Gateway/TWS)

- `4001` - IB Gateway Live Trading
- `4002` - IB Gateway Paper Trading (default in config)
- `7496` - TWS Live Trading
- `7497` - TWS Paper Trading