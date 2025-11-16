# Historical Tick Data Guide

## Overview

Historical tick-by-tick data provides ultra-precise market data for options contracts, enabling detailed execution analysis and realistic backtesting. This guide covers how to fetch, store, and query tick data using `dlt-ibapi`.

## When to Use Tick Data vs Bar Data

### Use Tick Data When:
- **Precise execution analysis**: Need exact bid/ask at specific times (e.g., 3:55pm entry)
- **Spread analysis**: Want to measure actual spreads and slippage
- **Microstructure analysis**: Study opening/closing auction behavior
- **Volume distribution**: Understand when trades occurred within a time window
- **Fill simulation**: Model limit orders vs market orders with real spreads

### Use Bar Data When:
- **Strategy development**: Testing strategies with minute/hourly/daily data
- **Long-term backtesting**: Analyzing multi-day or multi-week positions
- **Lower storage requirements**: Tick data is much larger than bar data
- **Simpler analysis**: OHLCV data sufficient for strategy logic

## IB API Tick Data Capabilities

### Tick Types

**BID_ASK** (recommended for options):
- Bid/ask prices and sizes
- Automatically calculates spread and midpoint
- Best for analyzing entry/exit feasibility

**TRADES**:
- Last trade prices and sizes
- Exchange and special conditions
- Best for volume distribution analysis

**MIDPOINT**:
- Midpoint prices only
- Minimal data for price reference

### Limitations

**Important IB API Constraints**:
- ⚠️ **Maximum 1000 ticks per request** (automatic pagination handled)
- ⚠️ **15-second rate limit** per contract (automatic rate limiting)
- ⚠️ **60 requests per 10 minutes** global limit
- ⚠️ **Cannot span multiple days** in single request (handled by `fetch_historical_ticks_range`)
- ⚠️ **Options only available historically** (not real-time)
- ⚠️ **Up to 6 months** of tick data available

## CLI Usage

### Basic Example: Entry Window Ticks

Fetch bid/ask ticks around a 3:55pm entry:

```bash
dlt-ibapi backfill-ticks TMC 20251121 5.0 C \
  --start "2025-11-12 15:50" \
  --end "2025-11-12 16:00" \
  --tick-type bid_ask
```

Output:
```
Backfilling bid_ask ticks for TMC $5.0C exp 20251121
Time window: 2025-11-12 15:50:00 to 2025-11-12 16:00:00

✓ Backfill complete
Loaded 127 ticks in 18.3s
Time range: 2025-11-12T15:50:00 to 2025-11-12T16:00:00
Data saved to: ./data/option_ticks/
```

### Exit Window Ticks

Fetch ticks for exit analysis the next day:

```bash
dlt-ibapi backfill-ticks TMC 20251121 5.0 C \
  --start "2025-11-14 09:30" \
  --end "2025-11-14 09:40" \
  --tick-type bid_ask
```

### Trade Volume Ticks

Get trade ticks to analyze volume distribution:

```bash
dlt-ibapi backfill-ticks AAPL 20251219 150.0 C \
  --start "2025-11-12 15:00" \
  --end "2025-11-12 16:00" \
  --tick-type trades
```

### CLI Options

| Option | Default | Description |
|--------|---------|-------------|
| `--tick-type` | `bid_ask` | Tick type: `bid_ask` or `trades` |
| `--exchange` | `SMART` | Exchange for routing |
| `--currency` | `USD` | Currency |
| `--use-rth/--no-rth` | `--use-rth` | Use regular trading hours only |
| `--data-dir` | `./data` | Data directory path |
| `--dataset` | `option_ticks` | Dataset name |
| `--pipeline-name` | `ib_tick_backfill` | DLT pipeline name |

## Programmatic Usage (Python API)

### Fetching Tick Data

```python
import dlt
from datetime import datetime, date
from dlt_ibapi.backfill.tick_resources import backfill_option_ticks_bid_ask

# Create pipeline
pipeline = dlt.pipeline(
    pipeline_name="ib_ticks",
    destination=dlt.destinations.filesystem(bucket_url="./data"),
    dataset_name="option_ticks"
)

# Fetch ticks for specific time window
data = backfill_option_ticks_bid_ask(
    underlying="TMC",
    expiry=date(2025, 11, 21),
    strike=5.0,
    right='C',
    start_datetime=datetime(2025, 11, 12, 15, 50),  # 3:50pm
    end_datetime=datetime(2025, 11, 12, 16, 0),     # 4:00pm
)

# Run pipeline
info = pipeline.run(data, loader_file_format="parquet")
print(f"Loaded {info.metrics.get('rows', 0)} ticks")
```

### Querying Tick Data

```python
from datetime import datetime, date
from dlt_ibapi.repositories import OptionTicksReader

# Initialize reader
reader = OptionTicksReader('./data', 'option_ticks')

# Get spread at specific time (±30 seconds)
spread_355 = reader.get_spread_at_time(
    underlying='TMC',
    expiry=date(2025, 11, 21),
    strike=5.0,
    right='C',
    target_time=datetime(2025, 11, 12, 15, 55),
    window_seconds=30
)
print(f"Spread at entry: ${spread_355:.4f}")

# Get all ticks in window
ticks = reader.get_ticks(
    underlying='TMC',
    expiry=date(2025, 11, 21),
    strike=5.0,
    right='C',
    start_datetime=datetime(2025, 11, 12, 15, 50),
    end_datetime=datetime(2025, 11, 12, 16, 0),
    tick_type='bid_ask'
)

print(f"Tick count: {len(ticks)}")
print(f"Avg spread: ${ticks['spread'].mean():.4f}")
print(f"Min spread: ${ticks['spread'].min():.4f}")
print(f"Max spread: ${ticks['spread'].max():.4f}")

# Get volume in window
volume = reader.get_volume_window(
    underlying='TMC',
    expiry=date(2025, 11, 21),
    strike=5.0,
    right='C',
    start_datetime=datetime(2025, 11, 12, 15, 50),
    end_datetime=datetime(2025, 11, 12, 16, 0)
)
print(f"Volume: {volume} contracts")

# Get comprehensive statistics
stats = reader.get_tick_stats(
    underlying='TMC',
    expiry=date(2025, 11, 21),
    strike=5.0,
    right='C',
    start_datetime=datetime(2025, 11, 12, 15, 50),
    end_datetime=datetime(2025, 11, 12, 16, 0)
)
print(f"Stats: {stats}")
```

## Storage Structure

Tick data is stored in Hive-partitioned Parquet files:

```
data/option_ticks/
├── option_ticks_bid_ask/
│   ├── date=2025-11-12/
│   │   └── symbol=TMC/
│   │       └── *.parquet
│   └── date=2025-11-14/
│       └── symbol=TMC/
│           └── *.parquet
└── option_ticks_trades/
    └── date=2025-11-12/
        └── symbol=TMC/
            └── *.parquet
```

**Partition Columns**:
- `date`: ISO date (YYYY-MM-DD) - enables efficient date filtering
- `symbol`: Underlying symbol - enables efficient symbol filtering

**Primary Key**: `[underlying, expiry, strike, right, tick_time]` - prevents duplicates

## Schema

### Bid/Ask Tick Schema

| Column | Type | Description |
|--------|------|-------------|
| `tick_time` | datetime | Tick timestamp |
| `bid_price` | float | Bid price |
| `ask_price` | float | Ask price |
| `bid_size` | int | Bid size (contracts) |
| `ask_size` | int | Ask size (contracts) |
| `spread` | float | `ask_price - bid_price` |
| `spread_pct` | float | `spread / midpoint * 100` |
| `midpoint` | float | `(bid_price + ask_price) / 2` |
| `underlying` | str | Underlying symbol |
| `expiry` | str | Expiration date (ISO) |
| `strike` | float | Strike price |
| `right` | str | 'C' or 'P' |
| `date` | str | Date partition (ISO) |
| `symbol` | str | Same as underlying (partition) |

### Trade Tick Schema

| Column | Type | Description |
|--------|------|-------------|
| `tick_time` | datetime | Tick timestamp |
| `price` | float | Trade price |
| `size` | int | Trade size (contracts) |
| `exchange` | str | Exchange |
| `special_conditions` | str | Special conditions |
| `underlying` | str | Underlying symbol |
| `expiry` | str | Expiration date (ISO) |
| `strike` | float | Strike price |
| `right` | str | 'C' or 'P' |
| `date` | str | Date partition (ISO) |
| `symbol` | str | Same as underlying (partition) |

## Typical Tick Counts

For 10-minute window (e.g., 3:50-4:00pm):

| Liquidity | Tick Count |
|-----------|------------|
| Liquid options (AAPL, SPY) | 100-500 ticks |
| Moderate liquidity (midcap stocks) | 50-100 ticks |
| Illiquid (small cap, far OTM) | < 50 ticks |

**Note**: Illiquid options may have sparse tick data. Consider using bar data if tick count is too low.

## Rate Limiting and Pagination

### Automatic Handling

`dlt-ibapi` automatically handles:
- **Pagination**: Fetches 1000 ticks at a time, continues until all data retrieved
- **Rate limiting**: Enforces 15-second wait between requests per contract
- **Multi-day queries**: Splits requests by day to comply with IB API limitation

### Manual Control

If you need finer control over rate limiting:

```python
from ib_connector import IBRuntime

with IBRuntime(host='127.0.0.1', port=4002, client_id=1) as runtime:
    # Fetch single page (max 1000 ticks)
    ticks = runtime.tick_historical.fetch_historical_ticks(
        contract=my_contract,
        start_time=datetime(2025, 11, 12, 15, 50),
        end_time=datetime(2025, 11, 12, 16, 0),
        tick_type='BID_ASK',
        timeout=30.0  # Custom timeout
    )
```

## Best Practices

### 1. Pre-fetch for Critical Analysis

Fetch tick data ahead of time for important time windows:

```bash
# Entry window (3:50-4:00pm)
dlt-ibapi backfill-ticks TMC 20251121 5.0 C \
  --start "2025-11-12 15:50" --end "2025-11-12 16:00"

# Exit window (next day 9:30-9:40am)
dlt-ibapi backfill-ticks TMC 20251121 5.0 C \
  --start "2025-11-14 09:30" --end "2025-11-14 09:40"
```

### 2. Use Wider Windows for Illiquid Options

If tick count is low, expand time window:

```bash
# Wider window (3:45-4:00pm)
dlt-ibapi backfill-ticks TMC 20251121 5.0 C \
  --start "2025-11-12 15:45" --end "2025-11-12 16:00"
```

### 3. Combine Tick and Bar Data

Use ticks for precise points, bars for context:

```python
# Get 1-minute bars for context
bars = equity_reader.get_bars(...)

# Get ticks for exact entry time
ticks = ticks_reader.get_ticks(...)

# Analyze spread at entry vs average bar volume
```

### 4. Monitor Storage Size

Tick data is large. Monitor disk usage:

```bash
# Check tick data size
du -sh ./data/option_ticks/

# Check specific contract
du -sh ./data/option_ticks/option_ticks_bid_ask/date=2025-11-12/symbol=TMC/
```

**Typical sizes**:
- 10-minute bid/ask window: 5-50 KB compressed Parquet
- Full trading day: 100KB - 5MB depending on liquidity
- 100 contracts × 1 day: 10-500 MB

### 5. Use `get_spread_at_time` for Single Points

Instead of loading all ticks for a single time:

```python
# Good: Use helper function
spread = reader.get_spread_at_time(
    underlying='TMC',
    expiry=date(2025, 11, 21),
    strike=5.0,
    right='C',
    target_time=datetime(2025, 11, 12, 15, 55),
    window_seconds=30
)

# Less efficient: Load all ticks
ticks = reader.get_ticks(...)
spread = ticks['spread'].mean()
```

## Troubleshooting

### No ticks returned

**Possible causes**:
1. **Contract doesn't exist**: Verify expiration date and strike
2. **No trading activity**: Check if option is too far OTM or too illiquid
3. **Time window outside RTH**: Use `--no-rth` to include extended hours
4. **Time zone mismatch**: IB API uses exchange local time (Eastern Time for US stocks)

**Solution**:
```bash
# Try wider window
dlt-ibapi backfill-ticks TMC 20251121 5.0 C \
  --start "2025-11-12 09:30" --end "2025-11-12 16:00"

# Include extended hours
dlt-ibapi backfill-ticks TMC 20251121 5.0 C \
  --start "2025-11-12 09:30" --end "2025-11-12 16:00" \
  --no-rth
```

### Rate limit errors

**Error**: `Pacing violation` or timeout

**Solution**: Reduce request frequency or wait 15 seconds between requests.

```python
import time

for contract in contracts:
    # Fetch ticks
    ticks = backfill_option_ticks_bid_ask(...)

    # Wait to avoid rate limit
    time.sleep(15)
```

### Data quality issues

**Issue**: Large gaps in tick data

**Cause**: Low liquidity or market hours

**Solution**: Use bar data for periods with sparse ticks.

## Use Cases

### 1. Precise Spread Analysis

Measure exact bid/ask at entry/exit times:

```python
entry_spread = reader.get_spread_at_time(
    underlying='TMC',
    expiry=date(2025, 11, 21),
    strike=5.0,
    right='C',
    target_time=datetime(2025, 11, 12, 15, 55),
    window_seconds=30
)

exit_spread = reader.get_spread_at_time(
    underlying='TMC',
    expiry=date(2025, 11, 21),
    strike=5.0,
    right='C',
    target_time=datetime(2025, 11, 14, 9, 35),
    window_seconds=30
)

print(f"Entry spread: ${entry_spread:.4f}")
print(f"Exit spread: ${exit_spread:.4f}")
```

### 2. Volume Distribution

Understand when trades occurred:

```python
# Get trades in hour before close
trades = reader.get_ticks(
    underlying='TMC',
    expiry=date(2025, 11, 21),
    strike=5.0,
    right='C',
    start_datetime=datetime(2025, 11, 12, 15, 0),
    end_datetime=datetime(2025, 11, 12, 16, 0),
    tick_type='trades'
)

# Group by 5-minute bins
trades['bin'] = pd.to_datetime(trades['tick_time']).dt.floor('5min')
volume_by_bin = trades.groupby('bin')['size'].sum()
print(volume_by_bin)
```

### 3. Realistic Fill Simulation

Model limit orders vs market orders:

```python
# Get bid/ask at entry time
ticks = reader.get_ticks(
    underlying='TMC',
    expiry=date(2025, 11, 21),
    strike=5.0,
    right='C',
    start_datetime=datetime(2025, 11, 12, 15, 54),
    end_datetime=datetime(2025, 11, 12, 15, 56),
    tick_type='bid_ask'
)

# Market order: filled at ask
market_fill = ticks['ask_price'].iloc[0]

# Limit order: check if bid reached target
limit_price = 0.50
limit_filled = (ticks['bid_price'] >= limit_price).any()

print(f"Market fill: ${market_fill:.2f}")
print(f"Limit filled: {limit_filled}")
```

### 4. Microstructure Analysis

Study opening/closing auction behavior:

```python
# Get ticks around market open
open_ticks = reader.get_ticks(
    underlying='AAPL',
    expiry=date(2025, 12, 19),
    strike=150.0,
    right='C',
    start_datetime=datetime(2025, 11, 12, 9, 28),  # 2 min before open
    end_datetime=datetime(2025, 11, 12, 9, 35),    # 5 min after open
    tick_type='bid_ask'
)

# Analyze spread evolution
open_ticks['minutes_from_open'] = (
    pd.to_datetime(open_ticks['tick_time']) - datetime(2025, 11, 12, 9, 30)
).dt.total_seconds() / 60

spread_evolution = open_ticks.groupby(
    pd.cut(open_ticks['minutes_from_open'], bins=[-2, 0, 1, 2, 5])
)['spread_pct'].mean()
print(spread_evolution)
```

## Summary

**Tick data is best for**:
- ✓ Precise execution analysis at specific times
- ✓ Spread and slippage estimation
- ✓ Volume distribution within windows
- ✓ Microstructure analysis
- ✓ Realistic fill simulation

**Limitations**:
- ✗ Larger storage requirements than bar data
- ✗ Requires liquid options for meaningful data
- ✗ Rate limits slow bulk downloads
- ✗ Not suitable for long-term backtests (use bars)

For most strategy development, use **bar data**. Use **tick data** for critical execution points where precise spreads and timing matter.
