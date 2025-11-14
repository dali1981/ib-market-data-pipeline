# Complete Data Acquisition Workflow

End-to-end workflow for acquiring market data via dlt-ibapi CLI.

## Prerequisites

- IB Gateway or TWS running and connected
- `dlt-ibapi` installed and configured
- Earnings data in JSON format (from Nasdaq or similar source)

## Overview

The complete data acquisition workflow has 5 main steps:

1. **Load Earnings Calendar** - Import earnings announcement dates
2. **Resolve Contracts** - Validate symbols and pre-populate contract cache
3. **Capture Option Snapshots** - Get option chain metadata (strikes/expirations)
4. **Backfill Equity Bars** - Get underlying stock prices (for spot prices)
5. **Backfill Option Bars** - Get historical OHLCV data for option contracts

## Step-by-Step Workflow

### Step 1: Load Earnings Calendar

Import earnings data to drive the acquisition process:

```bash
dlt-ibapi load-earnings ./earnings_2025-11-13.json
```

**What this does:**
- Parses earnings JSON file (supports both old and new Nasdaq schemas)
- Normalizes symbols (uppercase, removes special characters)
- Loads into `./data_delta/earnings/earnings_calendar/*.parquet`
- Uses `replace` write disposition (overwrites existing data)

**Verify loaded data:**
```bash
dlt-ibapi list-earnings --days-ahead 30
dlt-ibapi stats ./data_delta --dataset earnings
```

---

### Step 2: Resolve Contracts (Validate Symbols)

**Critical step**: Validate symbols exist in IB before expensive operations.

```bash
# Resolve equity contracts for all earnings symbols
dlt-ibapi resolve-contracts --earnings-date 2025-11-13

# Or for option contracts (after snapshot)
dlt-ibapi resolve-contracts --sec-type OPT --snapshot-date 2025-11-13
```

**What this does:**
- Queries earnings calendar for symbols on specified date
- Checks contract cache (`.dlt-ibapi/cache/contracts/`) for existing contracts
- Calls IB ContractDetails API for new symbols
- Handles failures gracefully (logs error, continues with next symbol)
- Saves resolved contracts to Parquet cache

**Example output:**
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
┏━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃ Symbol ┃ Error                                         ┃
┡━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┩
│ EMX    │ No security definition (Error 200)            │
└────────┴───────────────────────────────────────────────┘
```

**Why this matters:**
- Validates symbols before expensive snapshot operations
- Identifies invalid symbols (delisted, wrong exchange, non-existent)
- Pre-populates cache for faster subsequent runs
- Avoids "No security definition" errors during snapshot/backfill

---

### Step 3: Capture Option Chain Snapshots

Get option chain metadata (strikes and expirations) for all earnings symbols:

```bash
dlt-ibapi snapshot --earnings-date 2025-11-13 \
  --min-dte 0 \
  --max-dte 60
```

**What this does:**
- Queries earnings calendar for symbols with earnings on 2025-11-13
- For each symbol: fetches available strikes and expirations from IB
- Stores in `./data_delta/option_chains/option_chain_snapshot/*.parquet`
- Skips symbols without listed options (normal for small-cap stocks)

**Verify captured data:**
```bash
dlt-ibapi stats ./data_delta --dataset option_chains
dlt-ibapi list-snapshots --underlying DIS
```

---

### Step 4: Backfill Equity Bars

Get underlying stock prices (needed for spot price extraction in option backfill):

```bash
# Batch: backfill all earnings symbols
dlt-ibapi backfill-equity --earnings-date 2025-11-13 \
  --start 2025-10-01 \
  --end 2025-11-13 \
  --bar-size "1 day"

# Or single symbol:
dlt-ibapi backfill-equity DIS \
  --start 2025-10-01 \
  --end 2025-11-13 \
  --bar-size "1 day"
```

**What this does:**
- Detects gaps in existing equity data
- Fetches only missing bars from IB Historical Data API
- Stores in `./data_delta/stocks/historical_bars/*.parquet`
- Uses "1 day" bars (daily closes used for spot price extraction)

**Verify data:**
```bash
dlt-ibapi stats ./data_delta --dataset stocks
```

**Important**: This step is **required** before option backfill. The option backfill workflow needs equity bars to extract spot prices for each symbol.

---

### Step 5: Resolve Option Contracts

Before backfilling option bars, resolve option contracts to pre-populate the cache:

```bash
dlt-ibapi resolve-contracts --sec-type OPT --snapshot-date 2025-11-13
```

**What this does:**
- Loads option contracts from snapshot data (all strikes × expirations × C/P)
- Checks cache for already-resolved contracts
- Calls IB ContractDetails API for new contracts
- Saves resolved option contracts with conId, tradingClass, localSymbol
- Handles failures gracefully (some strikes may not trade)

**Why this matters:**
- IB API requires exact contract details (conId, tradingClass) for historical data
- Pre-resolving avoids "No security definition" errors during backfill
- Cache makes subsequent runs much faster

**Expected behavior:**
- Many option contracts may fail (not all strikes/expirations trade)
- This is normal - skip failed contracts during backfill

---

### Step 6: Backfill Option Bars

Finally, fetch historical OHLCV data for option contracts:

```bash
# Batch: backfill all earnings symbols with auto spot prices
dlt-ibapi backfill-options --earnings-date 2025-11-13 \
  --k-expirations 6 \
  --k-strikes 5 \
  --bar-size "5 mins" \
  --start 2025-11-01 \
  --end 2025-11-13 \
  --client-id 2

# Or single symbol with manual spot price:
dlt-ibapi backfill-options DIS 100.50 \
  --mode atm \
  --k-strikes 5 \
  --bar-size "5 mins" \
  --start 2025-11-01 \
  --end 2025-11-13
```

**What this does (batch mode):**
- Queries earnings calendar for symbols on 2025-11-13
- **Auto-extracts spot prices** from equity bars (Step 4 required!)
- Loads expirations from snapshot data (Step 3)
- Selects k closest expirations beyond earnings date (default: all)
- Selects k strikes around ATM for each expiration
- Resolves each contract via cache (Step 5)
- Detects gaps in existing option bar data
- Fetches only missing bars from IB Historical Data API
- Stores in `./data_delta/options/option_bars_backfill/*.parquet`

**Parameters:**
- `--k-expirations 6`: Limit to 6 closest expirations beyond earnings date
- `--k-strikes 5`: Select 5 strikes around ATM for each expiration
- `--bar-size "5 mins"`: Intraday granularity (options: 1 min, 5 mins, 1 hour, 1 day)
- `--start/--end`: Date range for historical bars

**Verify data:**
```bash
dlt-ibapi stats ./data_delta --dataset options
```

---

## Complete Example: Full Workflow

```bash
#!/bin/bash
# complete_data_acquisition.sh
# Full workflow for 2025-11-13 earnings

EARNINGS_DATE="2025-11-13"
START_DATE="2025-10-01"
END_DATE="2025-11-13"

echo "=== Step 1: Load Earnings Calendar ==="
dlt-ibapi load-earnings ./earnings_${EARNINGS_DATE}.json

echo "=== Step 2: Resolve Equity Contracts ==="
dlt-ibapi resolve-contracts --earnings-date ${EARNINGS_DATE}

echo "=== Step 3: Capture Option Snapshots ==="
dlt-ibapi snapshot --earnings-date ${EARNINGS_DATE} \
  --min-dte 0 \
  --max-dte 60

echo "=== Step 4: Backfill Equity Bars ==="
dlt-ibapi backfill-equity --earnings-date ${EARNINGS_DATE} \
  --start ${START_DATE} \
  --end ${END_DATE} \
  --bar-size "1 day"

echo "=== Step 5: Resolve Option Contracts ==="
dlt-ibapi resolve-contracts --sec-type OPT \
  --snapshot-date ${EARNINGS_DATE}

echo "=== Step 6: Backfill Option Bars ==="
dlt-ibapi backfill-options --earnings-date ${EARNINGS_DATE} \
  --k-expirations 6 \
  --k-strikes 5 \
  --bar-size "5 mins" \
  --start ${START_DATE} \
  --end ${END_DATE} \
  --client-id 2

echo "=== Verify Data ==="
dlt-ibapi stats ./data_delta --dataset earnings
dlt-ibapi stats ./data_delta --dataset stocks
dlt-ibapi stats ./data_delta --dataset option_chains
dlt-ibapi stats ./data_delta --dataset options

echo "=== Done! ==="
```

---

## Data Storage Structure

After completing the workflow, your data directory will look like:

```
data_delta/
├── earnings/
│   └── earnings_calendar/
│       ├── date=2025-11-13/
│       │   └── *.parquet
│       └── _dlt_loads/
│           └── *.jsonl
│
├── stocks/
│   └── historical_bars/
│       ├── date=2025-10-01/
│       │   ├── symbol=DIS/*.parquet
│       │   ├── symbol=AMAT/*.parquet
│       │   └── symbol=JD/*.parquet
│       ├── date=2025-10-02/...
│       └── date=2025-11-13/...
│
├── option_chains/
│   └── option_chain_snapshot/
│       ├── date=2025-11-13/
│       │   ├── symbol=DIS/*.parquet
│       │   ├── symbol=AMAT/*.parquet
│       │   └── symbol=JD/*.parquet
│       └── _dlt_loads/
│           └── *.jsonl
│
└── options/
    └── option_bars_backfill/
        ├── date=2025-10-01/
        │   ├── symbol=DIS/*.parquet
        │   ├── symbol=AMAT/*.parquet
        │   └── symbol=JD/*.parquet
        ├── date=2025-10-02/...
        └── date=2025-11-13/...
```

**Note**: Data uses Delta Lake format with Hive partitioning by date/symbol for efficient querying.

---

## Troubleshooting

### Error: "No equity data for {symbol} - skipping"

**Cause**: Step 4 (Backfill Equity Bars) was skipped or failed.

**Solution**: Run equity backfill before option backfill:
```bash
dlt-ibapi backfill-equity --earnings-date 2025-11-13 \
  --start 2025-10-01 \
  --end 2025-11-13 \
  --bar-size "1 day"
```

The option backfill workflow needs equity bars to extract spot prices.

---

### Error: "No security definition" during option backfill

**Cause**: Step 5 (Resolve Option Contracts) was skipped.

**Solution**: Pre-resolve option contracts before backfill:
```bash
dlt-ibapi resolve-contracts --sec-type OPT --snapshot-date 2025-11-13
```

---

### Many symbols show "0 expirations, 0 strikes"

**Cause**: Small-cap/micro-cap stocks don't have listed options.

**Explanation**:
- Contract resolution validates symbol exists (Step 2)
- Snapshot succeeds but returns empty data (Step 3)
- This is **expected** - not all stocks have options

**Which symbols have options?**
- Market cap > $1B
- Volume > 1M shares/day
- Major exchanges (NYSE, NASDAQ)

**Solution**: Filter earnings to large-cap stocks or accept empty snapshots (normal behavior).

---

### Batch backfill is slow

**Cause**: IB Gateway has rate limits (60 requests/min for historical data).

**Solutions:**
- Reduce `--k-expirations` (fewer expirations per symbol)
- Reduce `--k-strikes` (fewer strikes per expiration)
- Use `--bar-size "1 day"` instead of intraday bars
- Run in stages (process symbols in batches)

---

## Performance Tips

### Optimize Request Volume

```bash
# Conservative: 3 expirations, 3 strikes, daily bars
dlt-ibapi backfill-options --earnings-date 2025-11-13 \
  --k-expirations 3 \
  --k-strikes 3 \
  --bar-size "1 day"

# Moderate: 6 expirations, 5 strikes, 5-min bars
dlt-ibapi backfill-options --earnings-date 2025-11-13 \
  --k-expirations 6 \
  --k-strikes 5 \
  --bar-size "5 mins"

# Aggressive: all expirations, all strikes (very slow!)
dlt-ibapi backfill-options --earnings-date 2025-11-13 \
  --mode all  # Not recommended for batch
```

### Use Multiple Client IDs

Run parallel backfills with different client IDs:

```bash
# Terminal 1: Pre-market symbols
dlt-ibapi backfill-options --earnings-date 2025-11-13 \
  --earnings-time PRE_MARKET \
  --client-id 2

# Terminal 2: After-hours symbols
dlt-ibapi backfill-options --earnings-date 2025-11-13 \
  --earnings-time AFTER_HOURS \
  --client-id 3
```

---

## Related Documentation

- [Earnings Snapshot Workflow](./EARNINGS_SNAPSHOT_WORKFLOW.md) - Detailed snapshot documentation
- [Earnings Guide](./EARNINGS_GUIDE.md) - Loading and querying earnings data
- [Option Contract Resolution Guide](./OPTION_CONTRACT_RESOLUTION_GUIDE.md) - Contract resolution details
- [Backfill Guide](./BACKFILL_GUIDE.md) - Gap detection and backfill strategies
- [Backtest Quickstart](./BACKTEST_QUICKSTART.md) - Using data for backtesting
- [API Reference](./API_REFERENCE.md) - Complete API documentation
