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

# Database statistics
uv run dlt-ibapi stats ./data --dataset stocks
```

## Key Design Principles

1. **DLT-First**: All data writes go through DLT resources (schema evolution, deduplication)
2. **Gap Detection**: Backfills are idempotent - only fetch missing data
3. **Separation of Concerns**: Library handles ingestion, Dagster (separate repo) handles orchestration
4. **Type Safety**: Pydantic models for configuration and data validation
5. **Reader/Writer Split**: Resources write data, Repositories read data (different APIs)
6. **Parquet Standard**: Use Hive-style partitioning (date/symbol) for optimal queries

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

## Common Gotchas

1. **Parquet Partitioning**: Always use `hive_partitioning=true` in DuckDB queries
   ```sql
   SELECT * FROM parquet_scan('./data/stocks/**/*.parquet', hive_partitioning=true)
   WHERE symbol = 'AAPL'  -- Partition pruning works!
   ```

2. **PyArrow Date Filters**: Use `pa.scalar()` for date comparisons
   ```python
   filters = [
       ("date", ">=", pa.scalar(start_date, type=pa.date32())),
       ("date", "<=", pa.scalar(end_date, type=pa.date32())),
   ]
   ```

3. **Gap Detection Business Days**: Use `pandas_market_calendars` to respect market hours
   ```python
   from dlt_ibapi.backfill.market_calendar import get_valid_trading_days
   business_days = get_valid_trading_days(start_date, end_date, bar_size)
   ```

4. **DLT Write Dispositions**:
   - `replace`: Snapshots (option chains)
   - `append`: Backfills with deduplication via primary keys
   - `merge`: Not typically used (DLT handles dedup automatically)

5. **Contract Cache**: First run will be slower (needs to resolve contracts and cache)
   - Cache location: `.dlt-ibapi/cache/`
   - Subsequent runs use cached contract IDs

## File Locations

**Core Source Files**:
- `src/dlt_ibapi/sources.py` - Basic DLT resources (historical bars, contract details)
- `src/dlt_ibapi/backfill/resources.py` - Backfill DLT resources with gap detection
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

**Repositories (Read API)**:
- `src/dlt_ibapi/repositories/base.py` - Base reader classes
- `src/dlt_ibapi/repositories/parquet_reader.py` - ParquetReaderBase (DuckDB + PyArrow)
- `src/dlt_ibapi/repositories/equity_bars.py` - EquityBarsReader
- `src/dlt_ibapi/repositories/option_bars.py` - OptionBarsReader
- `src/dlt_ibapi/repositories/option_chain.py` - OptionChainSnapshotReader

**Documentation**:
- `README.md` - User-facing documentation
- `docs/BACKFILL_GUIDE.md` - Complete backfill guide
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