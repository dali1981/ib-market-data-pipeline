# dlt-ibapi

DLT connector for Interactive Brokers - ingest market data from IB Gateway/TWS into data pipelines.

## Table of Contents

- [Overview](#overview)
- [Installation](#installation)
- [Prerequisites](#prerequisites)
- [Quick Start](#quick-start)
- [Configuration](#configuration)
  - [YAML Configuration](#method-1-yaml-configuration-recommended)
  - [Environment Variables](#method-2-environment-variables)
  - [Python Configuration](#method-3-python-configuration-pydantic-models)
  - [CLI Commands](#method-4-cli-commands)
- [API Reference](#api-reference)
- [Data Schema](#data-schema)
- [Working with Loaded Data](#working-with-loaded-data)
- [Data Transformation](#data-transformation)
- [Architecture](#architecture)
- [CLI Reference](#cli-reference)
- [Development](#development)
- [Examples](#examples)
- [Troubleshooting](#troubleshooting)

## Overview

`dlt-ibapi` is a [dlt](https://dlthub.com/) source connector that allows you to easily extract market data from Interactive Brokers and load it into any destination (DuckDB, PostgreSQL, Snowflake, BigQuery, etc.).

Built on top of `ib-connector`, it provides clean, composable DLT resources for:
- Historical bar data (OHLCV)
- Contract details and specifications
- Option chains and parameters
- Market data snapshots

## Installation

```bash
# Install from source (development)
cd /path/to/ib-connector
uv sync

cd /path/to/dlt-ibapi
uv sync

# Or install as a dependency in your project
uv add dlt-ibapi

# Verify installation
dlt-ibapi version
```

After installation, the `dlt-ibapi` CLI command will be available.

## Prerequisites

1. **IB Gateway or TWS** running locally or remotely
2. **API connections enabled** in IB Gateway/TWS settings
3. **Python >= 3.10**

## Quick Start

### Basic Historical Data Pipeline

```python
import dlt
from dlt_ibapi import ib_historical_bars

# Create a pipeline to DuckDB
pipeline = dlt.pipeline(
    pipeline_name="ib_market_data",
    destination="duckdb",
    dataset_name="stocks",
)

# Fetch AAPL historical bars
data = ib_historical_bars(
    symbol="AAPL",
    exchange="SMART",
    currency="USD",
)

# Run the pipeline
info = pipeline.run(data)
print(info)
```

### Multiple Symbols Pipeline

```python
import dlt
from dlt_ibapi import ib_source

# Define symbols to track
symbols = ["AAPL", "GOOGL", "MSFT", "TSLA"]

# Create combined source
source = ib_source(
    symbols=symbols,
    include_historical=True,
    include_contract_details=True,
)

# Load to PostgreSQL
pipeline = dlt.pipeline(
    pipeline_name="ib_stocks",
    destination="postgres",
    dataset_name="market_data",
)

info = pipeline.run(source)
print(info)
```

### Contract Details

```python
from dlt_ibapi import ib_contract_details

# Fetch contract specifications
contracts = ib_contract_details(
    symbols=["AAPL", "GOOGL"],
    exchange="SMART",
    currency="USD",
)

pipeline = dlt.pipeline(
    pipeline_name="ib_contracts",
    destination="duckdb",
    dataset_name="reference_data",
)

pipeline.run(contracts)
```

### Option Chain Data

```python
from dlt_ibapi import ib_option_chain

# Fetch option chain for AAPL (you need the contract ID)
options = ib_option_chain(
    symbol="AAPL",
    conid=265598,  # AAPL contract ID
    exchange="SMART",
)

pipeline.run(options)
```

## Configuration

`dlt-ibapi` supports multiple ways to configure your connection and data requests:

1. **YAML config files** (recommended for projects)
2. **Environment variables** (recommended for secrets/deployment)
3. **Python code** (Pydantic models)
4. **CLI commands** (for quick testing)

### Configuration Hierarchy

Settings are loaded with the following priority (highest to lowest):

1. **Explicitly passed config objects** in Python code
2. **Environment variables** (`IB_HOST`, `IB_PORT`, etc.)
3. **User project config** (`.dlt-ibapi/ib_gateway.yaml` in project root)
4. **Default config** (shipped with package)

---

### Method 1: YAML Configuration (Recommended)

Initialize a config file in your project:

```bash
# Create .dlt-ibapi/ib_gateway.yaml in current directory
dlt-ibapi init

# Or specify a different directory
dlt-ibapi init --dir /path/to/project
```

This creates `.dlt-ibapi/ib_gateway.yaml`:

```yaml
connection:
  host: 127.0.0.1
  port: 4002        # IB Gateway Paper Trading
  client_id: 1
  ready_timeout: 10.0

historical:
  duration: "1 D"
  bar_size: "1 min"
  what_to_show: "TRADES"
  use_rth: true
  timeout: 20.0

market_data:
  generic_ticks: ""
  snapshot: true
  timeout: 10.0

option_chain:
  exchange: ""
  timeout: 10.0
```

**Using YAML config in Python:**

```python
import dlt
from dlt_ibapi import ib_historical_bars

# Config is automatically loaded from .dlt-ibapi/ib_gateway.yaml
data = ib_historical_bars(symbol="AAPL")

pipeline = dlt.pipeline(
    pipeline_name="ib_market_data",
    destination="duckdb",
    dataset_name="stocks",
)

pipeline.run(data)
```

**View your current configuration:**

```bash
dlt-ibapi show-config
```

---

### Method 2: Environment Variables

Set environment variables to override config file settings:

```bash
# Connection settings
export IB_HOST=127.0.0.1
export IB_PORT=4002
export IB_CLIENT_ID=1
export IB_READY_TIMEOUT=10.0

# Historical data settings
export IB_HIST_DURATION="1 W"
export IB_HIST_BAR_SIZE="5 mins"
export IB_HIST_WHAT_TO_SHOW="TRADES"
export IB_HIST_USE_RTH=true
export IB_HIST_TIMEOUT=20.0

# Market data settings
export IB_MARKET_GENERIC_TICKS=""
export IB_MARKET_SNAPSHOT=true
export IB_MARKET_TIMEOUT=10.0

# Option chain settings
export IB_OPTION_EXCHANGE=""
export IB_OPTION_TIMEOUT=10.0
```

**Using environment variables in Python:**

```python
# Environment variables are automatically loaded
from dlt_ibapi import ib_historical_bars

# Will use IB_HOST, IB_PORT, etc. from environment
data = ib_historical_bars(symbol="AAPL")
```

---

### Method 3: Python Configuration (Pydantic Models)

For programmatic control, use Pydantic config models directly:

```python
from dlt_ibapi import ib_historical_bars
from dlt_ibapi.config import IBConnectionConfig, IBHistoricalConfig

# Connection config
conn_config = IBConnectionConfig(
    host="127.0.0.1",
    port=7497,  # TWS Paper Trading
    client_id=1,
    ready_timeout=10.0,
)

# Historical data config
hist_config = IBHistoricalConfig(
    duration="1 W",           # 1 week of data
    bar_size="5 mins",        # 5-minute bars
    what_to_show="TRADES",    # Trade data
    use_rth=True,             # Regular trading hours only
    timeout=30.0,
)

# Pass configs explicitly (overrides YAML and env vars)
data = ib_historical_bars(
    symbol="AAPL",
    connection_config=conn_config,
    hist_config=hist_config,
)
```

**Using the config loader:**

```python
from dlt_ibapi.config_loader import get_connection_config, get_historical_config

# Load from YAML + env vars
conn_config = get_connection_config()
hist_config = get_historical_config()

# Use configs
data = ib_historical_bars(
    symbol="AAPL",
    connection_config=conn_config,
    hist_config=hist_config,
)
```

---

### Method 4: CLI Commands

The CLI provides commands for testing and quick data fetching:

**Test your connection:**

```bash
# Test with config file settings
dlt-ibapi test-connection

# Override connection settings
dlt-ibapi test-connection --host 127.0.0.1 --port 7497 --client-id 2
```

**Fetch data manually:**

```bash
# Fetch historical data for symbols
dlt-ibapi fetch AAPL GOOGL MSFT

# Save to file
dlt-ibapi fetch AAPL --output aapl_data.json

# Fetch contract details
dlt-ibapi fetch AAPL GOOGL --type contract -o contracts.json

# Use custom config file
dlt-ibapi fetch TSLA --config /path/to/custom_config.yaml
```

**View CLI help:**

```bash
dlt-ibapi --help
dlt-ibapi init --help
dlt-ibapi fetch --help
```

## API Reference

### Resources

#### `ib_historical_bars`
Fetches OHLCV bar data for a single symbol.

```python
@dlt.resource(name="historical_bars")
def ib_historical_bars(
    symbol: str,
    exchange: str = "SMART",
    currency: str = "USD",
    sec_type: str = "STK",
    end_date: Optional[str] = None,
    connection_config: Optional[IBConnectionConfig] = None,
    hist_config: Optional[IBHistoricalConfig] = None,
) -> Iterator[dict]
```

**Parameters:**
- `symbol` (str): Stock symbol (e.g., "AAPL", "GOOGL")
- `exchange` (str): Exchange routing (default: "SMART")
- `currency` (str): Currency code (default: "USD")
- `sec_type` (str): Security type (default: "STK" for stocks)
- `end_date` (str, optional): End date for historical data (format: "YYYYMMDD HH:mm:ss" or empty for now)
- `connection_config` (IBConnectionConfig, optional): IB connection settings
- `hist_config` (IBHistoricalConfig, optional): Historical data request settings

**Returns:** Iterator yielding normalized bar records (see Data Schema below)

**Example:**
```python
data = ib_historical_bars(
    symbol="TSLA",
    exchange="SMART",
    currency="USD",
    end_date="20250115 16:00:00",
)
```

---

#### `ib_contract_details`
Fetches detailed contract specifications for multiple symbols.

```python
@dlt.resource(name="contract_details")
def ib_contract_details(
    symbols: List[str],
    exchange: str = "SMART",
    currency: str = "USD",
    sec_type: str = "STK",
    connection_config: Optional[IBConnectionConfig] = None,
) -> Iterator[dict]
```

**Parameters:**
- `symbols` (List[str]): List of symbols to fetch
- `exchange` (str): Exchange (default: "SMART")
- `currency` (str): Currency (default: "USD")
- `sec_type` (str): Security type (default: "STK")
- `connection_config` (IBConnectionConfig, optional): IB connection settings

**Returns:** Iterator yielding contract detail records

**Example:**
```python
contracts = ib_contract_details(
    symbols=["AAPL", "MSFT", "GOOGL"],
    exchange="SMART",
    currency="USD",
)
```

---

#### `ib_option_chain`
Fetches option chain parameters including strikes and expirations.

```python
@dlt.resource(name="option_chain")
def ib_option_chain(
    symbol: str,
    conid: int,
    sec_type: str = "STK",
    exchange: str = "",
    connection_config: Optional[IBConnectionConfig] = None,
    option_config: Optional[IBOptionChainConfig] = None,
) -> Iterator[dict]
```

**Parameters:**
- `symbol` (str): Underlying symbol
- `conid` (int): Contract ID of underlying asset (get from contract_details)
- `sec_type` (str): Security type (default: "STK")
- `exchange` (str): Exchange (default: "")
- `connection_config` (IBConnectionConfig, optional): IB connection settings
- `option_config` (IBOptionChainConfig, optional): Option chain request settings

**Returns:** Iterator yielding option parameter records

**Example:**
```python
options = ib_option_chain(
    symbol="AAPL",
    conid=265598,
    exchange="SMART",
)
```

---

#### `ib_market_data_snapshot`
Fetches market data snapshots for multiple symbols.

```python
@dlt.resource(name="market_data_snapshot")
def ib_market_data_snapshot(
    symbols: List[str],
    exchange: str = "SMART",
    currency: str = "USD",
    connection_config: Optional[IBConnectionConfig] = None,
    market_config: Optional[IBMarketDataConfig] = None,
) -> Iterator[dict]
```

**Parameters:**
- `symbols` (List[str]): List of stock symbols
- `exchange` (str): Exchange (default: "SMART")
- `currency` (str): Currency (default: "USD")
- `connection_config` (IBConnectionConfig, optional): IB connection settings
- `market_config` (IBMarketDataConfig, optional): Market data request settings

**Returns:** Iterator yielding snapshot records

**Example:**
```python
snapshots = ib_market_data_snapshot(
    symbols=["SPY", "QQQ", "DIA"],
    exchange="SMART",
)
```

---

### Sources

#### `ib_source`
Combined DLT source that orchestrates multiple resources.

```python
@dlt.source(name="ib_source")
def ib_source(
    symbols: List[str],
    include_historical: bool = True,
    include_contract_details: bool = True,
    include_option_chain: bool = False,
    connection_config: Optional[IBConnectionConfig] = None,
) -> List[Any]
```

**Parameters:**
- `symbols` (List[str]): List of symbols to fetch
- `include_historical` (bool): Include historical bars (default: True)
- `include_contract_details` (bool): Include contract details (default: True)
- `include_option_chain` (bool): Include option chain data (default: False)
- `connection_config` (IBConnectionConfig, optional): IB connection settings

**Returns:** List of DLT resources to be loaded

**Example:**
```python
source = ib_source(
    symbols=["AAPL", "GOOGL"],
    include_historical=True,
    include_contract_details=True,
)
pipeline.run(source)
```

---

### Configuration Classes

#### `IBConnectionConfig`
Configuration for IB Gateway/TWS connection.

```python
class IBConnectionConfig(BaseModel):
    host: str = "127.0.0.1"           # IB Gateway/TWS host
    port: int = 7497                  # IB Gateway/TWS port
    client_id: int = 1                # Client ID for connection
    ready_timeout: float = 10.0       # Timeout for connection ready (seconds)
```

**Common Port Numbers:**
- `7497`: TWS Paper Trading
- `7496`: TWS Live Trading
- `4002`: IB Gateway Paper Trading
- `4001`: IB Gateway Live Trading

---

#### `IBHistoricalConfig`
Configuration for historical data requests.

```python
class IBHistoricalConfig(BaseModel):
    duration: str = "1 D"              # Duration string
    bar_size: str = "1 min"            # Bar size
    what_to_show: str = "TRADES"       # Data type
    use_rth: bool = True               # Regular trading hours only
    timeout: float = 20.0              # Request timeout (seconds)
```

**Duration Options:** "1 D", "1 W", "1 M", "1 Y", etc.
**Bar Size Options:** "1 secs", "5 secs", "10 secs", "15 secs", "30 secs", "1 min", "2 mins", "3 mins", "5 mins", "10 mins", "15 mins", "20 mins", "30 mins", "1 hour", "2 hours", "3 hours", "4 hours", "8 hours", "1 day", "1 week", "1 month"
**What to Show Options:** "TRADES", "MIDPOINT", "BID", "ASK", "BID_ASK", "HISTORICAL_VOLATILITY", "OPTION_IMPLIED_VOLATILITY"

---

#### `IBMarketDataConfig`
Configuration for market data snapshots.

```python
class IBMarketDataConfig(BaseModel):
    generic_ticks: str = ""            # Generic tick types
    snapshot: bool = True              # Request snapshot only
    timeout: float = 10.0              # Request timeout (seconds)
```

---

#### `IBOptionChainConfig`
Configuration for option chain requests.

```python
class IBOptionChainConfig(BaseModel):
    exchange: str = ""                 # Exchange for option params
    timeout: float = 10.0              # Request timeout (seconds)
```

## Data Schema

All data is normalized and cleaned by transformer functions before loading. Timestamps are in ISO format, and all numeric fields are properly typed.

### Historical Bars
Output schema from `ib_historical_bars()`:

```python
{
    "symbol": str,              # Stock symbol (e.g., "AAPL")
    "exchange": str,            # Exchange (e.g., "SMART")
    "currency": str,            # Currency code (e.g., "USD")
    "timestamp": str,           # ISO format timestamp
    "open": float,              # Opening price
    "high": float,              # High price
    "low": float,               # Low price
    "close": float,             # Closing price
    "volume": int,              # Volume traded
    "wap": float | None,        # Weighted average price (optional)
    "bar_count": int | None,    # Number of trades in bar (optional)
}
```

**Example Record:**
```python
{
    "symbol": "AAPL",
    "exchange": "SMART",
    "currency": "USD",
    "timestamp": "2025-01-15 09:30:00",
    "open": 185.50,
    "high": 186.20,
    "low": 185.30,
    "close": 186.00,
    "volume": 1250000,
    "wap": 185.85,
    "bar_count": 3420
}
```

---

### Contract Details
Output schema from `ib_contract_details()`:

```python
{
    "symbol": str,              # Stock symbol
    "contract_id": int,         # IB contract ID (conId)
    "local_symbol": str,        # Local trading symbol
    "trading_class": str,       # Trading class
    "sec_type": str,            # Security type (e.g., "STK")
    "exchange": str,            # Exchange
    "primary_exchange": str,    # Primary exchange
    "currency": str,            # Currency
    "long_name": str,           # Full company name
    "category": str,            # Industry category
    "subcategory": str,         # Industry subcategory
    "industry": str | None,     # Industry (optional)
    "min_tick": float,          # Minimum price tick
    "price_magnifier": int,     # Price magnifier
    "order_types": str,         # Allowed order types (comma-separated)
    "valid_exchanges": str,     # Valid exchanges (comma-separated)
    "market_name": str,         # Market name
    "fetched_at": str,          # ISO format timestamp when fetched
}
```

**Example Record:**
```python
{
    "symbol": "AAPL",
    "contract_id": 265598,
    "local_symbol": "AAPL",
    "trading_class": "NMS",
    "sec_type": "STK",
    "exchange": "SMART",
    "primary_exchange": "NASDAQ",
    "currency": "USD",
    "long_name": "APPLE INC",
    "category": "Technology",
    "subcategory": "Computers",
    "industry": "Computer Hardware",
    "min_tick": 0.01,
    "price_magnifier": 1,
    "order_types": "ACTIVETIM,AD,ADJUST...",
    "valid_exchanges": "SMART,AMEX,NYSE...",
    "market_name": "NMS",
    "fetched_at": "2025-01-15T14:30:00.123456"
}
```

---

### Option Chain Parameters
Output schema from `ib_option_chain()`:

```python
{
    "underlying_symbol": str,   # Underlying stock symbol
    "underlying_conid": int,    # Underlying contract ID
    "exchange": str,            # Exchange
    "trading_class": str,       # Trading class
    "multiplier": str,          # Contract multiplier
    "expirations": List[str],   # List of expiration dates
    "strikes": List[float],     # List of strike prices
    "expiration_count": int,    # Number of expirations
    "strike_count": int,        # Number of strikes
    "fetched_at": str,          # ISO format timestamp when fetched
}
```

**Example Record:**
```python
{
    "underlying_symbol": "AAPL",
    "underlying_conid": 265598,
    "exchange": "SMART",
    "trading_class": "AAPL",
    "multiplier": "100",
    "expirations": ["20250117", "20250124", "20250131"],
    "strikes": [170.0, 175.0, 180.0, 185.0, 190.0],
    "expiration_count": 3,
    "strike_count": 5,
    "fetched_at": "2025-01-15T14:30:00.123456"
}
```

---

### Market Data Snapshot
Output schema from `ib_market_data_snapshot()`:

```python
{
    "symbol": str,              # Stock symbol
    "exchange": str,            # Exchange
    "currency": str,            # Currency
    "contract_id": int,         # Contract ID
    "local_symbol": str,        # Local symbol
    "long_name": str,           # Company name
    "timestamp": str,           # ISO format timestamp
}
```

**Example Record:**
```python
{
    "symbol": "AAPL",
    "exchange": "SMART",
    "currency": "USD",
    "contract_id": 265598,
    "local_symbol": "AAPL",
    "long_name": "APPLE INC",
    "timestamp": "2025-01-15T14:30:00.123456"
}
```

## Working with Loaded Data

Once data is loaded, you can query it using SQL or pandas:

### Query with DuckDB

```python
import dlt
import duckdb

# After running your pipeline
pipeline = dlt.pipeline(
    pipeline_name="ib_market_data",
    destination="duckdb",
    dataset_name="stocks",
)

# Connect to the DuckDB database
conn = duckdb.connect(f"{pipeline.pipeline_name}.duckdb")

# Query historical bars
result = conn.execute("""
    SELECT symbol, timestamp, close, volume
    FROM stocks.historical_bars
    WHERE symbol = 'AAPL'
    ORDER BY timestamp DESC
    LIMIT 10
""").fetchdf()

print(result)
```

### Query with Pandas

```python
import dlt
import duckdb

pipeline = dlt.pipeline(
    pipeline_name="ib_market_data",
    destination="duckdb",
    dataset_name="stocks",
)

# Load data into pandas DataFrame
with duckdb.connect(f"{pipeline.pipeline_name}.duckdb") as conn:
    df = conn.execute("SELECT * FROM stocks.historical_bars").fetchdf()

# Analyze with pandas
print(df.describe())
print(df.groupby('symbol')['volume'].mean())
```

### Incremental Loading

For ongoing data collection, use DLT's incremental loading:

```python
import dlt
from dlt_ibapi import ib_historical_bars

# Use write_disposition for incremental loading
data = ib_historical_bars(
    symbol="AAPL",
    exchange="SMART",
)

pipeline = dlt.pipeline(
    pipeline_name="ib_incremental",
    destination="duckdb",
    dataset_name="stocks",
)

# Append new data without duplicates
info = pipeline.run(data, write_disposition="append")
```

---

## Data Transformation

The connector uses transformer functions in `src/dlt_ibapi/transformers.py` to normalize IB API data:

### Available Transformers

#### `normalize_bar_data()`
Transforms raw bar data from IB API into clean OHLCV records with consistent types and timestamps.

**Location:** `src/dlt_ibapi/transformers.py:7`

#### `normalize_contract_details()`
Extracts contract information from IB ContractDetails objects into flat, queryable dictionaries.

**Location:** `src/dlt_ibapi/transformers.py:35`

#### `normalize_option_params()`
Structures option chain data including strikes, expirations, and multipliers.

**Location:** `src/dlt_ibapi/transformers.py:70`

#### `normalize_tick_data()`
Handles various tick types (price, size, string, option) and structures them appropriately.

**Location:** `src/dlt_ibapi/transformers.py:96`

All transformers ensure:
- Consistent data types (floats, ints, strings)
- ISO format timestamps
- Null handling for optional fields
- Flat structure for easy querying

---

## Architecture

```
dlt-ibapi (DLT connector)
    ↓ depends on
ib-connector (IB Gateway/TWS wrapper)
    ↓ depends on
ibapi (Official IB API)
```

### Component Layers

1. **DLT Resources** (`sources.py`): DLT-decorated functions that yield data
2. **Transformers** (`transformers.py`): Normalize raw IB data to clean schemas
3. **Configuration** (`config.py`): Pydantic models for type-safe config
4. **IB Connector**: Handles IB Gateway/TWS communication
5. **Official IB API**: Low-level Interactive Brokers API

### Design Principles

1. **Separation of Concerns**: `ib-connector` handles IB API, `dlt-ibapi` handles DLT integration
2. **Stateless**: Resources are stateless and can be composed
3. **Modular**: Use only what you need
4. **Type-Safe**: Pydantic models for configuration
5. **Testable**: Each layer can be tested independently
6. **Data Normalization**: All data is cleaned and typed before loading

## CLI Reference

The `dlt-ibapi` command-line interface provides utilities for configuration, testing, and data fetching.

### Available Commands

```bash
dlt-ibapi init              # Initialize config file
dlt-ibapi show-config       # Display current configuration
dlt-ibapi test-connection   # Test IB Gateway/TWS connection
dlt-ibapi fetch             # Fetch data manually
dlt-ibapi version           # Show version
```

### Command Details

#### `init` - Initialize Configuration

Creates `.dlt-ibapi/ib_gateway.yaml` in your project:

```bash
# Create config in current directory
dlt-ibapi init

# Create in specific directory
dlt-ibapi init --dir /path/to/project

# Overwrite existing config
dlt-ibapi init --force
```

#### `show-config` - Display Configuration

Shows merged configuration from all sources (defaults, user config, env vars):

```bash
# Show config from auto-detected user config
dlt-ibapi show-config

# Show config from specific file
dlt-ibapi show-config --config /path/to/config.yaml
```

Output example:
```
Configuration Sources:
  Default: /path/to/package/config_files/ib_gateway.yaml
  User:    /path/to/project/.dlt-ibapi/ib_gateway.yaml ✓
  Env:     IB_HOST, IB_PORT, etc.

Connection Settings
┏━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━┓
┃ Setting       ┃ Value       ┃
┡━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━┩
│ Host          │ 127.0.0.1   │
│ Port          │ 4002        │
│ Client ID     │ 1           │
│ Ready Timeout │ 10.0s       │
└───────────────┴─────────────┘
```

#### `test-connection` - Test IB Connection

Verifies connection to IB Gateway/TWS:

```bash
# Test with config file settings
dlt-ibapi test-connection

# Override settings
dlt-ibapi test-connection --host 127.0.0.1 --port 7497 --client-id 2

# Use custom config file
dlt-ibapi test-connection --config /path/to/config.yaml
```

#### `fetch` - Fetch Data

Fetch market data and optionally save to JSON:

```bash
# Fetch historical bars for symbols
dlt-ibapi fetch AAPL GOOGL MSFT

# Save to file
dlt-ibapi fetch AAPL --output aapl_bars.json

# Fetch contract details
dlt-ibapi fetch AAPL GOOGL --type contract --output contracts.json

# Use custom config
dlt-ibapi fetch TSLA --config /path/to/config.yaml --output tsla.json
```

**Options:**
- `--output, -o`: Output file path (JSON format)
- `--type, -t`: Data type (`historical` or `contract`)
- `--config, -c`: Path to config file

---

## Development

```bash
# Install dev dependencies
uv sync --dev

# Run tests
uv run pytest

# Format code
uv run ruff format .

# Lint
uv run ruff check .
```

## Examples

See the `examples/` directory for complete usage examples:

- **`basic_pipeline.py`** - Simple historical data pipeline using config loader
- **`multi_symbol.py`** - Multiple symbols with DuckDB, demonstrates `ib_source`
- **`contract_details.py`** - Fetch contract specifications and query results
- **`config_example.py`** - All configuration methods (YAML, env vars, code)

Each example includes:
- Configuration loading from YAML/env vars
- Setup instructions
- Both explicit and auto-load config patterns

**Before running examples:**

```bash
# 1. Initialize config in examples directory
cd examples
dlt-ibapi init

# 2. Edit config to match your IB Gateway setup
vim .dlt-ibapi/ib_gateway.yaml

# 3. Test connection
dlt-ibapi test-connection

# 4. Run an example
uv run python basic_pipeline.py
```

## Troubleshooting

### Connection Errors
- Ensure IB Gateway/TWS is running
- Check port number (7497 for paper, 4002 for IB Gateway paper)
- Verify API connections are enabled in TWS settings
- Check client_id is not already in use

### Timeout Errors
- Increase `ready_timeout` in connection config
- Increase resource-specific timeouts
- Check network connectivity to IB Gateway

### No Data Returned
- Verify symbol exists and is correct
- Check exchange and currency parameters
- Ensure market is open or use historical data during market hours
- Check IB account permissions for data

## License

MIT

## Related Projects

- [ib-connector](../ib-connector) - Standalone IB Gateway/TWS connector
- [dlt](https://dlthub.com/) - Data load tool
- [ibapi](https://interactivebrokers.github.io/) - Official IB API
