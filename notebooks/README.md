# dlt-ibapi Notebooks

Interactive Jupyter notebooks demonstrating the usage of `dlt-ibapi` for fetching and querying market data from Interactive Brokers.

## Notebooks

### 1. Quickstart Guide (`01_quickstart.ipynb`)

**Purpose**: Learn the basics of `dlt-ibapi` and get started quickly.

**Topics Covered**:
- Setting up IB Gateway connection
- Fetching historical equity bars
- Capturing option chain snapshots
- Historical data backfilling with gap detection
- Querying saved Parquet data with DuckDB
- Visualizing market data

**Best For**: First-time users, getting familiar with the library

**Prerequisites**: IB Gateway/TWS running locally

---

### 2. Reading Data (`02_reading_data.ipynb`)

**Purpose**: Deep dive into querying Parquet data using different methods.

**Topics Covered**:
- Understanding Parquet file structure with Hive partitioning
- SQL queries with DuckDB
- Using Reader Repositories (Python API)
- Advanced PyArrow queries with predicate pushdown
- Performance comparison of different query methods
- Best practices for querying partitioned data

**Best For**: Users who want to efficiently query and analyze stored data

**Prerequisites**: Run `01_quickstart.ipynb` first to generate sample data

---

### 3. Calendar Spread Strategy - TMC Earnings (`03_calendar_spread_tmc_earnings.ipynb`)

**Purpose**: Demonstrate calendar spread strategy using real TMC earnings data.

**Topics Covered**:
- Loading hourly option bars for specific contracts
- Calendar spread construction (sell near-term, buy far-term)
- P&L tracking over time
- Exit timing analysis (before vs after earnings)
- IV crush visualization

**Best For**: Understanding options trading strategies with real data

**Prerequisites**: TMC option data backfilled

---

### 4. Calendar Spread Earnings Backtest (`04_calendar_spread_earnings_backtest.ipynb`)

**Purpose**: Backtest calendar spread strategy across multiple earnings events.

**Topics Covered**:
- Batch processing of earnings calendar
- Multi-event strategy backtesting
- Performance metrics and statistics
- Win rate and P&L distribution analysis

**Best For**: Evaluating strategy performance across many events

**Prerequisites**: Multiple earnings events and option data

---

### 5. Volatility Term Structure Analysis (`05_volatility_term_structure_earnings.ipynb`)

**Purpose**: Visualize implied volatility collapse around earnings events.

**Topics Covered**:
- Black-Scholes IV calculation using scipy
- Volatility smiles (IV across strikes)
- Volatility term structure (IV across maturities)
- IV collapse heatmaps
- Differential IV collapse analysis (calendar spread edge)

**Best For**: Understanding the volatility dynamics that make calendar spreads profitable

**Prerequisites**: Option data around earnings dates

**See Also**: [README_VOL_ANALYSIS.md](./README_VOL_ANALYSIS.md) for detailed documentation

---

### 6. IV Ratio Ranking (`06_iv_ratio_ranking.ipynb`)

**Purpose**: Rank trading opportunities by implied volatility ratio to predict profitability.

**Data**: Uses **hourly bars** for compatibility across all symbols

**Topics Covered**:
- Calculating IV for short and long legs at entry
- Computing IV ratio (short IV / long IV)
- Correlation analysis between IV ratio and P&L
- Quartile ranking of opportunities
- Identifying high-probability setups

**Best For**: Trade selection and opportunity ranking

**Prerequisites**: Earnings and option data

**Key Hypothesis**: Higher IV ratio at entry → better P&L (short-term options more "expensive" relative to long-term)

---

### 6b. IV Ratio Ranking - 5-Minute Bars (`06b_iv_ratio_ranking_5min.ipynb`)

**Purpose**: Same as 06, but with higher precision using 5-minute bars.

**Data**: Uses **5-minute bars** for more precise entry/exit timing

**Timing**: Entry 3:00pm, Exit 10:00am (same as 06)

**Key Differences from 06**:
- **Granularity**: 5-min bars vs hourly
- **Precision**: Entry at 3:00pm bar (not 3:00-4:00pm hourly bar)
- **Volume**: Shows when trades actually occurred within the hour
- **Spreads**: More accurate high-low ranges for spread estimation
- **Coverage**: May have fewer successful backtests (some symbols lack 5-min data)

**When to Use**:
- Use **06b** for liquid symbols with 5-min data (more precise analysis)
- Use **06** for broader coverage including less liquid symbols (hourly fallback)

**Best For**: High-precision analysis on liquid earnings options

**Prerequisites**: Earnings and 5-min option data

---

### 6c. IV Ratio Ranking - Adjusted Entry/Exit Times (`06c_iv_ratio_ranking_adjusted_times.ipynb`)

**Purpose**: Same as 06b, but with **realistic entry/exit times** for better execution.

**Data**: Uses **5-minute bars**

**Timing**:
- **Entry**: 3:55pm (5 minutes before close)
- **Exit**: 9:35am (5 minutes after open)

**Rationale**:

**Entry at 3:55pm** (instead of 3:00pm):
- Avoids 4:00pm closing auction volatility
- Still captures elevated IV before earnings
- More realistic execution (tighter spreads than last-minute rush)
- Less exposure to end-of-day order imbalances

**Exit at 9:35am** (instead of 10:00am):
- Captures overnight IV crush after AFTER_HOURS earnings
- Avoids 9:30am opening volatility spike
- First 5 minutes often chaotic - this waits for market to settle
- Earlier exit = less time decay, more conservative

**When to Use**:
- **Production/Live Trading**: Most realistic times for actual execution
- **Price Realism Analysis**: Tests if strategy works with executable prices
- **Conservative Analysis**: Earlier exit may show lower P&L but more realistic

**Comparison**:

| Version | Entry | Exit | Best For |
|---------|-------|------|----------|
| 06 | 3:00pm | 10:00am | Broad coverage, simple analysis |
| 06b | 3:00pm | 10:00am | Precision with 5-min data |
| **06c** | **3:55pm** | **9:35am** | **Realistic execution timing** |

**Best For**: Validating strategy with production-ready timing

**Prerequisites**: Earnings and 5-min option data

---

## Getting Started

### Installation

```bash
# Install dlt-ibapi
uv add dlt-ibapi

# Install Jupyter
uv add jupyter matplotlib pandas

# Or install with notebook dependencies
uv sync --extra notebooks
```

### Running Notebooks

```bash
# Start Jupyter Lab
jupyter lab

# Or Jupyter Notebook
jupyter notebook
```

Then open the notebooks in order:
1. Start with `01_quickstart.ipynb`
2. Explore `02_reading_data.ipynb` for advanced queries

### Data Storage

All notebooks store data in the `../data/` directory using Parquet files with Hive-style partitioning:

```
data/
├── stocks/
│   └── equity_bars_backfill/
│       └── date=2025-10-20/
│           ├── symbol=AAPL/*.parquet
│           └── symbol=MSFT/*.parquet
└── options/
    ├── option_bars_backfill/
    │   └── date=2025-10-20/
    │       └── symbol=AAPL/*.parquet
    └── option_chain_snapshot/
        └── date=2025-10-20/
            └── underlying=SPY/*.parquet
```

## Key Concepts

### Parquet Storage

`dlt-ibapi` uses Parquet files for data storage with the following benefits:

- **10x better compression** - Typical OHLCV data compresses very well
- **Predicate pushdown** - Only reads relevant partition directories
- **Cloud-ready** - Works with S3, GCS, Azure Blob Storage
- **No persistent database** - DuckDB in-memory for all queries

### Hive Partitioning

Data is partitioned by:
- **date**: ISO format (YYYY-MM-DD)
- **symbol**: Stock/underlying symbol

This enables fast filtering: `WHERE symbol = 'AAPL' AND date >= '2025-10-01'`

### Query Methods

1. **Reader API** (`dlt_ibapi.read`) - Recommended Python API for querying data
2. **DuckDB** - SQL queries, best for analytics and aggregations
3. **PyArrow** - Direct Parquet access, best for large scans with custom filters

## Example Workflows

### Fetch and Query Equity Data

```python
import dlt
from dlt_ibapi import ib_historical_bars
from dlt_ibapi.read import EquityBarsReader

# 1. Fetch data
pipeline = dlt.pipeline(
    pipeline_name="ib_market_data",
    destination=dlt.destinations.filesystem(bucket_url="data"),
    dataset_name="stocks",
)
data = ib_historical_bars(symbol="AAPL", ...)
pipeline.run(data, loader_file_format="parquet")

# 2. Query with Reader API
reader = EquityBarsReader("data", "stocks")
bars = reader.get_bars(symbol="AAPL", bar_size="1 day")
symbols = reader.get_available_symbols()
```

### Backfill Historical Data

```python
from dlt_ibapi.backfill.resources import backfill_equity_bars
from datetime import date, timedelta

# Backfill with gap detection (idempotent)
data = backfill_equity_bars(
    symbol="MSFT",
    database_path="data",
    dataset_name="stocks",
    start_date=date.today() - timedelta(days=30),
    end_date=date.today(),
    bar_size="1 day",
)

pipeline.run(data, loader_file_format="parquet")
```

### Query with DuckDB

```python
import duckdb

conn = duckdb.connect(":memory:")
df = conn.execute("""
    SELECT * FROM parquet_scan('data/stocks/**/*.parquet', hive_partitioning=true)
    WHERE symbol = 'AAPL' AND date >= '2025-10-01'
    ORDER BY time
""").df()
```

## Troubleshooting

### IB Gateway Connection Issues

```python
# Check if IB Gateway is running
from ib_async import IB

ib = IB()
try:
    ib.connect('127.0.0.1', 7497, clientId=1)
    print("✓ Connected to IB Gateway")
    ib.disconnect()
except Exception as e:
    print(f"✗ Connection failed: {e}")
    print("  Make sure IB Gateway/TWS is running")
    print("  Check API settings: Enable ActiveX and Socket Clients")
```

### No Data Found

If queries return no data:
1. Run `01_quickstart.ipynb` to generate sample data
2. Check the `../data/` directory exists
3. Verify Parquet files were created: `ls -R ../data/`

### Permission Errors

```bash
# Ensure data directory is writable
chmod -R u+w ../data/
```

## Additional Resources

- [Main Documentation](../README.md)
- [Backfill Guide](../docs/BACKFILL_GUIDE.md)
- [API Reference](../docs/API_REFERENCE.md)
- [Example Scripts](../examples/)

## Contributing

If you create new notebooks, please:
1. Follow the naming convention: `##_topic_name.ipynb`
2. Include clear markdown documentation
3. Add to this README
4. Test all cells execute without errors
