# Nasdaq Earnings Calendar Scraper - Ollama Vision

This scraper uses Playwright + Ollama's vision model to extract earnings data from Nasdaq's earnings calendar page.

## Prerequisites

1. **Ollama installed and running**
   ```bash
   # Install Ollama from https://ollama.ai
   # Pull the vision model
   ollama pull llama3.2-vision:11b
   ```

2. **Python dependencies**
   ```bash
   uv sync
   ```

## Usage

### Basic Usage (Both Methods, All Pages)
```bash
uv run python scrape_earnings_playwright.py
```

### Method A Only (Full Table Screenshots)
```bash
uv run python scrape_earnings_playwright.py --method full
```

### Method B Only (Individual Row Screenshots)
```bash
uv run python scrape_earnings_playwright.py --method rows
```

### Specific Date
```bash
uv run python scrape_earnings_playwright.py --date 2025-10-23
```

### Show Browser Window (Debug)
```bash
uv run python scrape_earnings_playwright.py --no-headless
```

### CSV Output Only
```bash
uv run python scrape_earnings_playwright.py --output csv
```

### Quick Test (Single Page)
```bash
uv run python test_ollama_scraper.py
```

## Comparison: Method A vs Method B

### Method A: Full Table Screenshot
- **Pro**: Faster (1 screenshot per page)
- **Pro**: Preserves table context for LLM
- **Con**: LLM might misalign columns
- **Speed**: ~14 screenshots for full calendar

### Method B: Individual Row Screenshots
- **Pro**: More accurate per-row extraction
- **Pro**: Better isolation of data
- **Con**: Slower (10 screenshots per page)
- **Speed**: ~140 screenshots for full calendar

## Expected Output

For all 14 pages (131 total records):
- `earnings_method_a_full_table_TIMESTAMP.json` - Method A results
- `earnings_method_b_rows_TIMESTAMP.json` - Method B results
- `earnings_comparison_TIMESTAMP.json` - Comparison metadata
- Optional CSV files if `--output csv` or `--output both`

## Data Fields Extracted

Each record contains:
1. `date` - Earnings date (YYYY-MM-DD)
2. `time` - "Pre-Market", "After Hours", or "Time Not Supplied"
3. `symbol` - Stock ticker (e.g., TSLA)
4. `company_name` - Full company name
5. `market_cap` - Market capitalization
6. `fiscal_quarter_ending` - Fiscal quarter (e.g., Sep/2025)
7. `consensus_eps_forecast` - EPS forecast
8. `num_estimates` - Number of analyst estimates
9. `last_year_report_date` - Previous year's report date
10. `last_year_eps` - Previous year's EPS
11. `scraped_at` - Timestamp of extraction

## Icon Detection

The scraper identifies earnings time by analyzing icons in the Time column:
- **Sun icon** (orange/yellow) → "Pre-Market"
- **Moon icon** (blue/dark) → "After Hours"
- **No icon or unclear** → "Time Not Supplied"

## Troubleshooting

### "Ollama connection error"
- Make sure Ollama is running: `ollama list`
- Verify model is installed: `ollama list | grep llama3.2-vision`

### "No records extracted"
- Check screenshots in `/tmp/nasdaq_*.png` to verify table is visible
- Try with `--no-headless` to see if table renders
- Increase wait time on line 74 of scraper if table loads slowly

### "JSON parse error from Ollama"
- The vision model may have returned malformed JSON
- Check `/tmp/` screenshots to verify image quality
- Try Method B (row-by-row) for more reliable extraction

## Performance

- **Method A**: ~3-5 minutes for all 14 pages (with llama3.2-vision:11b)
- **Method B**: ~15-20 minutes for all 14 pages
- **Headless vs Visible**: Headless is slightly faster

## Validation

After scraping, validate results:
```bash
# Check record count
cat earnings_method_a_*.json | jq 'length'  # Should be ~131

# Check comparison
cat earnings_comparison_*.json | jq '.'
```
