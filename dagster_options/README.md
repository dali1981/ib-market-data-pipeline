# Dagster Options Pipeline

Complete Dagster pipeline for multi-ticker option data collection with intelligent contract selection.

## Overview

This pipeline automates the process of:
1. Resolving ticker symbols to IB contracts
2. Fetching historical stock data
3. Capturing option chain snapshots
4. Selecting option contracts using multiple delta-targeting strategies
5. Backfilling historical option data

## Features

- **Independent Pipeline**: Runs standalone, not tied to earnings calendar
- **On-Demand Execution**: Manual trigger via Dagster UI or API
- **Smart Contract Resolution**: Uses IB API with intelligent caching
- **Gap Detection**: Only fetches missing historical data
- **Multiple Selection Strategies**: Compare 3 different delta-targeting methods
- **Flexible Configuration**: Easy to customize via config.py

## Architecture

### Assets (Dependency Graph)

```
ticker_contracts
    ├── stock_historical_data
    └── option_chain_snapshots
            └── selected_option_contracts
                    └── option_historical_data
```

### Selection Strategies

The pipeline implements **three delta-targeting strategies** for comparison:

1. **Closest Match**: Simple heuristic approximation
   - Fast, no calculations required
   - Estimates delta from strike-to-spot relationship
   - Good for quick prototyping

2. **Black-Scholes Calculated**: Physics-based delta calculation
   - Uses Black-Scholes model
   - Requires volatility and risk-free rate estimates
   - Accurate for European-style options

3. **IB API Greeks**: Live market data from IB
   - Uses IB's calculated greeks
   - Most accurate but requires market data subscription
   - Slower due to API rate limits

## Quick Start

### 1. Setup

Ensure IB Gateway or TWS is running:
```bash
# IB Gateway should be listening on:
# Paper Trading: localhost:7497
# Live Trading: localhost:7496
```

### 2. Configure Tickers

Edit `dagster_options/example_tickers.txt`:
```
# One ticker per line
# Lines starting with # are comments

AAPL
MSFT
GOOGL
```

### 3. Run Pipeline

#### Via Dagster UI

```bash
# Start Dagster UI
dagster dev -f dagster_options/definitions.py

# Navigate to http://localhost:3000
# Click "Materialize All" or select specific assets
```

#### Via CLI

```bash
# Run full pipeline
dagster asset materialize -f dagster_options/definitions.py --select "*"

# Run specific job
dagster job execute -f dagster_options/definitions.py -j full_pipeline_job
```

### 4. Query Results

```python
from dlt_ibapi.repositories.equity_bars import EquityBarsReader
from dlt_ibapi.repositories.option_chain import OptionChainSnapshotReader

# Query stock data
stock_reader = EquityBarsReader(".dlt-ibapi/data", "stocks")
aapl_bars = stock_reader.get_bars("AAPL", "1 day")

# Query option chains
chain_reader = OptionChainSnapshotReader(".dlt-ibapi/data", "option_chains")
aapl_chain = chain_reader.get_chain_for_date("AAPL", as_of=date.today())
```

## Configuration

### Default Configuration

```python
from dagster_options.config import get_default_config

config = get_default_config()

# Ticker source
config.ticker_source.file_path = "dagster_options/example_tickers.txt"

# Stock data
config.stock_config.lookback_days = 30
config.stock_config.bar_size = "1 day"

# Option chains
config.chain_config.min_dte = 7
config.chain_config.max_dte = 365

# Delta selection
config.delta_config.target_deltas = [0.25, 0.50, 0.75]
config.delta_config.include_calls = True
config.delta_config.include_puts = True

# Option data
config.option_config.lookback_days = 7
config.option_config.bar_size = "1 hour"
```

### Custom Configuration

```python
# config.py
from dagster_options.config import OptionsPipelineConfig, DeltaSelectionConfig

custom_config = OptionsPipelineConfig(
    ticker_source=TickerSourceConfig(
        source_type="file",
        file_path="my_custom_tickers.txt"
    ),
    delta_config=DeltaSelectionConfig(
        target_deltas=[0.25, 0.50],  # Only 25Δ and ATM
        include_puts=False,  # Calls only
    ),
)
```

## Pipeline Steps

### Asset 1: ticker_contracts

Resolves ticker symbols to IB contracts with caching.

**Output**: DataFrame with columns
- `symbol`: Ticker symbol
- `conid`: IB contract ID
- `exchange`: Primary exchange
- `currency`: Trading currency
- `sec_type`: Security type (STK)

**Process**:
1. Load tickers from configured source
2. Check contract cache
3. If missing, call IB API (match_symbol + contract_details)
4. Save to cache automatically
5. Return resolved contracts

### Asset 2: stock_historical_data

Fetches daily historical bars with gap detection.

**Output**: Summary statistics dictionary

**Process**:
1. For each resolved contract
2. Detect gaps in existing data using `EquityBarsReader`
3. Fetch missing bars via `backfill_equity_bars`
4. Store in Parquet with partitioning by date and symbol

**Data Location**: `.dlt-ibapi/data/stocks/`

### Asset 3: option_chain_snapshots

Captures option chain snapshots (expirations + strikes).

**Output**: Summary statistics dictionary

**Process**:
1. For each ticker
2. Request option params via IB SecDef API
3. Filter expirations by DTE (7-365 days default)
4. Store snapshot with all strikes and expirations

**Data Location**: `.dlt-ibapi/data/option_chains/`

### Asset 4: selected_option_contracts

Selects contracts using multiple delta strategies.

**Output**: DataFrame with columns
- `underlying`: Underlying symbol
- `expiry`: Expiration date
- `strike`: Strike price
- `right`: "C" or "P"
- `strategy`: Selection strategy name
- `delta`: Calculated delta (if available)
- `reason`: Selection reason tag

**Process**:
1. Get latest stock price from historical data
2. Load option chain snapshot
3. For each expiration:
   - Apply enabled strategies (closest_match, black_scholes, ib_greeks)
   - Select strikes matching target deltas
   - Tag with strategy name
4. Return consolidated DataFrame

### Asset 5: option_historical_data

Backfills historical bars for selected contracts.

**Output**: Summary statistics dictionary

**Process**:
1. Group selected contracts by underlying
2. For each contract (underlying, expiry, strike, right):
   - Detect gaps using `OptionBarsReader`
   - Fetch missing bars via IB API
   - Store in Parquet

**Data Location**: `.dlt-ibapi/data/options/`

## Available Jobs

### Full Jobs

- **`full_pipeline_job`**: Complete pipeline from ticker resolution to option data
- **`process_tickers_job`**: Alias for full_pipeline_job

### Partial Jobs

- **`resolve_contracts_job`**: Only resolve tickers to contracts
- **`fetch_market_data_job`**: Resolve + fetch stock data + option chains
- **`select_contracts_job`**: Resolve + fetch + select contracts (no option data)

## Data Storage

All data is stored in Parquet format with Hive partitioning:

```
.dlt-ibapi/
├── data/
│   ├── stocks/
│   │   └── historical_bars/
│   │       ├── symbol=AAPL/
│   │       │   └── date=2025-01-15/
│   │       │       └── data.parquet
│   │       └── ...
│   ├── option_chains/
│   │   └── option_chain_snapshot/
│   │       └── data.parquet
│   └── options/
│       └── option_bars_backfill/
│           └── data.parquet
└── cache/
    └── contracts/
        └── sec_type=STK/
            └── data.parquet
```

## Querying Data

### Stock Data

```python
from dlt_ibapi.repositories.equity_bars import EquityBarsReader
from datetime import date

reader = EquityBarsReader(".dlt-ibapi/data", "stocks")

# Get bars for symbol
bars = reader.get_bars(
    symbol="AAPL",
    bar_size="1 day",
    start_date=date(2025, 1, 1),
    end_date=date(2025, 1, 15),
)

# Get available symbols
symbols = reader.get_available_symbols()

# Get date range for symbol
start, end = reader.get_date_range("AAPL", "1 day")
```

### Option Chain Data

```python
from dlt_ibapi.repositories.option_chain import OptionChainSnapshotReader
from datetime import date

reader = OptionChainSnapshotReader(".dlt-ibapi/data", "option_chains")

# Get chain for date
chain = reader.get_chain_for_date(
    underlying="AAPL",
    as_of=date.today(),
    min_dte=7,
    max_dte=60,
)

# Get available expirations
expirations = reader.get_available_expirations(
    underlying="AAPL",
    as_of=date.today(),
)

# Get strikes for expiration
strikes = reader.get_strikes_for_expiry(
    underlying="AAPL",
    as_of=date.today(),
    expiry=date(2025, 2, 21),
)
```

### Selected Contracts

The selected contracts are returned as a DataFrame from the asset:

```python
# Access via Dagster
from dagster import materialize
from dagster_options.assets import selected_option_contracts

result = materialize([selected_option_contracts])
contracts_df = result.output_for_node("selected_option_contracts")

# Analyze selection strategies
contracts_df.groupby("strategy").size()
contracts_df[contracts_df["strategy"] == "black_scholes"]
```

## Troubleshooting

### IB Connection Issues

```bash
# Check IB Gateway is running
ps aux | grep ibgateway

# Verify port
netstat -an | grep 7497
```

### No Contracts Resolved

- Check ticker symbols are valid
- Verify IB Gateway is connected
- Check contract cache permissions
- Review Dagster logs for API errors

### Missing Option Data

- Ensure ticker has options (not all stocks do)
- Check DTE filters (min_dte/max_dte)
- Verify option chain snapshot exists
- Some ETFs may have limited option chains

### Slow Performance

- IB API has rate limits (50 req/sec for contract details)
- Option data fetching is sequential
- Consider reducing number of tickers or expirations
- Use contract cache to avoid re-resolution

## Advanced Usage

### Custom Ticker Source

```python
# ticker_loader.py
def load_from_database():
    import sqlite3
    conn = sqlite3.connect("tickers.db")
    cursor = conn.execute("SELECT symbol FROM watchlist WHERE active=1")
    return [row[0] for row in cursor.fetchall()]

# config.py
config.ticker_source.source_type = "database"
config.ticker_source.db_connection_string = "sqlite:///tickers.db"
config.ticker_source.db_query = "SELECT symbol FROM watchlist WHERE active=1"
```

### Runtime Configuration

```python
# Override config at runtime
from dagster import RunConfig

run_config = RunConfig(
    ops={
        "ticker_contracts": {
            "config": {
                "ticker_file": "custom_list.txt"
            }
        }
    }
)

# Execute with custom config
dagster job execute -f definitions.py -j full_pipeline_job --config run_config.yaml
```

## Integration with Earnings Calendar

While this pipeline is independent, it can be integrated:

```python
# Load tickers from earnings calendar
from earnings_calendar import nasdaq_earnings_source

earnings = nasdaq_earnings_source()
tickers = earnings["symbol"].unique().tolist()

# Write to ticker file
with open("earnings_tickers.txt", "w") as f:
    f.write("\n".join(tickers))

# Update config
config.ticker_source.file_path = "earnings_tickers.txt"
```

## References

- [DLT Documentation](https://dlthub.com)
- [Dagster Documentation](https://docs.dagster.io)
- [IB API Documentation](https://interactivebrokers.github.io/tws-api/)
- [Black-Scholes Model](https://en.wikipedia.org/wiki/Black%E2%80%93Scholes_model)

## Support

For issues or questions:
- Check Dagster logs
- Review IB Gateway connection
- Verify configuration in config.py
- Inspect data with ParquetReaderBase
