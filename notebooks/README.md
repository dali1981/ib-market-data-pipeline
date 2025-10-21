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

1. **DuckDB** - SQL queries, best for analytics and aggregations
2. **PyArrow** - Direct Parquet access, best for large scans
3. **Reader Repositories** - Convenient Python API, uses PyArrow internally

## Example Workflows

### Fetch and Query Equity Data

```python
import dlt
from dlt_ibapi import ib_historical_bars
from dlt_ibapi.repositories import EquityBarsReader

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
