# Earnings Calendar Guide

Complete guide to loading, storing, and querying earnings calendar data in `dlt-ibapi`.

## Table of Contents

- [Overview](#overview)
- [Data Source](#data-source)
- [Loading Earnings Data](#loading-earnings-data)
  - [CLI: Load from JSON](#cli-load-from-json)
  - [Python API: Load from JSON](#python-api-load-from-json)
- [Querying Earnings Data](#querying-earnings-data)
  - [CLI: List Earnings](#cli-list-earnings)
  - [Python API: EarningsCalendarReader](#python-api-earningscalendarreader)
  - [DuckDB: SQL Queries](#duckdb-sql-queries)
- [Integration with Backtesting](#integration-with-backtesting)
- [Data Schema](#data-schema)
- [Complete Workflows](#complete-workflows)
- [Troubleshooting](#troubleshooting)

---

## Overview

The earnings calendar dataset stores earnings announcement dates, times, and forecasts for stocks. This data is crucial for options trading strategies that:

- **Time trades around earnings** (e.g., pre-earnings calendar spreads)
- **Filter by IV behavior** (earnings announcements increase IV)
- **Avoid earnings risk** (exclude positions expiring near earnings)

**Key Features:**
- Load earnings from external sources (Nasdaq JSON files)
- Store as Parquet with efficient querying
- Query upcoming earnings, filter by symbol/time
- Integration with backtest validation system

**Dataset Location:** `./data/earnings/earnings_calendar/`

---

## Data Source

**IMPORTANT**: `dlt-ibapi` does NOT fetch earnings data automatically. You must obtain earnings data from external sources first, then load it using `dlt-ibapi`.

### How to Get Earnings Data

The most common source is **Nasdaq earnings calendar**. Here's how to obtain it:

#### Option 1: Manual Browser Method (Recommended for First Time)

1. **Navigate to Nasdaq Earnings Calendar**
   - URL: https://www.nasdaq.com/market-activity/earnings

2. **Open Browser DevTools**
   - Press `F12` or right-click → "Inspect"
   - Go to **Network** tab

3. **Refresh the Page**
   - Watch for XHR/Fetch requests
   - Look for a request to an API endpoint (usually contains "earnings" or "calendar")

4. **Find the JSON Response**
   - Click on the request
   - Go to **Response** tab
   - Copy the JSON data

5. **Save to File**
   - Create a file: `~/Desktop/earnings_2025-11-13.json`
   - Paste the JSON data
   - Save with today's date in filename for tracking

**Example filename pattern**: `earnings_YYYY-MM-DD.json`

#### Option 2: Automated Scraping (For Daily Ingestion)

Build a scraper using MCP tools or Python:

```python
# Example using mcp__agentql__extract-web-data (if available)
url = "https://www.nasdaq.com/market-activity/earnings"
data = extract_web_data(url, "earnings announcements for next 30 days")

# Or use Playwright MCP for more control
# See: mcp__playwright__browser_navigate, mcp__playwright__browser_snapshot
```

#### Option 3: Other Data Sources

Alternative sources for earnings calendars:
- **Yahoo Finance**: Earnings calendar with similar data
- **Financial APIs**: Alpha Vantage, Polygon.io, etc. (may require subscription)
- **Broker APIs**: Some brokers provide earnings calendars via API

### Understanding the Workflow

```
┌─────────────────────────────────────────┐
│ Step 1: Get Earnings Data              │
│ - Scrape Nasdaq website                │
│ - Save as JSON file                     │
│ - Example: earnings_2025-11-13.json    │
└─────────────────┬───────────────────────┘
                  │
┌─────────────────▼───────────────────────┐
│ Step 2: Load into dlt-ibapi            │
│ dlt-ibapi load-earnings earnings.json  │
│ - Parses JSON                           │
│ - Validates schema                      │
│ - Saves as Parquet files                │
└─────────────────┬───────────────────────┘
                  │
┌─────────────────▼───────────────────────┐
│ Step 3: Query the Data                 │
│ dlt-ibapi list-earnings                │
│ - or -                                  │
│ Python: EarningsCalendarReader         │
│ - or -                                  │
│ DuckDB: SELECT * FROM parquet_scan()   │
└─────────────────────────────────────────┘
```

### Why Not Automatic?

`dlt-ibapi` does not include automatic scraping because:
1. **Legal compliance** - scraping terms of service vary by site
2. **Stability** - website changes would break automatic scraping
3. **Flexibility** - you can use any data source you prefer
4. **Separation of concerns** - data acquisition vs data storage

### JSON File Format

Expected JSON structure (array of earnings events):

```json
[
  {
    "symbol": "AAPL",
    "companyName": "Apple Inc.",
    "earningsDate": "2025-11-15",
    "earningsTime": "AFTER_HOURS",
    "epsForecast": 1.52,
    "fiscalQuarter": "Q4 2025"
  },
  {
    "symbol": "MSFT",
    "companyName": "Microsoft Corporation",
    "earningsDate": "2025-11-16",
    "earningsTime": "PRE_MARKET",
    "epsForecast": 2.75,
    "fiscalQuarter": "Q1 2026"
  }
]
```

**Field Mapping:**
- `earningsTime`: "PRE_MARKET", "AFTER_HOURS", or "UNKNOWN"
- `epsForecast`: Expected EPS (can be `null`)
- All other fields are optional

---

## Loading Earnings Data

### Understanding Data Ingestion Strategy

**Key Insight**: When you ingest earnings data daily, you'll have overlapping data that needs proper deduplication.

**Example Scenario:**
- **Day 1 (Nov 13)**: Load earnings for next 7 days → Nov 13-20
- **Day 2 (Nov 14)**: Load earnings for next 7 days → Nov 14-21
- **Result**: Days 14-20 appear in both loads (overlap)
- **Problem**: Data might change (new forecasts, updated times)

**Solution**: Use **append mode with primary keys**

The DLT resource `load_earnings_from_json` has:
- **Primary key**: `["symbol", "earnings_date"]`
- **Write disposition**: `"replace"` (default) or `"append"` (recommended for daily use)
- **Tracking**: `loaded_at` timestamp shows when each row was ingested

**How it works:**
1. Load earnings today → Parquet files created
2. Load earnings tomorrow → DLT checks primary keys `(symbol, earnings_date)`
3. If key exists → **UPDATE** with new data (keeps latest `loaded_at`)
4. If key new → **INSERT** new row

**Recommendation**:
- **First load**: Use default (replace mode) or append
- **Daily updates**: Always use append mode (automatic deduplication)
- **No date filtering needed**: Just ingest everything from JSON

### CLI: Load from JSON

Load earnings from a JSON file into the Parquet dataset:

```bash
# Recommended: Simple load (no filtering, ingest everything)
dlt-ibapi load-earnings /path/to/earnings.json

# Result:
# - Saves to ./data/earnings/earnings_calendar/
# - Tracks loaded_at timestamp automatically
# - Deduplicates on (symbol, earnings_date)
# - Safe to run daily - will update existing entries
```

**Optional filters** (usually not needed):
```bash
# Filter by date range (if JSON has too much old data)
dlt-ibapi load-earnings earnings_2025-11-13.json \
  --start-date 2025-11-13 \
  --end-date 2025-12-31

# Filter by symbols (if you only trade certain stocks)
dlt-ibapi load-earnings earnings.json \
  --symbols AAPL MSFT GOOGL TSLA

# Use custom dataset name
dlt-ibapi load-earnings earnings.json \
  --dataset my_earnings \
  --pipeline-name custom_loader
```

**CLI Options:**
- `json_file` (required): Path to JSON file containing earnings
- `--start-date`: Filter minimum earnings date (YYYY-MM-DD)
- `--end-date`: Filter maximum earnings date (YYYY-MM-DD)
- `--symbols`: Filter specific symbols (space-separated)
- `--dataset`: Dataset name (default: "earnings")
- `--pipeline-name`: DLT pipeline name (default: "earnings_loader")
- `--data-dir`: Data directory (default: "./data")

**Output:**
```
📥 Loading Earnings Calendar

Source: /Users/mohamedali/Desktop/earnings_2025-11-13.json
Dataset: earnings
Pipeline: earnings_loader

✅ Loaded 245 earnings events
   Date range: 2025-11-13 to 2025-12-15
   Symbols: 245

💾 Saved to ./data/earnings/earnings_calendar/
```

---

### Python API: Load from JSON

Use the DLT resources directly for programmatic loading:

#### Simple Load (Replace Mode)

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

# Load earnings (replaces existing data)
data = load_earnings_from_json(
    json_file="/path/to/earnings.json",
    start_date=date(2025, 11, 1),
    end_date=date(2025, 12, 31),
    symbols=["AAPL", "MSFT", "GOOGL"],
)

# Run pipeline
info = pipeline.run(data, write_disposition="replace", loader_file_format="parquet")
print(f"Loaded {info.metrics['rows']} earnings events")
```

#### Snapshot Loading (Append Mode)

Track historical snapshots of earnings calendars over time:

```python
from dlt_ibapi import load_earnings_snapshot

# Load with snapshot tracking
snapshot_data = load_earnings_snapshot(
    json_file="/path/to/earnings_2025-11-13.json",
    snapshot_date=date(2025, 11, 13),  # When this data was captured
    start_date=date(2025, 11, 13),
    end_date=date(2026, 2, 28),
)

# Append to dataset (preserves historical snapshots)
info = pipeline.run(snapshot_data, write_disposition="append", loader_file_format="parquet")
```

**Use Case for Snapshots:**
- Track how earnings forecasts change over time
- Analyze forecast accuracy
- Historical analysis: "What was expected on Nov 1 vs Nov 15?"

**Primary Key Difference:**
- `load_earnings_from_json`: `[symbol, earnings_date]` (current earnings only)
- `load_earnings_snapshot`: `[symbol, earnings_date, snapshot_date]` (historical tracking)

---

## Querying Earnings Data

### CLI: List Earnings

Query stored earnings using the CLI:

```bash
# List upcoming earnings (next 7 days by default)
dlt-ibapi list-earnings

# List earnings for next 30 days
dlt-ibapi list-earnings --days-ahead 30

# Filter by symbols
dlt-ibapi list-earnings --symbols AAPL MSFT GOOGL

# Filter by earnings time
dlt-ibapi list-earnings --time PRE_MARKET
dlt-ibapi list-earnings --time AFTER_HOURS

# Combined filters
dlt-ibapi list-earnings \
  --days-ahead 14 \
  --symbols AAPL MSFT \
  --time AFTER_HOURS

# Use custom dataset
dlt-ibapi list-earnings --dataset my_earnings --data-dir ./data
```

**Output Example:**
```
📅 Upcoming Earnings (Next 7 Days)

┏━━━━━━━━┳━━━━━━━━━━━━━━┳━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃ Symbol ┃ Date         ┃ Time        ┃ Company                 ┃
┡━━━━━━━━╇━━━━━━━━━━━━━━╇━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━┩
│ AAPL   │ 2025-11-15   │ AFTER_HOURS │ Apple Inc.              │
│ MSFT   │ 2025-11-16   │ PRE_MARKET  │ Microsoft Corporation   │
│ GOOGL  │ 2025-11-18   │ AFTER_HOURS │ Alphabet Inc.           │
└────────┴──────────────┴─────────────┴─────────────────────────┘

Total: 3 earnings announcements
```

---

### Python API: EarningsCalendarReader

Use the reader repository for type-safe queries:

```python
from dlt_ibapi.repositories import EarningsCalendarReader
from datetime import date

# Initialize reader
reader = EarningsCalendarReader(
    database_path="./data",
    dataset_name="earnings"
)

# Get upcoming earnings
upcoming = reader.get_upcoming_earnings(
    days_ahead=30,
    from_date=date.today(),
    symbols=["AAPL", "MSFT", "GOOGL"],
    earnings_time="AFTER_HOURS"  # Optional filter
)

print(upcoming[['symbol', 'earnings_date', 'earnings_time', 'company_name']])
```

#### Available Reader Methods

**1. Get Upcoming Earnings**

```python
upcoming = reader.get_upcoming_earnings(
    days_ahead=7,                    # Next N days
    from_date=date(2025, 11, 13),   # Optional start date (default: today)
    symbols=["AAPL", "MSFT"],       # Optional symbol filter
    earnings_time="PRE_MARKET"      # Optional time filter
)
# Returns: DataFrame with upcoming earnings
```

**2. Get Earnings for Symbol**

```python
aapl_earnings = reader.get_earnings_for_symbol(
    symbol="AAPL",
    start_date=date(2025, 1, 1),    # Optional
    end_date=date(2025, 12, 31)     # Optional
)
# Returns: DataFrame with all AAPL earnings in date range
```

**3. Get Earnings on Specific Date**

```python
earnings_on_date = reader.get_earnings_on_date(
    earnings_date=date(2025, 11, 15),
    symbols=["AAPL", "MSFT"]        # Optional
)
# Returns: DataFrame with all earnings on Nov 15, 2025
```

**4. Get Available Symbols**

```python
symbols = reader.get_available_symbols()
# Returns: List of symbols with earnings data
print(f"Earnings data for {len(symbols)} symbols")
```

**5. Get Date Range**

```python
min_date, max_date = reader.get_date_range()
# Returns: (earliest_date, latest_date) tuple
print(f"Earnings data from {min_date} to {max_date}")
```

**6. Count Earnings**

```python
total = reader.count_earnings()
nov_count = reader.count_earnings(
    start_date=date(2025, 11, 1),
    end_date=date(2025, 11, 30)
)
print(f"Total earnings: {total}")
print(f"November 2025: {nov_count}")
```

---

### DuckDB: SQL Queries

Query earnings data directly using SQL:

```python
import duckdb

conn = duckdb.connect(":memory:")

# Query upcoming earnings
result = conn.execute("""
    SELECT
        symbol,
        earnings_date,
        earnings_time,
        company_name,
        eps_forecast,
        fiscal_quarter
    FROM parquet_scan('./data/earnings/earnings_calendar/**/*.parquet', hive_partitioning=true)
    WHERE earnings_date >= CURRENT_DATE
      AND earnings_date <= CURRENT_DATE + INTERVAL '30 days'
    ORDER BY earnings_date, symbol
""").df()

print(result)
```

**Useful SQL Queries:**

```sql
-- Count earnings by time of day
SELECT
    earnings_time,
    COUNT(*) as count
FROM parquet_scan('./data/earnings/earnings_calendar/**/*.parquet', hive_partitioning=true)
WHERE earnings_date >= CURRENT_DATE
GROUP BY earnings_time
ORDER BY count DESC;

-- Symbols with most frequent earnings
SELECT
    symbol,
    company_name,
    COUNT(*) as earnings_count
FROM parquet_scan('./data/earnings/earnings_calendar/**/*.parquet', hive_partitioning=true)
GROUP BY symbol, company_name
ORDER BY earnings_count DESC
LIMIT 10;

-- Check for earnings conflicts (same day)
SELECT
    earnings_date,
    COUNT(*) as companies_reporting
FROM parquet_scan('./data/earnings/earnings_calendar/**/*.parquet', hive_partitioning=true)
WHERE earnings_date >= CURRENT_DATE
GROUP BY earnings_date
HAVING COUNT(*) > 10
ORDER BY companies_reporting DESC;
```

---

## Integration with Backtesting

Earnings data integrates with the options backtesting framework via `EarningsCalendarProvider`.

### Using Earnings in Backtests

```python
from datetime import date
from dlt_ibapi.backtest import (
    IBBacktestDataProvider,
    EarningsCalendarProvider,
    OptionsBacktestRunner,
)
from tools.strategies.options import PreEarningsCalendarSpreadStrategy, PreEarningsConfig

# Initialize data providers
data_provider = IBBacktestDataProvider("./data")
earnings_provider = EarningsCalendarProvider(
    database_path="./data",
    dataset_name="earnings"
)

# Configure pre-earnings strategy
config = PreEarningsConfig(
    underlying_symbols=["AAPL", "MSFT", "GOOGL"],
    entry_window=(10, 25),      # Enter 10-25 days before earnings
    exit_buffer=2,              # Exit 2 days before earnings
    iv_contango_min=0.05,
    profit_target=0.30,
)

strategy = PreEarningsCalendarSpreadStrategy(config)

# Run backtest with earnings integration
runner = OptionsBacktestRunner(
    strategy=strategy,
    data_provider=data_provider,
    earnings_calendar_provider=earnings_provider,  # Earnings provider
    initial_capital=100000,
)

result = runner.run(
    start_date=date(2024, 1, 1),
    end_date=date(2024, 12, 31),
    validate_data=True,
)

print(f"Total Return: {result.total_return_pct:.2f}%")
print(f"Trades: {result.num_trades}")
```

### CLI Backtest with Earnings

```bash
# Run pre-earnings spread backtest
dlt-ibapi backtest-earnings-spreads \
    --strategy pre_earnings \
    --symbols AAPL MSFT GOOGL \
    --start-date 2024-01-01 \
    --end-date 2024-12-31 \
    --capital 100000 \
    --data-path ./data \
    --earnings-dataset earnings
```

**How It Works:**
1. Strategy queries earnings calendar via `EarningsCalendarProvider`
2. Finds upcoming earnings for specified symbols
3. Times trades around earnings announcements
4. Automatically exits positions before earnings (risk management)

---

## Data Schema

### Earnings Calendar Table

**Table Name:** `earnings_calendar`

**Columns:**

| Column | Type | Description |
|--------|------|-------------|
| `symbol` | `text` | Stock symbol (e.g., "AAPL") |
| `earnings_date` | `date` | Earnings announcement date |
| `earnings_time` | `text` | "PRE_MARKET", "AFTER_HOURS", or "UNKNOWN" |
| `company_name` | `text` | Full company name |
| `eps_forecast` | `double` | Expected EPS (can be null) |
| `fiscal_quarter` | `text` | Fiscal quarter (e.g., "Q4 2025") |
| `loaded_at` | `timestamp` | When data was loaded into dataset |

**Primary Key:**
- **Simple load**: `[symbol, earnings_date]`
- **Snapshot load**: `[symbol, earnings_date, snapshot_date]`

**Indexes (via Hive Partitioning):**
- Can optionally partition by `earnings_date` for large datasets

---

## Complete Workflows

### Workflow 1: Initial Earnings Load

```bash
# 1. Obtain earnings data from Nasdaq
# (Manual: Save JSON from https://www.nasdaq.com/market-activity/earnings)

# 2. Load into dataset
dlt-ibapi load-earnings ~/Desktop/earnings_2025-11-13.json

# 3. Verify data loaded
dlt-ibapi stats ./data --dataset earnings

# 4. List upcoming earnings
dlt-ibapi list-earnings --days-ahead 30
```

### Workflow 2: Filter and Load Specific Symbols

```bash
# Load only tech stocks for next quarter
dlt-ibapi load-earnings earnings.json \
  --symbols AAPL MSFT GOOGL AMZN META NVDA \
  --start-date 2025-11-01 \
  --end-date 2026-01-31 \
  --dataset tech_earnings
```

### Workflow 3: Python Integration

```python
import dlt
from datetime import date
from dlt_ibapi import load_earnings_from_json
from dlt_ibapi.repositories import EarningsCalendarReader

# Step 1: Load earnings data
pipeline = dlt.pipeline(
    pipeline_name="earnings",
    destination=dlt.destinations.filesystem(bucket_url="./data"),
    dataset_name="earnings",
)

data = load_earnings_from_json(
    json_file="earnings_2025-11-13.json",
    start_date=date(2025, 11, 13),
    end_date=date(2026, 2, 28),
)

info = pipeline.run(data, write_disposition="replace", loader_file_format="parquet")
print(f"✅ Loaded {info.metrics.get('rows', 0)} earnings events")

# Step 2: Query earnings data
reader = EarningsCalendarReader("./data", "earnings")

# Find AAPL earnings
aapl = reader.get_earnings_for_symbol("AAPL")
print(f"AAPL earnings dates: {aapl['earnings_date'].tolist()}")

# Check upcoming earnings (next 7 days)
upcoming = reader.get_upcoming_earnings(days_ahead=7)
print(f"Upcoming: {len(upcoming)} earnings announcements")

# Step 3: Use in backtest
from dlt_ibapi.backtest import EarningsCalendarProvider

earnings_provider = EarningsCalendarProvider("./data", "earnings")
upcoming_backtest = earnings_provider.get_upcoming_earnings(
    days_ahead=14,
    timestamp=date(2025, 11, 13),
    symbols=["AAPL", "MSFT"],
)
print(f"Backtest found {len(upcoming_backtest)} relevant earnings")
```

### Workflow 4: Historical Snapshot Tracking

```python
from datetime import date
from dlt_ibapi import load_earnings_snapshot

# Load multiple historical snapshots
snapshots = [
    ("earnings_2025-11-01.json", date(2025, 11, 1)),
    ("earnings_2025-11-08.json", date(2025, 11, 8)),
    ("earnings_2025-11-15.json", date(2025, 11, 15)),
]

pipeline = dlt.pipeline(
    pipeline_name="earnings_history",
    destination=dlt.destinations.filesystem(bucket_url="./data"),
    dataset_name="earnings_snapshots",
)

for json_file, snapshot_date in snapshots:
    data = load_earnings_snapshot(
        json_file=json_file,
        snapshot_date=snapshot_date,
    )

    info = pipeline.run(data, write_disposition="append", loader_file_format="parquet")
    print(f"Loaded snapshot from {snapshot_date}: {info.metrics.get('rows', 0)} events")

# Now you can query: "How did AAPL forecast change from Nov 1 to Nov 15?"
```

---

## Troubleshooting

### Error: "No module named 'dlt_ibapi.earnings'"

**Cause:** Old version of dlt-ibapi without earnings support.

**Solution:** Update to latest version:
```bash
cd /path/to/dlt-ibapi
uv sync
```

### Error: "FileNotFoundError: earnings.json not found"

**Cause:** Invalid path to JSON file.

**Solution:** Use absolute path or verify file exists:
```bash
ls -la /path/to/earnings.json
dlt-ibapi load-earnings /absolute/path/to/earnings.json
```

### Error: "No data loaded" or "0 rows"

**Cause:** Filters are too restrictive or JSON format is incorrect.

**Solution:**
1. Check JSON format matches expected schema
2. Remove filters to test: `dlt-ibapi load-earnings earnings.json`
3. Verify date filters: dates should be in `YYYY-MM-DD` format

### Warning: "EarningsCalendarReader: No data found"

**Cause:** Dataset doesn't exist or is empty.

**Solution:**
```bash
# 1. Verify dataset exists
ls -la ./data/earnings/

# 2. Check if any data loaded
dlt-ibapi stats ./data --dataset earnings

# 3. Reload earnings data
dlt-ibapi load-earnings earnings.json
```

### Performance: Queries are slow

**Cause:** Large dataset without Hive partitioning.

**Solution:** Enable Hive partitioning for large datasets (see API docs for column hints).

### Data Quality: Missing or incorrect earnings

**Cause:** Source data (Nasdaq JSON) may be incomplete.

**Solution:**
- Verify source data quality before loading
- Cross-reference with multiple sources
- Use snapshot tracking to monitor changes over time

---

## Best Practices

1. **Regular Updates**: Load earnings data weekly to capture new announcements
2. **Version Control**: Save JSON files with dates (e.g., `earnings_2025-11-13.json`)
3. **Validation**: Always run `list-earnings` after loading to verify data
4. **Snapshot Tracking**: Use snapshot mode for production backtests to ensure data integrity
5. **Symbol Filtering**: Load only symbols you trade to keep dataset small
6. **Date Filtering**: Load 2-3 months ahead (most earnings strategies use 30-60 day windows)

---

## Summary

**Loading Data:**
- CLI: `dlt-ibapi load-earnings earnings.json`
- Python: `load_earnings_from_json()` or `load_earnings_snapshot()`

**Querying Data:**
- CLI: `dlt-ibapi list-earnings --days-ahead 30`
- Python: `EarningsCalendarReader.get_upcoming_earnings()`
- SQL: DuckDB with `parquet_scan()`

**Integration:**
- Backtests: `EarningsCalendarProvider` for strategy timing
- Validation: Pre-flight checks ensure earnings data coverage

**Next Steps:**
- Load your first earnings dataset: `dlt-ibapi load-earnings`
- Explore data: `dlt-ibapi list-earnings`
- Run earnings backtest: `dlt-ibapi backtest-earnings-spreads --help`

For more information:
- [README.md](../README.md) - Project overview
- [BACKTEST_QUICKSTART.md](BACKTEST_QUICKSTART.md) - Backtesting guide
- [API_REFERENCE.md](API_REFERENCE.md) - Complete API documentation
