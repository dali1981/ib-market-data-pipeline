# Architecture Overview

## Design Principles

### 1. Modularity at the Library Level

Each component can be used independently:

- **Scraper**: Standalone scraper usable without dlt or Dagster
- **DLT Pipeline**: Can be run without Dagster orchestration
- **Read API**: Query data without knowing about scraping/pipeline internals
- **Dagster Assets**: Optional orchestration layer

### 2. Separation of Concerns

```
┌─────────────────────────────────────────────────────────────┐
│                     Application Layer                       │
│  (Examples, Notebooks, Custom Scripts)                      │
└─────────────────────────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────┐
│                   Orchestration Layer                        │
│  (Dagster: Assets, Schedules, Jobs)                         │
└─────────────────────────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────┐
│                      Pipeline Layer                          │
│  (dlt: Sources, Resources, Transformers)                    │
└─────────────────────────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────┐
│                     Data Access Layer                        │
│  (Scraper, Config, API)                                     │
└─────────────────────────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────┐
│                      Storage Layer                           │
│  (Parquet Files, Filesystem/DuckDB)                         │
└─────────────────────────────────────────────────────────────┘
```

## Component Details

### Data Access Layer

#### Scraper (`scraper.py`)

- **Purpose**: Fetch data from Nasdaq
- **Dependencies**: httpx, playwright (optional)
- **Strategy**: Try API first, fall back to Playwright
- **Output**: List of raw dictionaries

**Key Design Decisions:**
- Hybrid approach for reliability
- No external dependencies beyond HTTP client
- Configurable timeout and retry logic
- Returns structured data (not HTML/JSON)

#### Config (`config.py`)

- **Purpose**: Centralized configuration
- **Pattern**: Pydantic models with validation
- **Loading**: Environment variables, YAML files, or defaults
- **Consistency**: Similar to dlt-ibapi config system

#### Transformers (`transformers.py`)

- **Purpose**: Normalize and clean data
- **Pattern**: Pure functions for testability
- **Features**: Type conversion, date parsing, calculated fields
- **Extensibility**: Easy to add new transformations

### Pipeline Layer

#### DLT Sources (`sources.py`)

- **Resources**: `earnings_calendar_resource`
- **Sources**: `nasdaq_earnings_source`
- **Write Disposition**: `replace` (daily snapshots)
- **Primary Key**: `symbol` (within each snapshot)

**Key Design Decisions:**
- Daily snapshots instead of incremental updates
- Simple deduplication strategy
- Partition by `snapshot_date` for historical queries
- Resource-level configuration injection

#### Read API (`api.py`)

- **Purpose**: Query stored Parquet data
- **Backend**: DuckDB for SQL queries
- **Pattern**: Repository pattern with specialized queries
- **Performance**: Predicate pushdown to Parquet

**Key Design Decisions:**
- DuckDB for complex aggregations
- PyArrow for simple reads
- Convenience functions for common queries
- Matches ParquetReader pattern from dlt-ibapi

### Orchestration Layer

#### Dagster Assets (`assets.py`)

Two implementations provided:

1. **@dlt_assets decorator**:
   - Automatic asset creation
   - Built-in metadata tracking
   - Recommended for simplicity

2. **Custom asset**:
   - Manual control
   - Custom metadata
   - Flexible error handling

**Key Design Decisions:**
- Group name: `earnings_calendar`
- Compute kind: `dlt`
- Asset metadata includes record counts

#### Schedules (`schedules.py`)

Three schedule options:

1. **Daily (6 AM)**: Default schedule
2. **Weekday only**: Skip weekends
3. **Custom**: Dynamic configuration

**Key Design Decisions:**
- Morning schedule (before market open)
- Configurable via run config
- Tagged with metadata

#### Definitions (`definitions.py`)

- **Purpose**: Bundle all Dagster components
- **Pattern**: Single `Definitions` object
- **Resources**: DagsterDltResource for dlt integration

## Data Flow

### Write Path

```
1. Dagster Schedule Triggers
           ↓
2. Asset Materialization Starts
           ↓
3. DLT Resource Activated
           ↓
4. Scraper Fetches Data (API/Playwright)
           ↓
5. Transformer Normalizes Records
           ↓
6. DLT Writes to Parquet
           ↓
7. Asset Metadata Updated
```

### Read Path

```
1. User Query (API Call)
           ↓
2. EarningsCalendarReader
           ↓
3. DuckDB SQL Query
           ↓
4. Parquet Predicate Pushdown
           ↓
5. Results Returned
```

## Storage Strategy

### Daily Snapshots

**Why snapshots over incremental?**

1. **Simplicity**: No deduplication logic needed
2. **Historical Analysis**: See how estimates changed over time
3. **Data Quality**: Complete state each day
4. **Debugging**: Easy to identify when data changed

**Trade-offs:**
- More storage space (acceptable for this use case)
- Simpler query logic
- No merge conflicts

### Partitioning

```
data/nasdaq_earnings/earnings_calendar/
├── snapshot_date=2025-10-21/
│   └── earnings_calendar.parquet
├── snapshot_date=2025-10-22/
│   └── earnings_calendar.parquet
└── snapshot_date=2025-10-23/
    └── earnings_calendar.parquet
```

Partition columns:
- `snapshot_date`: When data was captured
- `earnings_year`: For range queries
- `earnings_month`: For range queries

## Integration Patterns

### Standalone Usage

```python
from earnings_calendar import fetch_earnings_calendar

data = fetch_earnings_calendar(days_ahead=30)
# Use data however you want
```

### DLT Pipeline

```python
from earnings_calendar import run_pipeline

load_info = run_pipeline(days_ahead=30)
# Pipeline handles everything
```

### Dagster Orchestration

```python
# Just run: dagster dev -m dagster_earnings
# Everything configured in definitions.py
```

### Combined with dlt-ibapi

```python
import dlt
from earnings_calendar import nasdaq_earnings_source
from dlt_ibapi import ib_source

pipeline = dlt.pipeline(
    pipeline_name="trading_data",
    destination="filesystem"
)

# Load both sources
pipeline.run(nasdaq_earnings_source())
pipeline.run(ib_source(symbols=["AAPL"]))
```

## Testing Strategy

### Unit Tests

- Pure functions (transformers)
- Configuration loading
- Data normalization

### Integration Tests

- Scraper with mock responses
- DLT pipeline with test data
- Dagster asset materialization

### End-to-End Tests

- Full pipeline run
- Query API against real data
- Dagster schedule execution

## Extensibility

### Adding New Data Fields

1. Update `scraper.py` to extract new fields
2. Add transformation logic in `transformers.py`
3. Update schema in `sources.py` if needed
4. Queries automatically pick up new fields

### Adding New Queries

1. Add method to `EarningsCalendarReader`
2. Write SQL query using DuckDB
3. Optionally add convenience function

### Adding New Schedules

1. Create schedule in `schedules.py`
2. Define job in `definitions.py`
3. Add to `Definitions` object

### Supporting New Sources

1. Create new scraper class
2. Add dlt resource
3. Create Dagster asset
4. Reuse existing read API

## Performance Considerations

### Scraping

- Parallel requests for date ranges
- Rate limiting respect
- Playwright fallback (slower but reliable)

### Storage

- Parquet compression
- Columnar format for analytics
- Partition pruning

### Queries

- DuckDB predicate pushdown
- Partition filtering
- Index on common columns

## Security

### API Keys

- No API keys required for Nasdaq
- Configuration via environment variables
- No sensitive data in code

### Data Privacy

- Public earnings data only
- No PII collected
- GDPR not applicable

## Monitoring

### Dagster

- Asset materialization status
- Record counts
- Load time metrics
- Error tracking

### Logging

- Structured logging throughout
- Log levels: INFO, WARNING, ERROR
- Rich console output for CLI

## Future Enhancements

### Potential Additions

1. **More Sources**: Yahoo Finance, SEC Edgar
2. **Real-time Updates**: WebSocket connections
3. **Estimate Changes**: Track analyst revisions
4. **Alerting**: Notify on surprise earnings
5. **ML Features**: Predict earnings beats/misses
6. **Dashboard**: Streamlit/Gradio UI
7. **API Server**: FastAPI endpoints
8. **Cloud Storage**: S3, GCS support

### Scalability

Current design handles:
- ~10,000 earnings per month
- Daily updates
- 30-day rolling window

For larger scale:
- Add incremental updates
- Implement CDC patterns
- Use distributed compute (Spark/Ray)
- Add caching layer (Redis)
