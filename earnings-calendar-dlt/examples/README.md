# Examples

This directory contains example scripts demonstrating different ways to use the earnings calendar library.

## Running Examples

All examples should be run from the project root:

```bash
cd earnings-calendar-dlt
```

## 1. Standalone Scraper

Use the scraper without dlt or Dagster:

```bash
uv run python examples/standalone_scraper.py
```

This example shows:
- Fetching earnings data directly from Nasdaq
- Using the scraper as a standalone library
- Displaying results in a formatted table

## 2. Run DLT Pipeline

Run the complete dlt pipeline to store data:

```bash
uv run python examples/run_pipeline.py
```

This example shows:
- Running the dlt pipeline
- Storing data in Parquet format
- Viewing pipeline execution results

## 3. Query Data

Query stored data using the read API:

```bash
uv run python examples/query_data.py
```

This example shows:
- Querying upcoming earnings
- Getting earnings history for a ticker
- Finding earnings surprises
- Viewing dataset statistics

## 4. Dagster Webserver

Run the Dagster webserver to view assets:

```bash
uv run dagster dev -m dagster_earnings
```

Then open http://localhost:3000 to:
- View asset definitions
- Materialize assets manually
- Monitor scheduled runs
- View asset lineage

## Notes

### First Run

On first run, you may need to:

1. Install Playwright browsers:
   ```bash
   uv run playwright install chromium
   ```

2. Create data directory:
   ```bash
   mkdir -p data/nasdaq_earnings/earnings_calendar
   ```

### Data Path

Examples expect data to be stored in:
```
./data/nasdaq_earnings/earnings_calendar/
```

You can customize this by setting environment variables:
```bash
export EARNINGS_BUCKET_URL=file://./my-data
```

### API Rate Limiting

If you encounter rate limiting:
- Reduce `days_ahead` parameter
- Enable `use_playwright_fallback=True`
- Add delays between runs
