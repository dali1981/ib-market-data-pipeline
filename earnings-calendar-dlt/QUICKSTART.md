# Quick Start Guide

Get up and running with earnings-calendar-dlt in 5 minutes.

## Installation

```bash
cd earnings-calendar-dlt
uv sync
uv run playwright install chromium
```

## 1. Test the Scraper (30 seconds)

```python
from earnings_calendar import fetch_earnings_calendar

# Fetch upcoming earnings
earnings = fetch_earnings_calendar(days_ahead=7)
print(f"Found {len(earnings)} earnings announcements")
print(earnings[0])  # Show first record
```

Or run the example:

```bash
uv run python examples/standalone_scraper.py
```

## 2. Run the Pipeline (2 minutes)

```python
from earnings_calendar import run_pipeline

# Run pipeline to store data
load_info = run_pipeline(days_ahead=30)
print("Pipeline complete!")
```

Or run the example:

```bash
uv run python examples/run_pipeline.py
```

## 3. Query the Data (1 minute)

```python
from earnings_calendar import get_upcoming_earnings

# Get earnings for next 7 days
upcoming = get_upcoming_earnings(days_ahead=7)

for record in upcoming:
    print(f"{record['symbol']}: {record['earnings_date']}")
```

Or run the example:

```bash
uv run python examples/query_data.py
```

## 4. Start Dagster (1 minute)

```bash
uv run dagster dev -m dagster_earnings
```

Open http://localhost:3000 and click "Materialize" on the earnings calendar asset.

## Common Queries

### Get earnings for specific stocks

```python
from earnings_calendar import get_upcoming_earnings

tech_earnings = get_upcoming_earnings(
    days_ahead=30,
    symbols=["AAPL", "GOOGL", "MSFT", "AMZN"]
)
```

### Get earnings history for a ticker

```python
from earnings_calendar import get_earnings_by_ticker

aapl_history = get_earnings_by_ticker("AAPL", limit=10)
```

### Find earnings surprises

```python
from earnings_calendar import EarningsCalendarReader

reader = EarningsCalendarReader()
surprises = reader.get_earnings_with_surprises(
    min_surprise_pct=5.0,  # At least 5% surprise
    limit=20
)
```

### Get earnings on a specific date

```python
from earnings_calendar import get_earnings_by_date

today = "2025-10-22"
today_earnings = get_earnings_by_date(today)
```

## Configuration

### Environment Variables

```bash
# Scraper config
export EARNINGS_DAYS_AHEAD=30
export EARNINGS_PLAYWRIGHT_FALLBACK=true
export EARNINGS_TIMEOUT=30

# Storage config
export EARNINGS_DESTINATION=filesystem
export EARNINGS_DATASET_NAME=nasdaq_earnings
```

### Config File

Create `.earnings-calendar/config.yaml`:

```yaml
scraper:
  days_ahead: 30
  use_playwright_fallback: true
  timeout: 30

dlt:
  destination: filesystem
  dataset_name: nasdaq_earnings
  write_disposition: replace
```

## Troubleshooting

### Playwright not installed

```bash
uv run playwright install chromium
```

### Data path not found

```bash
mkdir -p ./data/nasdaq_earnings/earnings_calendar
```

### API rate limiting

Reduce days_ahead or enable Playwright fallback:

```python
from earnings_calendar import NasdaqEarningsScraper

scraper = NasdaqEarningsScraper(
    days_ahead=7,  # Fetch less data
    use_playwright_fallback=True
)
```

## Next Steps

- Read [README.md](README.md) for complete documentation
- Check [ARCHITECTURE.md](ARCHITECTURE.md) for design details
- See [examples/](examples/) for more code examples
- View [tests/](tests/) for testing patterns

## Integration with dlt-ibapi

Combine earnings calendar with market data:

```python
import dlt
from earnings_calendar import nasdaq_earnings_source
from dlt_ibapi import ib_source

pipeline = dlt.pipeline(
    pipeline_name="trading_data",
    destination="filesystem",
    dataset_name="trading"
)

# Load earnings calendar
pipeline.run(nasdaq_earnings_source(days_ahead=30))

# Load market data for stocks with upcoming earnings
from earnings_calendar import get_upcoming_earnings

upcoming = get_upcoming_earnings(days_ahead=7)
symbols = [r["symbol"] for r in upcoming]

pipeline.run(ib_source(symbols=symbols[:10]))  # First 10
```

Now query both datasets together:

```python
from earnings_calendar import EarningsCalendarReader
from dlt_ibapi import EquityBarsReader

earnings_reader = EarningsCalendarReader()
bars_reader = EquityBarsReader()

# Get stocks with earnings today
today_earnings = earnings_reader.get_earnings_by_date("2025-10-22")

# Get price history for those stocks
for record in today_earnings:
    symbol = record["symbol"]
    bars = bars_reader.get_bars(
        symbol=symbol,
        start_date="2025-10-01",
        end_date="2025-10-22"
    )
    print(f"{symbol}: {len(bars)} bars before earnings")
```
