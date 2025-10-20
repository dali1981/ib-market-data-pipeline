# dlt-ibapi Implementation Plan: Use Cases 3, 4, 10
## Detailed Technical Specifications

**Version**: 2.0
**Date**: 2025-01-20
**Updated**: Architecture revised to DLT-first approach

---

## Executive Summary

Implement **Historical Market Data Backfilling** (UC3), **Real-Time Option Chain Monitoring** (UC4), and **Scheduled Data Collection Jobs** (UC10) for dlt-ibapi.

**Architecture**: DLT-first approach with lightweight reader repositories for gap detection

**Core Principles**:
- **DLT handles all writes** - No custom Parquet writers, DLT destinations are source of truth
- **Reader repositories** - Query DLT-written data for gap detection and coverage tracking
- **Writer repositories** - Only for contract caching (needs custom partitioning/deduplication)
- Symbol-to-contract resolution using IBKR MatchingSymbols + ContractDetails APIs
- Gap-aware backfilling with business day calendars
- Contract caching to minimize API calls

**Priority**: Option chain snapshots and option bars backfill (equity bars as supporting feature)

**Estimated Total Effort**: 10-14 hours across 7 phases

---

## Table of Contents

1. [Architecture Overview](#architecture-overview)
2. [Phase 0: Symbol & Contract Resolution Infrastructure](#phase-0-symbol--contract-resolution-infrastructure)
3. [Phase 1: Reader Repositories for Gap Detection](#phase-1-reader-repositories-for-gap-detection)
4. [Phase 2: Gap Detection & Backfill Logic](#phase-2-gap-detection--backfill-logic)
5. [Phase 3: DLT Resources for Backfilling](#phase-3-dlt-resources-for-backfilling)
6. [Phase 4: Configuration & CLI Extensions](#phase-4-configuration--cli-extensions)
7. [Phase 5: Examples & Documentation](#phase-5-examples--documentation)
8. [Phase 6: Testing](#phase-6-testing)
9. [Dependencies](#dependencies)
10. [Implementation Order](#implementation-order)
11. [Key Design Principles](#key-design-principles)

---

## Architecture Overview

### DLT-First Design

**Write Path**: DLT resources → DLT destination (DuckDB/Postgres/etc.)
- All market data writes go through DLT
- DLT handles schema evolution, typing, deduplication keys
- Standard DLT table structure with `write_disposition` and `primary_key`

**Read Path**: Reader repositories → Query DLT destination
- Lightweight query wrappers around DLT destinations
- Used only for gap detection (`present_dates()`)
- No custom Parquet I/O, no schema management

**Exception**: Contract caching uses custom writer repository
- Requires custom deduplication logic (by conid)
- Requires custom partitioning (sec_type, snapshot date)
- Minimal, focused implementation

### Data Flow

```
IB API
  ↓
DLT Resource (fetch + normalize)
  ↓
DLT Pipeline (write_disposition, primary_key)
  ↓
DLT Destination (DuckDB, Postgres, etc.)
  ↑ query for gap detection
Reader Repository (coverage tracking)
  ↓
Gap Detection (missing_windows)
  ↓
DLT Resource (fetch only gaps)
```

### Key Differences from Original Plan

| Aspect | Original Plan | DLT-First Plan |
|--------|--------------|----------------|
| **Data Writes** | Custom PyArrow writers | DLT handles all writes |
| **Schema Management** | Custom pa.Schema definitions | DLT infers from data |
| **Partitioning** | Custom Hive partitioning | DLT destination partitioning |
| **Deduplication** | Custom logic | DLT `primary_key` |
| **Repositories** | Read/write repositories | Read-only (except contracts) |
| **Complexity** | High (custom storage layer) | Low (DLT conventions) |

---

## Phase 0: Symbol & Contract Resolution Infrastructure

**Rationale**: IBKR requires Contract objects (not symbols) for all data requests. Contract resolution results need caching with custom deduplication.

### 0.1 Contract Cache Writer Repository

**File**: `src/dlt_ibapi/resolution/contract_cache.py`

**Purpose**: Cache resolved contracts to minimize IB API calls. Uses custom Parquet writer because:
1. Needs deduplication by `conid` (not just append)
2. Needs custom partitioning by `sec_type` and `snapshot` date
3. Small, focused dataset (thousands of contracts, not millions of bars)

**Schema Design**:
- symbol: string (normalized uppercase)
- sec_type: string (STK, OPT, FUT)
- conid: int64 (IB unique ID)
- exchange: string
- primary_exchange: string
- currency: string
- local_symbol: string
- trading_class: string
- multiplier: int (for options)
- long_name: string (company name)
- snapshot: date (partition key)
- created_at: timestamp

**Partitioning**: sec_type / snapshot (daily snapshots per security type)

**Operations**:
- `save(contracts_df)`: Write with deduplication by conid (keep latest)
- `get_by_symbol(symbol, sec_type)`: Lookup from cache
- `get_by_conid(conid)`: Reverse lookup
- `present_conids()`: Set of cached conids for existence checks

**Implementation Notes**:
- Use pyarrow.parquet.write_to_dataset with existing_data_behavior="overwrite_or_ignore"
- Single file per partition (small data)
- Load entire dataset into memory for queries (fast, small footprint)

### 0.2 Contract Resolver Service

**File**: `src/dlt_ibapi/resolution/contract_resolver.py`

**Purpose**: Resolve ticker symbols to IB Contract objects with caching

**Key Methods**:

```
resolve_symbol(symbol, sec_type="STK", exchange="SMART", currency="USD") -> Contract
  Algorithm:
  1. Check contract cache via get_by_symbol()
  2. If miss: Call MatchingSymbolService.fetch(pattern=symbol)
  3. Filter by sec_type, currency, primary_exchange
  4. If multiple matches: Prefer SMART, raise AmbiguousSymbolError if still ambiguous
  5. Call ContractDetailsService.fetch() for full details
  6. Save to cache
  7. Return Contract object

  Rate limiting: Enforce 1 sec between MatchingSymbols calls

resolve_symbols_batch(symbols) -> Dict[symbol, Contract]
  Batch resolution with progress tracking

resolve_from_conid(conid) -> Contract
  Resolve by IB contract ID
```

**Error Handling**:
- `SymbolNotFoundError`: No matches in IB
- `AmbiguousSymbolError`: Multiple matches, includes candidates list
- `RetryableIBError`: Timeout, can retry with backoff

**Rate Limiting**:
- MatchingSymbols: 1 call/sec (IB requirement)
- ContractDetails: 50 calls/sec (use semaphore for batch)

### 0.3 Contract Descriptions Cache (Optional)

**File**: `src/dlt_ibapi/resolution/contract_descriptions.py`

**Purpose**: Lightweight cache of MatchingSymbols results for fast "has options?" checks

**Implementation**: Could be DLT table or simple JSON cache (decide during implementation)

**Schema**: symbol, sec_type, conid, derivative_sec_types (list)

**Use Case**: Check if symbol has options before requesting option chains

---

## Phase 1: Reader Repositories for Gap Detection

**Philosophy**: Repositories are **read-only** query wrappers around DLT-written data. No schema management, no write logic.

### 1.1 Base Reader Repository

**File**: `src/dlt_ibapi/repositories/base_reader.py`

**Purpose**: Abstract base for querying DLT destinations

**Key Methods**:

```
__init__(pipeline_name, dataset_name, destination="duckdb")
  - Connects to DLT destination database
  - No schema enforcement (reads what DLT wrote)

present_dates(table_name, start_date, end_date, **filters) -> Set[date]
  - Query: SELECT DISTINCT date FROM {table} WHERE date BETWEEN start AND end AND {filters}
  - Returns set of dates with data
  - Generic implementation works for all tables with date columns

_query(sql, params) -> pd.DataFrame
  - Execute SQL against DLT destination
  - Returns pandas DataFrame
  - Handles connection pooling

_get_connection()
  - Returns DB connection (DuckDB, Postgres, etc.)
  - Uses DLT pipeline API to get destination connection
```

**No Custom Parquet I/O**: Queries go through DLT destination's SQL interface

### 1.2 Equity Bars Reader

**File**: `src/dlt_ibapi/repositories/equity_bars_reader.py`

**Purpose**: Query equity bars written by DLT for coverage tracking

**DLT Table**: `{dataset}.equity_bars_backfill` (from DLT resource name)

**Expected Schema** (inferred by DLT from yielded dicts):
- time: timestamp
- date: date
- symbol: string
- bar_size: string
- open/high/low/close/volume: float
- wap, bar_count: nullable

**Methods**:

```
present_dates(symbol, bar_size, start_date, end_date) -> Set[date]
  SQL: SELECT DISTINCT date FROM equity_bars_backfill
       WHERE symbol = ? AND bar_size = ? AND date BETWEEN ? AND ?

get_date_range(symbol, bar_size) -> (min_date, max_date)
  SQL: SELECT MIN(date), MAX(date) FROM equity_bars_backfill
       WHERE symbol = ? AND bar_size = ?

load_range(symbol, bar_size, start_date, end_date) -> pd.DataFrame
  SQL: SELECT * FROM equity_bars_backfill
       WHERE symbol = ? AND bar_size = ? AND date BETWEEN ? AND ?
```

**Implementation Notes**:
- No write methods
- SQL-based queries only
- Delegates to DLT destination's query engine

### 1.3 Option Bars Reader

**File**: `src/dlt_ibapi/repositories/option_bars_reader.py`

**DLT Table**: `{dataset}.option_bars_backfill`

**Expected Schema**:
- time, date, trade_date: timestamp/date
- underlying, expiry (date), strike, right: contract identifiers
- bar_size: string
- open/high/low/close/volume: float

**Methods**:

```
present_dates_for_contract(underlying, expiry, right, strike, bar_size, start, end) -> Set[date]
  SQL: SELECT DISTINCT date FROM option_bars_backfill
       WHERE underlying = ? AND expiry = ? AND right = ? AND strike = ?
       AND bar_size = ? AND date BETWEEN ? AND ?

list_known_contracts(underlying, limit=None) -> List[Tuple]
  SQL: SELECT DISTINCT underlying, expiry, right, strike FROM option_bars_backfill
       WHERE underlying = ? ORDER BY expiry, strike, right LIMIT ?
  Returns list of tuples for contract identification

load_contract_range(...) -> pd.DataFrame
  SQL: SELECT * FROM option_bars_backfill WHERE ...
```

### 1.4 Option Chain Snapshot Reader

**File**: `src/dlt_ibapi/repositories/option_chains_reader.py`

**DLT Table**: `{dataset}.option_chain_snapshot`

**Expected Schema**:
- underlying, underlying_conid: identifiers
- exchange, trading_class, multiplier: contract metadata
- expirations: JSON/list (DLT handles list serialization)
- strikes: JSON/list
- as_of: date (snapshot date)

**Methods**:

```
get_latest_snapshot_date(underlying) -> date
  SQL: SELECT MAX(as_of) FROM option_chain_snapshot WHERE underlying = ?

get_latest_snapshot(underlying) -> pd.DataFrame (single row)
  SQL: SELECT * FROM option_chain_snapshot
       WHERE underlying = ? AND as_of = (SELECT MAX(as_of) FROM option_chain_snapshot WHERE underlying = ?)

get_available_expiries(underlying, snapshot_date=None) -> List[date]
  - Fetch snapshot
  - Parse expirations JSON/list field
  - Return as list of dates
```

**List Field Handling**: DLT serializes lists as JSON in most destinations, parse on read

---

## Phase 2: Gap Detection & Backfill Logic

### 2.1 Gap Detection Utilities

**File**: `src/dlt_ibapi/backfill/windows.py`

**Key Function**:

```
missing_windows(present_dates: Set[date], start: date, end: date, calendar="NYSE") -> List[Tuple[date, date]]
  Algorithm:
  1. Generate business day range using pandas (NYSE calendar or 24/7)
  2. Compute missing = desired_dates - present_dates
  3. Group consecutive missing dates into contiguous windows
  4. Return list of (window_start, window_end) tuples

  Examples:
  - Full coverage → []
  - No coverage → [(start, end)]
  - Scattered gaps → [(gap1_start, gap1_end), (gap2_start, gap2_end)]
```

**Business Calendar Support**:
- NYSE: Use pandas bdate_range with US federal holidays
- Optional: pandas-market-calendars for accurate NYSE calendar
- 24/7: Use date_range for crypto/forex (future)

### 2.2 Backfill Configuration Models

**File**: `src/dlt_ibapi/backfill/config.py`

**Purpose**: Type-safe Pydantic configs for backfill operations

**Models**:

```
BackfillConfig:
  - underlying: str
  - start: date
  - end: date
  - bar_size: str = "1 day"
  - calendar: str = "NYSE"
  - Validation: start <= end, bar_size in VALID_BAR_SIZES

OptionBackfillConfig(BackfillConfig):
  - expiries_max: int = 8
  - strikes_per_side: int = 6
  - selection_mode: str = "k_around_atm"  # or "moneyness" or "delta"
  - moneyness_targets: List[float] = [0.8, 0.9, 1.0, 1.1, 1.2]
  - delta_targets: List[float] = [0.25, 0.50, 0.75]
  - iv_estimate: float = 0.25
  - min_dte: int = 0
  - max_dte: int = 90
```

### 2.3 Contract Selection Logic

**File**: `src/dlt_ibapi/backfill/contract_selection.py`

**Purpose**: Select option contracts to backfill based on strategies

**Functions**:

```
select_contracts_atm(chain_snapshot, spot_price, strikes_per_side, expiries_max, min_dte, max_dte, as_of_date) -> List[Dict]
  - Filter expiries by DTE range
  - For each expiry: find ATM strike, select k strikes on each side
  - Return list of contract specs (underlying, expiry, strike, right)

select_contracts_moneyness(chain_snapshot, spot_price, moneyness_targets, ...) -> List[Dict]
  - For each target moneyness (e.g., 0.9, 1.0, 1.1)
  - Find closest strike to spot_price * moneyness
  - Deduplicate strikes

select_contracts_delta(chain_snapshot, spot_price, delta_targets, iv_estimate, ...) -> List[Dict]
  - Use simplified Black-Scholes to solve for strike given target delta
  - Requires scipy.stats.norm for CDF/inverse CDF
  - Find closest actual strike in chain
```

**Output Format**: List of dicts with keys: underlying, expiry, strike, right, moneyness, dte

---

## Phase 3: DLT Resources for Backfilling

**Core Pattern**: DLT resources fetch data from IB, normalize, and yield dicts. DLT handles all writes.

### 3.1 Equity Bars Backfill Resource

**File**: `src/dlt_ibapi/resources/backfill_equity.py`

**DLT Resource**:

```
@dlt.resource(
    name="equity_bars_backfill",
    write_disposition="append",
    primary_key=["symbol", "bar_size", "time"]
)
def backfill_equity_bars(symbol, start_date, end_date, bar_size="1 day", pipeline_name=None, ...) -> Iterator[dict]
```

**Algorithm**:

```
1. Initialize reader repository (queries DLT destination)
2. Resolve symbol to IB Contract via ContractResolver
3. Check coverage: reader.present_dates(symbol, bar_size, start_date, end_date)
4. Find gaps: missing_windows(present_dates, start_date, end_date)
5. For each gap window:
   a. Fetch bars from IB HistoricalService
   b. Normalize: add symbol, bar_size, rename IB fields
   c. Yield dicts (DLT writes them)
6. Log summary
```

**Key Points**:
- No manual Parquet writes
- DLT `primary_key` ensures no duplicates on time dimension
- Reader repository queries DLT destination for coverage
- `pipeline_name` parameter needed to connect reader to correct DLT pipeline

**Yielded Dict Structure**:

```
{
  "time": datetime,  # IB "date" field
  "date": date,      # derived from time
  "symbol": str,
  "bar_size": str,
  "open": float,
  "high": float,
  "low": float,
  "close": float,
  "volume": float,
  "wap": float (optional),
  "bar_count": int (optional)
}
```

### 3.2 Option Chain Snapshot Resource

**File**: `src/dlt_ibapi/resources/option_chains.py`

**DLT Resource**:

```
@dlt.resource(
    name="option_chain_snapshot",
    write_disposition="replace",  # Daily snapshot, replace on rerun
    primary_key=["underlying", "as_of"]
)
def snapshot_option_chain(symbol, snapshot_date=None, pipeline_name=None, ...) -> Iterator[dict]
```

**Algorithm**:

```
1. snapshot_date = snapshot_date or today()
2. Check if snapshot exists via reader.get_latest_snapshot(symbol)
3. If exists for date, yield cached (idempotent)
4. Resolve symbol to Contract
5. Fetch option params from IB SecDefService
6. Aggregate:
   - Union all expirations from all exchanges
   - Union all strikes
   - Deduplicate and sort
7. Yield single dict:
   {
     "underlying": symbol,
     "underlying_conid": conid,
     "exchange": primary_exchange,
     "trading_class": trading_class,
     "multiplier": multiplier,
     "expirations": [list of ISO date strings],
     "strikes": [sorted list of floats],
     "as_of": snapshot_date,
     "created_at": datetime.now()
   }
```

**Key Points**:
- DLT handles list serialization (JSON in most destinations)
- `write_disposition="replace"` for daily snapshot semantics
- No custom aggregation logic in repository layer

### 3.3 Option Bars Backfill Resource

**File**: `src/dlt_ibapi/resources/backfill_options.py`

**DLT Resource**:

```
@dlt.resource(
    name="option_bars_backfill",
    write_disposition="append",
    primary_key=["underlying", "expiry", "strike", "right", "bar_size", "time"]
)
def backfill_option_bars(underlying, start_date, end_date, bar_size="1 day", config=None, pipeline_name=None, ...) -> Iterator[dict]
```

**Algorithm**:

```
1. Load option chain snapshot via reader
2. Get spot price from equity bars reader
3. Select contracts based on config.selection_mode:
   - k_around_atm: select_contracts_atm()
   - moneyness: select_contracts_moneyness()
   - delta: select_contracts_delta()
4. For each selected contract:
   a. Check coverage via reader.present_dates_for_contract()
   b. Find gaps via missing_windows()
   c. For each gap:
      - Create IB option Contract via make_option()
      - Fetch bars from HistoricalService
      - Normalize: add underlying, expiry, strike, right
      - Yield dicts
   d. Handle errors gracefully (log, continue to next contract)
5. Track stats: successful/failed/no_data contracts
```

**Yielded Dict Structure**:

```
{
  "time": datetime,
  "date": date,
  "trade_date": date,
  "underlying": str,
  "expiry": date,
  "strike": float,
  "right": str,  # "C" or "P"
  "bar_size": str,
  "open": float,
  "high": float,
  "low": float,
  "close": float,
  "volume": float,
  "wap": float (optional),
  "bar_count": int (optional),
  "contract_id": int (optional)  # IB conId
}
```

**Error Resilience**:
- Try/except per contract
- `IBNoDataError` → log warning, continue
- Other errors → log error, continue
- Don't fail entire backfill for single contract

---

## Phase 4: Configuration & CLI Extensions

### 4.1 Configuration Updates

**File**: `src/dlt_ibapi/config.py` (additions)

Add Pydantic models:
- `IBBackfillConfig`: repository_root, max_retries, batch_size, rate_limit_delay
- `IBOptionBackfillConfig`: expiries_max, strikes_per_side, selection_mode, moneyness_targets, delta_targets, iv_estimate, min_dte, max_dte

**File**: `src/dlt_ibapi/config_files/ib_gateway.yaml` (additions)

Add sections:
- backfill: repository_root (for contract cache), max_retries, batch_size, rate_limit_delay
- option_backfill: expiries_max, strikes_per_side, selection_mode, targets, DTE range

**File**: `src/dlt_ibapi/config_loader.py` (additions)

Add loader functions:
- `get_backfill_config() -> IBBackfillConfig`
- `get_option_backfill_config() -> IBOptionBackfillConfig`

### 4.2 CLI Commands

**File**: `src/dlt_ibapi/cli.py` (additions)

Commands:

```
dlt-ibapi backfill-equity SYMBOL --start YYYY-MM-DD --end YYYY-MM-DD [--bar-size "1 day"]
  - Creates DLT pipeline
  - Calls backfill_equity_bars resource
  - Displays progress and results

dlt-ibapi snapshot-chains SYMBOL1 SYMBOL2 ... [--date YYYY-MM-DD]
  - Creates DLT pipeline
  - Calls snapshot_option_chain for each symbol
  - Displays snapshot summary

dlt-ibapi backfill-options UNDERLYING --start YYYY-MM-DD --end YYYY-MM-DD [--mode k_around_atm] [--strikes 6] [--expiries 8]
  - Creates DLT pipeline
  - Calls backfill_option_bars resource
  - Displays contract selection and progress

dlt-ibapi show-coverage SYMBOL [--type equity|option] [--bar-size "1 day"]
  - Uses reader repository to query DLT destination
  - Displays coverage table (date range, gaps)
```

**Implementation Notes**:
- Use typer for CLI
- Use rich for formatted output (tables, progress bars)
- Handle DLT pipeline creation and destination connection

---

## Phase 5: Examples & Documentation

### 5.1 Examples

**File**: `examples/backfill_equity_bars.py`

Demonstrates:
- Simple equity backfill with gap detection
- DLT pipeline setup
- Querying results from DuckDB
- Running multiple times (idempotent)

**File**: `examples/backfill_option_bars.py`

Demonstrates:
- All three contract selection modes
- Option chain snapshot prerequisite
- DLT pipeline for option bars
- Querying option data

**File**: `examples/option_chain_snapshots.py`

Demonstrates:
- Daily snapshot capture
- Querying snapshot data
- Using snapshots for backfill planning

### 5.2 Documentation

**File**: `README.md` (additions)

Add sections:
- Backfilling Historical Data (Quick Start)
- Gap Detection (how it works)
- Contract Selection Modes (ATM, moneyness, delta)
- DLT Integration (write_disposition, primary_key)
- Reader Repositories (querying for coverage)

**File**: `specs/BACKFILL_GUIDE.md` (new comprehensive guide)

Sections:
1. Architecture Overview (DLT-first design)
2. Symbol Resolution & Contract Caching
3. Gap Detection Algorithm
4. Contract Selection Deep Dive
5. DLT Resource Patterns
6. Reader Repository Patterns
7. Performance Tuning
8. Troubleshooting

---

## Phase 6: Testing

### 6.1 Unit Tests

**Contract Resolution**:
- `tests/resolution/test_contract_cache.py`: Cache read/write, deduplication
- `tests/resolution/test_contract_resolver.py`: Symbol resolution, rate limiting, error handling

**Reader Repositories**:
- `tests/repositories/test_equity_bars_reader.py`: present_dates(), date_range()
- `tests/repositories/test_option_bars_reader.py`: present_dates_for_contract(), list_known_contracts()
- `tests/repositories/test_option_chains_reader.py`: get_latest_snapshot(), parse expirations

**Backfill Logic**:
- `tests/backfill/test_windows.py`: missing_windows() correctness
- `tests/backfill/test_contract_selection.py`: ATM/moneyness/delta selection

### 6.2 Integration Tests

**DLT Resources**:
- `tests/integration/test_equity_backfill.py`: End-to-end equity backfill with mocked IB API
- `tests/integration/test_option_chain_snapshot.py`: End-to-end snapshot with mocked IB API
- `tests/integration/test_option_backfill.py`: End-to-end option backfill

**Verification**:
- Verify data written to DLT destination (DuckDB)
- Verify gap detection works on second run
- Verify idempotency (no duplicates with primary_key)

### 6.3 Test Fixtures

**Mocked IB API**:
- `fixtures/mock_ib_responses.py`: Sample historical bars, option params, contract details
- Use pytest fixtures for IB service mocking

**DLT Test Pipelines**:
- Create temporary DuckDB databases for testing
- Clean up after tests

---

## Dependencies

**Update pyproject.toml**:

```toml
[project]
dependencies = [
    "dlt[duckdb]>=0.4.0",
    "ib-connector>=0.1.0",
    "pydantic>=2.0.0",
    "omegaconf>=2.3.0",
    "typer>=0.19.2",
    "rich>=14.2.0",
    "pyarrow>=16.0.0",  # For contract cache only
    "pandas>=2.0.0",
    "scipy>=1.11.0",  # For Black-Scholes delta calculations
]

[project.optional-dependencies]
dev = [
    "pytest>=7.0.0",
    "pytest-cov>=4.0.0",
    "pandas-market-calendars>=4.0.0",  # Accurate NYSE calendar
]
```

**Key Changes from Original**:
- pyarrow only for contract cache (not full repository layer)
- pandas-market-calendars optional for accurate business day calendar

---

## Implementation Order

### Simplified Order (DLT-First)

1. **Phase 0.1** - Contract cache writer repository (focused Parquet writer)
2. **Phase 0.2** - ContractResolver service with caching
3. **Phase 2.1, 2.2** - Gap detection utilities + config models
4. **Phase 1.1** - Base reader repository (SQL queries against DLT destination)
5. **Phase 1.4** - Option chain snapshot reader
6. **Phase 3.2** - Option chain snapshot DLT resource (PRIORITY 1)
7. **Phase 1.3** - Option bars reader
8. **Phase 2.3** - Contract selection logic
9. **Phase 3.3** - Option bars backfill DLT resource (PRIORITY 2)
10. **Phase 1.2** - Equity bars reader
11. **Phase 3.1** - Equity bars backfill DLT resource
12. **Phase 4** - Configuration + CLI
13. **Phase 5** - Examples + Documentation
14. **Phase 6** - Testing (parallel with development)

**Estimated Total Time**: 10-14 hours (reduced from 12-16 due to simpler architecture)

---

## Key Design Principles

### DLT-First Principles

1. **DLT Handles All Data Writes**: No custom Parquet writers except contract cache
2. **DLT Manages Schema**: Infer from yielded dicts, no manual pa.Schema definitions
3. **DLT Handles Deduplication**: Use `primary_key` for composite keys
4. **DLT Manages Partitioning**: Destination-specific partitioning (if supported)
5. **Reader Repositories Query DLT**: SQL queries against destination, not custom Parquet readers

### Contract Resolution

6. **Symbol Resolution First**: All IB API calls require Contract objects
7. **Contract Caching**: Custom repository only for contracts (small dataset, needs deduplication)
8. **Rate Limiting**: Enforce IB API limits (1/sec MatchingSymbols, 50/sec ContractDetails)

### Gap Detection

9. **Gap-Aware Backfilling**: Only fetch missing data via reader repository queries
10. **Business Day Calendar**: Use NYSE calendar for realistic gap detection
11. **Idempotent Resources**: Re-running backfill only fills gaps, no duplicates

### Error Resilience

12. **Per-Contract Error Handling**: Single contract failure doesn't stop batch
13. **Graceful Degradation**: Log warnings for no-data contracts, continue processing
14. **Retry Logic**: Configurable retries for transient IB errors

### Performance

15. **Batch Operations**: Resolve multiple symbols concurrently where possible
16. **Connection Pooling**: Reuse IB runtime across windows within single run
17. **SQL Query Optimization**: Use destination's query engine for coverage checks

---

## Comparison: Original vs DLT-First

| Component | Original Plan | DLT-First Plan | Benefit |
|-----------|--------------|----------------|---------|
| **Data Writes** | Custom PyArrow repositories | DLT resources | Simpler, standard DLT patterns |
| **Schema Management** | Manual pa.Schema definitions | DLT infers from dicts | Less code, automatic evolution |
| **Deduplication** | Custom logic in repositories | DLT primary_key | Built-in, reliable |
| **Gap Detection** | Query Parquet files directly | Query DLT destination via SQL | Works with any DLT destination |
| **Partitioning** | Custom Hive partitioning | DLT destination partitioning | Destination-optimized |
| **Code Complexity** | High (full repository layer) | Low (query wrappers) | Faster implementation |
| **Contract Cache** | Custom repository | Custom repository | Same (still needed) |
| **Total LoC** | ~3000 lines | ~1500 lines | 50% reduction |

**Key Insight**: DLT is designed to handle data loading. Use it for what it's good at, only write custom code where truly needed (contract caching with deduplication).

---

## Notes

- This plan uses DLT as the primary data storage mechanism
- Reader repositories are lightweight SQL query wrappers
- Contract cache is the only custom Parquet writer (small, focused use case)
- No reuse of earnings_ibapi repositories (clean implementation)
- Get schemas/fields from earnings_ibapi as reference only
- Architecture is simpler and aligns with DLT best practices
- Estimated effort reduced by 20% due to eliminated custom storage layer
