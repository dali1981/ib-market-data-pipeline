# Earnings-Based Snapshot Workflow

Complete workflow for capturing option chain snapshots for earnings events.

## Prerequisites

- IB Gateway or TWS running and connected
- Earnings data in JSON format (from Nasdaq or similar source)
- `dlt-ibapi` installed and configured

## Step-by-Step Workflow

### Step 1: Load Earnings Calendar

Load earnings data from JSON file into the earnings dataset:

```bash
mohamedali$ dlt-ibapi load-earnings ./earnings_raw/earnings_2025-11-13_v2.json
```

**What this does:**
- Parses earnings JSON file
- Normalizes symbols (uppercase, removes special characters)
- Loads data into `./data/earnings/` Parquet files
- Uses `replace` write disposition (overwrites existing data)

**Output:**
- Earnings events stored in `./data/earnings/earnings_calendar/*.parquet`
- Primary key: `[symbol, earnings_date]`

**Verify loaded data:**
```bash
mohamedali$ dlt-ibapi list-earnings --days-ahead 30
```

---

### Step 2: Resolve Contracts (Pre-populate Cache)

**Critical step**: Validate symbols and resolve to IB Contract objects before snapshot.

```bash
mohamedali$ dlt-ibapi resolve-contracts --earnings-date 2025-11-13
```

**What this does:**
- Queries earnings calendar for symbols on specified date
- Checks contract cache (`.dlt-ibapi/cache/contracts/`) for existing contracts
- Calls IB ContractDetails API for new symbols
- Handles failures gracefully (logs error, continues with next symbol)
- Saves resolved contracts to cache

**Output example:**
```
Contract Resolution Summary
┏━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━┓
┃ Metric           ┃ Value            ┃
┡━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━┩
│ Total Requested  │ 370              │
│ Resolved (New)   │ 258              │
│ Skipped (Cached) │ 111              │
│ Failed           │ 1                │
│ Duration         │ 92.07s           │
│ Cache Path       │ .dlt-ibapi/cache │
└──────────────────┴──────────────────┘

✗ Failed Contracts:
┏━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃ Symbol ┃ Error                                                               ┃
┡━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┩
│ EMX    │ Failed to get contract details for EMX: IB error 1763049658501: 200 │
└────────┴─────────────────────────────────────────────────────────────────────┘
```

**Why this step matters:**
- Validates symbols before expensive snapshot operations
- Identifies invalid symbols (delisted, wrong exchange, non-existent)
- Pre-populates cache for faster subsequent runs
- Avoids "No security definition" errors during snapshot

**Common failures:**
- `Error 200`: Symbol not found (delisted, invalid, or non-US equity)
- Wrong exchange routing
- Futures/options symbols in earnings data
- Typos or invalid tickers

---

### Step 3: Capture Option Chain Snapshots

With contracts resolved, capture option chain snapshots:

```bash
mohamedali$ dlt-ibapi snapshot --earnings-date 2025-11-13 --min-dte 0 --max-dte 60

### 2. Earnings Calendar Data

Obtain earnings data from Nasdaq or other sources in JSON format:

```json
[
  {
    "reporting_date": "2025-11-13",
    "time_slot": "time-pre-market",
    "symbol": "DIS",
    "company_name": "Walt Disney Company (The)",
    "fiscal_quarter_ending": "Sep/2025",
    "consensus_eps_forecast": "$1.03",
    "consensus_eps_value": 1.03
  }
]
```

**Note:** The loader supports both old (`date`, `time`) and new (`reporting_date`, `time_slot`) schema formats.

---

## Complete Workflow

### Step 1: Load Earnings Calendar

Load earnings data from a JSON file into the `earnings` dataset:

```bash
# Load all earnings from a file
dlt-ibapi load-earnings ./earnings_raw/earnings_2025-11-13.json

# Load with date filter
dlt-ibapi load-earnings ./earnings_raw/earnings.json \
  --start-date 2025-11-01 \
  --end-date 2025-12-31

# Load specific symbols only
dlt-ibapi load-earnings ./earnings.json \
  --symbols AAPL MSFT GOOGL
```

**Result:** Data is written to `./data/earnings/earnings_calendar/*.parquet`

### Step 2: Query Earnings Calendar

Verify loaded data and find upcoming earnings:

```bash
# Check database statistics
dlt-ibapi stats ./data --dataset earnings

# List upcoming earnings (next 30 days)
dlt-ibapi list-earnings --days-ahead 30

# Filter by symbols
dlt-ibapi list-earnings --symbols AAPL MSFT

# Filter by time
dlt-ibapi list-earnings --days-ahead 7 --earnings-time PRE_MARKET
```

**Example Output:**
```
Earnings Calendar: Next 30 Days

symbol  earnings_date  earnings_time  company_name
DIS     2025-11-13     PRE_MARKET     Walt Disney Company (The)
AMAT    2025-11-13     AFTER_HOURS    Applied Materials, Inc.
JD      2025-11-13     PRE_MARKET     JD.com, Inc.
```

### Step 3: Resolve Contracts (Validate Symbols)

**New step (recommended)**: Pre-resolve contracts before snapshot to validate symbols and handle failures gracefully.

```bash
mohamedali$ dlt-ibapi resolve-contracts --earnings-date 2025-11-13
```

**What Happens:**
- Queries earnings database for symbols on `2025-11-13`
- Checks contract cache (`.dlt-ibapi/cache/contracts/`) for existing contracts
- Calls IB ContractDetails API for new symbols
- Handles failures gracefully (logs error, continues with next symbol)
- Reports detailed success/failure summary

**Example Output:**
```
Contract Resolution Summary
┏━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━┓
┃ Metric           ┃ Value            ┃
┡━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━┩
│ Total Requested  │ 370              │
│ Resolved (New)   │ 258              │
│ Skipped (Cached) │ 111              │
│ Failed           │ 1                │
│ Duration         │ 92.07s           │
│ Cache Path       │ .dlt-ibapi/cache │
└──────────────────┴──────────────────┘

✗ Failed Contracts:
┏━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃ Symbol ┃ Error                                                               ┃
┡━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┩
│ EMX    │ Failed to get contract details for EMX: IB error 1763049658501: 200 │
└────────┴─────────────────────────────────────────────────────────────────────┘
```

**Why This Step Matters:**
- **Validates symbols** before expensive snapshot operations
- **Identifies invalid symbols** (delisted, wrong exchange, non-existent)
- **Pre-populates cache** for faster subsequent runs
- **Handles failures gracefully** - doesn't fail entire batch

**Common Failures:**
- `Error 200`: Symbol not found (delisted, invalid, or non-US equity)
- Wrong exchange routing
- Futures/options symbols in earnings data
- Typos or invalid tickers

**Note on Options Availability:**
- Contract resolution validates that a symbol exists in IB's database
- It does NOT check if the symbol has listed options
- Many small-cap/micro-cap stocks don't have options
- Snapshot will succeed but show "0 expirations, 0 strikes" for these symbols
- This is expected behavior - not all stocks have options listed

---

### Step 4: Snapshot Option Chains (Batch)

Capture option chains for all symbols with earnings on a specific date:

```bash
# All symbols reporting earnings on 2025-11-13 (uses cached contracts)
mohamedali$ dlt-ibapi snapshot --earnings-date 2025-11-13 \
  --min-dte 0 \
  --max-dte 60

# Only pre-market announcements
dlt-ibapi snapshot --earnings-date 2025-11-13 \
  --earnings-time PRE_MARKET \
  --min-dte 0 \
  --max-dte 14

# Only after-hours announcements
dlt-ibapi snapshot --earnings-date 2025-11-13 \
  --earnings-time AFTER_HOURS \
  --min-dte 7 \
  --max-dte 30
```

**What Happens:**

1. **Queries earnings database** for symbols with earnings on `2025-11-13`
2. **Applies time filter** (if specified) - `PRE_MARKET`, `AFTER_HOURS`, or `UNKNOWN`
3. **Processes each symbol sequentially:**
   - Connects to IB Gateway
   - Fetches option chain metadata (strikes, expirations)
   - Writes to `./data/option_chains/`
4. **Skips symbols** without option data (many small-cap stocks don't have options)
5. **Shows live progress** for each symbol
6. **Displays summary table** with success/failure status

**Example Output:**
```
Capturing Option Chain Snapshots for Earnings Date: 2025-11-13

Earnings Date: 2025-11-13
Snapshot Date: 2025-11-13
Time Filter:   PRE_MARKET
DTE range:     0 to 7
Pipeline:      ib_snapshots
Dataset:       option_chains

Processing PRE_MARKET earnings snapshots...

  [1/66] Processing DIS...
  [2/66] Processing BN...
  [3/66] Processing JD...
  ...

┏━━━━━━━━┳━━━━━━━━┳━━━━━━━━━━━━━┳━━━━━━━━━┳━━━━━━━━━━┓
┃ Symbol ┃ Status ┃ Expirations ┃ Strikes ┃ Duration ┃
┡━━━━━━━━╇━━━━━━━━╇━━━━━━━━━━━━━╇━━━━━━━━━╇━━━━━━━━━━┩
│ DIS    │ ✓      │ 12          │ 150     │ 2.3s     │
│ BN     │ ✓      │ 8           │ 98      │ 1.8s     │
│ JD     │ ✓      │ 10          │ 120     │ 2.1s     │
│ ALH    │ ✗      │ -           │ -       │ 0.5s     │
│ ...    │ ...    │ ...         │ ...     │ ...      │
└────────┴────────┴─────────────┴─────────┴──────────┘

Summary:
  Total symbols:      66
  Successful:         52
  Failed:             14 (ALH, NIQ, VIA, ...)
  Total duration:     125.4s
```

### Step 5: Verify Captured Data

Check that snapshots were saved:

```bash
# View option chain statistics
dlt-ibapi stats ./data --dataset option_chains

# List snapshots for a specific symbol
dlt-ibapi list-snapshots --underlying DIS

# Query snapshot data (Python)
python -c "
from dlt_ibapi.repositories import OptionChainSnapshotReader
from datetime import date

reader = OptionChainSnapshotReader('./data', 'option_chains')
chain = reader.get_chain_for_date('DIS', date(2025, 11, 13), min_dte=0, max_dte=7)
print(chain)
"
```

---

## Command Reference

### `dlt-ibapi load-earnings`

Load earnings calendar from JSON file.

```bash
dlt-ibapi load-earnings <json_file> [OPTIONS]
```

**Arguments:**
- `json_file`: Path to Nasdaq JSON file

**Options:**
- `--start-date YYYY-MM-DD`: Filter minimum earnings date
- `--end-date YYYY-MM-DD`: Filter maximum earnings date
- `--symbols AAPL MSFT`: Filter specific symbols
- `--pipeline-name NAME`: DLT pipeline name (default: `earnings_loader`)
- `--dataset NAME`: Dataset name (default: `earnings`)

**Example:**
```bash
dlt-ibapi load-earnings ./earnings_2025-11-13.json \
  --start-date 2025-11-13 \
  --end-date 2025-12-31 \
  --symbols DIS AMAT JD
```

---

### `dlt-ibapi list-earnings`

Query and display upcoming earnings.

```bash
dlt-ibapi list-earnings [OPTIONS]
```

**Options:**
- `--days-ahead N`: Number of days to look ahead (default: 7)
- `--from-date YYYY-MM-DD`: Start date (default: today)
- `--symbols AAPL MSFT`: Filter by symbols
- `--earnings-time TIME`: Filter by time (`PRE_MARKET`, `AFTER_HOURS`, `UNKNOWN`)
- `--database PATH`: Data directory (default: `./data`)
- `--dataset NAME`: Dataset name (default: `earnings`)

**Example:**
```bash
dlt-ibapi list-earnings --days-ahead 30 --earnings-time AFTER_HOURS
```

---

### `dlt-ibapi resolve-contracts`

Pre-populate contract cache for symbols (validates before snapshot).

```bash
dlt-ibapi resolve-contracts [SYMBOLS...] [OPTIONS]
```

**Arguments:**
- `SYMBOLS...`: Optional list of symbols to resolve (e.g., `AAPL MSFT GOOGL`)

**Options:**
- `--earnings-date YYYY-MM-DD`: Load symbols from earnings on this date
- `--earnings-file PATH`: Load symbols from earnings JSON file
- `--database-path PATH`: Data directory (default: `./data`)
- `--cache-path PATH`: Contract cache directory (default: `.dlt-ibapi/cache`)
- `--exchange STR`: Exchange for resolution (default: `SMART`)
- `--currency STR`: Currency (default: `USD`)

**Examples:**
```bash
# Resolve specific symbols
dlt-ibapi resolve-contracts AAPL MSFT GOOGL

# Resolve all symbols from earnings date
dlt-ibapi resolve-contracts --earnings-date 2025-11-13

# Resolve from JSON file
dlt-ibapi resolve-contracts --earnings-file earnings.json
```

**Benefits:**
- Validates symbols before expensive operations
- Identifies invalid/delisted symbols early
- Builds contract cache for faster runs
- Handles failures gracefully

---

### `dlt-ibapi snapshot --earnings-date`

Batch snapshot all symbols with earnings on a specific date.

```bash
dlt-ibapi snapshot --earnings-date YYYY-MM-DD [OPTIONS]
```

**Required:**
- `--earnings-date YYYY-MM-DD`: Earnings announcement date

**Optional:**
- `--earnings-time TIME`: Filter by earnings time (`PRE_MARKET`, `AFTER_HOURS`, `UNKNOWN`)
- `--min-dte N`: Minimum days to expiration (default: 7)
- `--max-dte N`: Maximum days to expiration (default: 365)
- `--pipeline-name NAME`: DLT pipeline name (default: `ib_snapshots`)
- `--dataset NAME`: Option chains dataset (default: `option_chains`)
- `--earnings-dataset NAME`: Earnings dataset (default: `earnings`)

**Example:**
```bash
dlt-ibapi snapshot --earnings-date 2025-11-13 \
  --earnings-time PRE_MARKET \
  --min-dte 0 \
  --max-dte 14
```

---

### `dlt-ibapi snapshot SYMBOL`

Single symbol snapshot (original command - still works).

```bash
dlt-ibapi snapshot SYMBOL [OPTIONS]
```

**Example:**
```bash
dlt-ibapi snapshot AAPL --min-dte 7 --max-dte 60
```

---

## Advanced Usage

### Example: Weekly Earnings Workflow

```bash
#!/bin/bash
# weekly_earnings_snapshot.sh
# Run every Monday to capture upcoming week's earnings

# 1. Load latest earnings data
wget -O earnings_$(date +%Y-%m-%d).json \
  "https://api.nasdaq.com/api/calendar/earnings?date=$(date +%Y-%m-%d)"

dlt-ibapi load-earnings earnings_$(date +%Y-%m-%d).json \
  --start-date $(date +%Y-%m-%d) \
  --end-date $(date -d "+7 days" +%Y-%m-%d)

# 2. List this week's earnings
dlt-ibapi list-earnings --days-ahead 7 > weekly_earnings.txt

# 3. Snapshot each day's earnings
for day_offset in {0..6}; do
  earnings_date=$(date -d "+$day_offset days" +%Y-%m-%d)

  echo "Processing earnings for $earnings_date..."

  # Pre-market snapshots (short-dated)
  dlt-ibapi snapshot --earnings-date $earnings_date \
    --earnings-time PRE_MARKET \
    --min-dte 0 \
    --max-dte 7

  # After-hours snapshots (include next week)
  dlt-ibapi snapshot --earnings-date $earnings_date \
    --earnings-time AFTER_HOURS \
    --min-dte 0 \
    --max-dte 14
done
```

---

### Python API Usage

```python
from datetime import date
import dlt
from dlt_ibapi import load_earnings_from_json
from dlt_ibapi.cli.snapshot import execute_batch_snapshot_for_earnings
from dlt_ibapi.cli.models import SnapshotParams
from dlt_ibapi.repositories import EarningsCalendarReader

# 1. Load earnings
pipeline = dlt.pipeline(
    pipeline_name="earnings_loader",
    destination=dlt.destinations.filesystem(bucket_url="./data"),
    dataset_name="earnings",
)

data = load_earnings_from_json(
    json_file="./earnings_2025-11-13.json",
    start_date=date(2025, 11, 13),
    end_date=date(2025, 12, 31),
)

info = pipeline.run(data, write_disposition="replace", loader_file_format="parquet")

# 2. Query earnings
reader = EarningsCalendarReader("./data", "earnings")
earnings_df = reader.get_earnings_on_date(date(2025, 11, 13))
print(f"Found {len(earnings_df)} symbols with earnings on 2025-11-13")

# 3. Batch snapshot
params = SnapshotParams(
    earnings_date=date(2025, 11, 13),
    earnings_time_filter="PRE_MARKET",
    snapshot_date=date(2025, 11, 13),
    min_dte=0,
    max_dte=7,
    pipeline_name="ib_snapshots",
    dataset_name="option_chains",
)

result = execute_batch_snapshot_for_earnings(params)
print(f"Captured {result.successful_snapshots}/{result.total_symbols} snapshots")
```

---

## Troubleshooting

### Issue: Snapshot shows "0 expirations, 0 strikes" for many symbols

**Cause:** Many small-cap and micro-cap stocks don't have listed options.

**Explanation:**
- Contract resolution (`resolve-contracts`) only validates that a symbol EXISTS in IB's database
- It does NOT check if the symbol has listed options
- Snapshot succeeds but returns empty data (0 expirations/strikes)
- This is **expected behavior**, not an error

**Which symbols have options?**
Generally, only stocks with:
- Market cap > $1B
- Average daily volume > 1M shares
- Listed on major exchanges (NYSE, NASDAQ)
- Not penny stocks or OTC

**Solution:**
- This is normal - batch snapshot handles it gracefully
- No action needed - empty snapshots are valid
- Filter your earnings list to large-cap stocks if you want to avoid empties
- Use market cap / volume filters when loading earnings data

**Example filtering:**
```bash
dlt-ibapi load-earnings earnings.json --symbols AAPL MSFT GOOGL DIS AMAT
```

**Note:** As of 2025-11-13, the snapshot command now correctly reports expiration and strike counts by reading pre-computed counts from the main table (DLT normalizes arrays into child tables)

---

### Issue: Batch snapshot is slow

**Cause:** IB Gateway has rate limits for API requests.

**Solutions:**
- **Filter by earnings time** to reduce symbol count: `--earnings-time PRE_MARKET`
- **Run snapshots at different times** (pre-market earnings in the morning, after-hours in the evening)
- **Use wider DTE ranges** less frequently instead of daily narrow ranges

---

### Issue: Earnings data not found

**Cause:** Earnings calendar was not loaded or date filter excludes data.

**Solutions:**
```bash
# Check what's in the database
dlt-ibapi stats ./data --dataset earnings

# Verify date range
dlt-ibapi list-earnings --days-ahead 365  # Check all data

# Reload earnings with broader date range
dlt-ibapi load-earnings earnings.json  # No date filters
```

---

### Issue: Logger errors / poor visibility

**Cause:** Logging configuration issues.

**Solution:** The batch snapshot now uses standard Python logging with live progress updates:

```bash
# Standard output shows progress
dlt-ibapi snapshot --earnings-date 2025-11-13 --earnings-time PRE_MARKET

# Output:
#   [1/66] Processing DIS...
#   [2/66] Processing BN...
#   ...
```

**Logging Options (Added 2025-11-13):**

```bash
# Write logs to file with auto-rotation (10MB limit)
dlt-ibapi snapshot --earnings-date 2025-11-13 --log-file snapshot.log

# Enable verbose (DEBUG) logging
dlt-ibapi snapshot --earnings-date 2025-11-13 --verbose --log-file snapshot.log

# Suppress INFO logs (only show WARNING+)
dlt-ibapi snapshot --earnings-date 2025-11-13 --quiet

# Combine options
dlt-ibapi snapshot --earnings-date 2025-11-13 \
  --verbose \
  --log-file logs/snapshot_$(date +%Y%m%d).log
```

**Available logging flags:**
- `--log-file PATH`: Write all logs to file with automatic rotation at 10MB
- `--verbose` / `-v`: Enable DEBUG level logging (detailed execution info)
- `--quiet` / `-q`: Suppress INFO logs (only WARNING and ERROR messages)

**Note:** When `--log-file` is specified, all Python logging output goes to the file, while console output (Rich tables and progress) still displays on screen

---

### Issue: IB Gateway disconnects

**Cause:** Too many concurrent connections or idle timeout.

**Solutions:**
- **Ensure only one instance** of the script is running
- **Restart IB Gateway** if connection fails
- **Check credentials** if using live account
- **Verify port** in `~/.dlt-ibapi/ib_gateway.yaml`

---

## Related Documentation

- [Earnings Guide](./EARNINGS_GUIDE.md) - Loading and querying earnings data
- [Backtest Quickstart](./BACKTEST_QUICKSTART.md) - Using option data for backtesting
- [API Reference](./API_REFERENCE.md) - Complete API documentation
- [README](../README.md) - Main project documentation
