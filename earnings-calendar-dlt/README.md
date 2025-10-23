# Earnings Calendar DLT

A modular earnings calendar scraper with dlt and Dagster integration for maintaining a dataset of earnings announcements from Nasdaq.

## Features

- **Standalone Scraper**: Use the scraper independently without dlt or Dagster
- **DLT Integration**: Efficient data pipeline with Parquet storage
- **Dagster Orchestration**: Daily scheduled jobs with monitoring
- **Clean Read API**: Query earnings data using DuckDB-powered API
- **Daily Snapshots**: Store complete state each day for historical analysis
- **Modular Design**: Each component can be used independently

## Installation

```bash
cd earnings-calendar-dlt
uv sync
```

Install Playwright browsers (required for web scraping):

```bash
uv run playwright install chromium
```

## Quick Start

### 1. Standalone Scraper

Use the scraper without dlt or Dagster:

```python
from earnings_calendar import fetch_earnings_calendar

# Fetch next 30 days of earnings
earnings = fetch_earnings_calendar(days_ahead=30)

for record in earnings:
    print(f"{record['symbol']}: {record['earnings_date']} - {record['company_name']}")
```

### 2. DLT Pipeline

Run the dlt pipeline to store data in Parquet format:

```python
from earnings_calendar import run_pipeline

# Run pipeline and store in filesystem (Parquet)
load_info = run_pipeline(
    days_ahead=30,
    destination="filesystem",
    dataset_name="nasdaq_earnings"
)

print(f"Loaded {load_info} records")
```

### 3. Query Stored Data

Use the read API to query Parquet data:

```python
from earnings_calendar import EarningsCalendarReader

reader = EarningsCalendarReader(
    data_path="./data/nasdaq_earnings/earnings_calendar"
)

# Get upcoming earnings for next 7 days
upcoming = reader.get_upcoming_earnings(days_ahead=7)

# Get all earnings for a specific ticker
aapl_earnings = reader.get_earnings_by_ticker("AAPL")

# Get earnings on a specific date
today_earnings = reader.get_earnings_by_date("2025-10-22")

# Get summary statistics
stats = reader.get_earnings_stats()
print(f"Total records: {stats['total_records']}")
print(f"Unique symbols: {stats['unique_symbols']}")
```

### 4. Dagster Orchestration

Run the Dagster webserver:

```bash
cd earnings-calendar-dlt
uv run dagster dev -m dagster_earnings
```

Then navigate to http://localhost:3000 to:
- View the earnings calendar assets
- Materialize assets on-demand
- Monitor daily scheduled runs
- View asset metadata and lineage

## Architecture

### Project Structure

```
earnings-calendar-dlt/
├── src/earnings_calendar/       # Core library
│   ├── scraper.py               # Nasdaq scraper (API + Playwright)
│   ├── config.py                # Pydantic configuration models
│   ├── transformers.py          # Data normalization
│   ├── sources.py               # dlt resources and sources
│   └── api.py                   # ParquetReader query API
├── dagster_earnings/            # Dagster integration
│   ├── assets.py                # @dlt_assets definitions
│   ├── schedules.py             # Daily schedules
│   └── definitions.py           # Dagster Definitions
├── tests/                       # Tests
│   └── unit/                    # Unit tests
│       ├── calendar/            # Calendar library tests
│       └── dagster/             # Dagster integration tests
└── pyproject.toml               # Dependencies
```

### Data Flow

```
Nasdaq API/Web → Scraper → Transformer → dlt Resource → Parquet Files → Query API
                                                              ↓
                                                         Dagster Assets
                                                              ↓
                                                      Scheduled Daily Runs
```

## Configuration

### Environment Variables

```bash
# Scraper configuration
export EARNINGS_DAYS_AHEAD=30
export EARNINGS_PLAYWRIGHT_FALLBACK=true
export EARNINGS_TIMEOUT=30

# DLT configuration
export EARNINGS_DESTINATION=filesystem
export EARNINGS_DATASET_NAME=nasdaq_earnings
export EARNINGS_BUCKET_URL=file://./data
```

### YAML Configuration

Create `.earnings-calendar/config.yaml`:

```yaml
scraper:
  days_ahead: 30
  use_playwright_fallback: true
  timeout: 30

dlt:
  destination: filesystem
  dataset_name: nasdaq_earnings
  bucket_url: file://./data
  write_disposition: replace
```

Load in code:

```python
from earnings_calendar.config import EarningsCalendarConfig

config = EarningsCalendarConfig.from_yaml(".earnings-calendar/config.yaml")
```

## Data Schema

Each earnings record contains:

| Field | Type | Description |
|-------|------|-------------|
| `symbol` | string | Stock ticker symbol |
| `company_name` | string | Company name |
| `earnings_date` | date | Earnings announcement date |
| `earnings_time` | string | Time of announcement (BMO, AMC, TAS) |
| `fiscal_quarter` | string | Fiscal quarter ending |
| `eps_forecast` | float | Consensus EPS estimate |
| `eps_actual` | float | Actual reported EPS |
| `eps_surprise` | float | EPS surprise (actual - forecast) |
| `eps_surprise_pct` | float | EPS surprise percentage |
| `revenue_forecast` | float | Revenue estimate |
| `revenue_actual` | float | Actual revenue |
| `market_cap` | float | Market capitalization |
| `num_estimates` | int | Number of analyst estimates |
| `snapshot_date` | date | Date when data was captured |
| `scraped_at` | timestamp | Timestamp of scraping |

## Daily Snapshots

The pipeline uses a **replace** write disposition to create daily snapshots. This approach:

- Captures the complete state of the earnings calendar each day
- Enables historical analysis of estimate changes
- Simplifies data management (no deduplication needed)
- Each snapshot is partitioned by `snapshot_date`

## API Examples

### Get Upcoming Earnings

```python
from earnings_calendar import get_upcoming_earnings

# Get earnings for next 7 days
upcoming = get_upcoming_earnings(days_ahead=7)

# Filter by specific symbols
tech_earnings = get_upcoming_earnings(
    days_ahead=30,
    symbols=["AAPL", "GOOGL", "MSFT"]
)
```

### Analyze Earnings Surprises

```python
from earnings_calendar import EarningsCalendarReader

reader = EarningsCalendarReader()

# Get earnings with significant surprises
surprises = reader.get_earnings_with_surprises(
    min_surprise_pct=5.0,  # At least 5% surprise
    limit=100
)

for record in surprises:
    print(f"{record['symbol']}: {record['eps_surprise_pct']:.2f}% surprise")
```

### Date Range Queries

```python
# Get all earnings in a date range
earnings = reader.get_earnings_in_range(
    start_date="2025-10-01",
    end_date="2025-10-31",
    symbols=["AAPL", "GOOGL"]  # Optional filter
)
```

## Dagster Integration Details

### Asset Definitions

Two approaches provided:

1. **@dlt_assets decorator** (Recommended):
   - Automatic asset creation from dlt source
   - Built-in metadata tracking
   - Simpler setup

2. **Custom asset**:
   - More control over execution
   - Custom metadata handling
   - Flexible error handling

### Schedules

Three schedule options:

1. **daily_earnings_calendar_schedule**: Runs every day at 6 AM
2. **weekday_earnings_calendar_schedule**: Runs Monday-Friday only
3. **daily_earnings_calendar_custom_schedule**: Custom schedule with dynamic config

Choose the schedule that fits your needs or create a custom one.

## Development

### Run Tests

```bash
# Run all tests
uv run pytest tests/

# Run only unit tests
uv run pytest tests/unit/

# Run calendar library tests
uv run pytest tests/unit/calendar/

# Run Dagster integration tests
uv run pytest tests/unit/dagster/
```

### Lint and Format

```bash
uv run ruff check src/
uv run ruff format src/
```

### Run Scraper Locally

```bash
uv run python -c "from earnings_calendar import fetch_earnings_calendar; print(fetch_earnings_calendar(days_ahead=7))"
```

### Run DLT Pipeline Locally

```bash
uv run python -c "from earnings_calendar import run_pipeline; run_pipeline(days_ahead=7)"
```

## Integration with dlt-ibapi

This library follows the same patterns as `dlt-ibapi`:

- Pydantic configuration models
- ParquetReader-based query API
- Filesystem destination with Parquet storage
- Modular, testable components

You can use both libraries together in a unified data platform:

```python
# Combined pipeline
from earnings_calendar import nasdaq_earnings_source
from dlt_ibapi import ib_source

import dlt

pipeline = dlt.pipeline(
    pipeline_name="trading_data",
    destination="filesystem",
    dataset_name="trading"
)

# Load earnings calendar
pipeline.run(nasdaq_earnings_source())

# Load market data
pipeline.run(ib_source(symbols=["AAPL", "GOOGL"]))
```

## Troubleshooting

### Playwright Installation Issues

If Playwright fails to install browsers:

```bash
uv run playwright install --help
uv run playwright install chromium --force
```

### API Rate Limiting

If you encounter rate limiting from Nasdaq:

- Reduce `days_ahead` to fetch fewer days
- Add delays between requests
- Use Playwright fallback (slower but more reliable)

### Data Path Issues

Ensure data directory exists:

```bash
mkdir -p ./data/nasdaq_earnings/earnings_calendar
```

## License

MIT

## Contributing

Contributions welcome! Please open an issue or PR.
