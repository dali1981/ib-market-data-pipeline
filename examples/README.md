# dlt-ibapi Examples

This directory contains complete working examples demonstrating how to use `dlt-ibapi` to fetch market data from Interactive Brokers.

## Prerequisites

1. **IB Gateway or TWS** running locally or remotely
2. **API connections enabled** in IB Gateway/TWS settings
3. **Configuration initialized** (see Setup below)

## Setup

### 1. Initialize Configuration

From this directory, create a config file:

```bash
cd examples
dlt-ibapi init
```

This creates `.dlt-ibapi/ib_gateway.yaml` with default settings.

### 2. Edit Configuration

Update the config to match your IB Gateway/TWS setup:

```bash
vim .dlt-ibapi/ib_gateway.yaml
```

Key settings to check:
- `connection.port`:
  - `4002` for IB Gateway Paper Trading (default)
  - `4001` for IB Gateway Live Trading
  - `7497` for TWS Paper Trading
  - `7496` for TWS Live Trading
- `connection.client_id`: Unique ID for this client (1-32)

### 3. Test Connection

Before running examples, verify your connection:

```bash
dlt-ibapi test-connection
```

You should see:
```
✓ Connected successfully!
✓ Received contract details for AAPL
```

## Examples

### 1. `basic_pipeline.py` - Basic Historical Data

Fetches 1 day of 1-minute bars for AAPL and loads to DuckDB.

**What it demonstrates:**
- Loading config from YAML/env vars
- Using `ib_historical_bars` resource
- Basic DLT pipeline

**Run it:**
```bash
uv run python basic_pipeline.py
```

**Output:**
- Creates `ib_basic.duckdb` with `stocks.historical_bars` table

---

### 2. `multi_symbol.py` - Multiple Symbols

Fetches historical bars and contract details for 5 tech stocks.

**What it demonstrates:**
- Loading config with `get_connection_config()`
- Using `ib_source` to combine multiple resources
- Fetching data for multiple symbols

**Run it:**
```bash
uv run python multi_symbol.py
```

**Output:**
- Creates `ib_multi_symbol.duckdb` with:
  - `market_data.historical_bars` - OHLCV data
  - `market_data.contract_details` - Contract specs

---

### 3. `contract_details.py` - Contract Specifications

Fetches detailed contract information and displays results.

**What it demonstrates:**
- Using `ib_contract_details` resource
- Querying loaded data with SQL
- Displaying results

**Run it:**
```bash
uv run python contract_details.py
```

**Output:**
- Creates `ib_contracts.duckdb` with `reference_data.contract_details`
- Prints formatted contract details to console

---

### 4. `config_example.py` - Configuration Methods

Comprehensive examples of all configuration approaches.

**What it demonstrates:**
- Auto-loading from YAML
- Using config loader utilities
- Viewing merged configuration
- Overriding with code
- Sharing config across resources

**Run specific examples:**
```bash
# View merged config (safe, no IB connection needed)
uv run python config_example.py 3

# Run all examples
uv run python config_example.py 1  # Auto-load from YAML
uv run python config_example.py 2  # Config loader
uv run python config_example.py 4  # Override with code
uv run python config_example.py 5  # Multiple resources
```

---

### 5. `ib_connector_standalone.py` - Direct IB Connector Usage

Shows how to use `ib-connector` directly without DLT.

**What it demonstrates:**
- Raw `ib-connector` API usage
- Lower-level control
- No DLT pipeline

**Run it:**
```bash
uv run python ib_connector_standalone.py
```

## Configuration Patterns

All examples support multiple configuration methods:

### Pattern 1: Auto-load (Simplest)

```python
from dlt_ibapi import ib_historical_bars

# Config is automatically loaded from .dlt-ibapi/ib_gateway.yaml
data = ib_historical_bars(symbol="AAPL")
```

### Pattern 2: Explicit Config Loader

```python
from dlt_ibapi import ib_historical_bars
from dlt_ibapi.config_loader import get_connection_config

# Load and inspect config
config = get_connection_config()
print(f"Using port: {config.port}")

# Pass to resource
data = ib_historical_bars(symbol="AAPL", connection_config=config)
```

### Pattern 3: Environment Variables

```bash
# Override config with env vars
export IB_HOST=127.0.0.1
export IB_PORT=7497
export IB_CLIENT_ID=2

# Run example
uv run python basic_pipeline.py
```

### Pattern 4: Programmatic Override

```python
from dlt_ibapi import ib_historical_bars
from dlt_ibapi.config import IBConnectionConfig

# Override everything with code
config = IBConnectionConfig(host="127.0.0.1", port=7497, client_id=99)
data = ib_historical_bars(symbol="AAPL", connection_config=config)
```

## Querying Loaded Data

After running any example, you can query the data:

### Using DuckDB CLI

```bash
duckdb ib_basic.duckdb

# Query historical bars
SELECT * FROM stocks.historical_bars
WHERE symbol = 'AAPL'
ORDER BY timestamp DESC
LIMIT 10;
```

### Using Python

```python
import duckdb

conn = duckdb.connect("ib_basic.duckdb")

# Get AAPL closing prices
df = conn.execute("""
    SELECT timestamp, close, volume
    FROM stocks.historical_bars
    WHERE symbol = 'AAPL'
    ORDER BY timestamp
""").fetchdf()

print(df)
```

### Using Pandas

```python
import duckdb
import pandas as pd

with duckdb.connect("ib_basic.duckdb") as conn:
    df = conn.execute("SELECT * FROM stocks.historical_bars").fetchdf()

# Analyze with pandas
print(df.describe())
print(df.groupby('symbol')['volume'].mean())
```

## Troubleshooting

### Connection Fails

**Error:** `Connection refused` or timeout

**Solutions:**
1. Ensure IB Gateway/TWS is running
2. Check port number in config matches IB Gateway
3. Verify "Enable ActiveX and Socket Clients" is checked in IB settings
4. Try: `dlt-ibapi test-connection --port 7497` (if using TWS)

### Wrong Port

**Error:** Connection succeeds but no data

**Solution:**
Update port in `.dlt-ibapi/ib_gateway.yaml`:
```yaml
connection:
  port: 7497  # Change to your IB Gateway/TWS port
```

### Client ID Already in Use

**Error:** `clientId already in use`

**Solution:**
Change client_id in config or disconnect other clients:
```yaml
connection:
  client_id: 2  # Use a different ID
```

### No Data Returned

**Possible causes:**
1. Market is closed (use historical data)
2. Symbol doesn't exist or is misspelled
3. IB account doesn't have data permissions
4. Exchange/currency mismatch

**Debug:**
```bash
# Test with a known symbol
dlt-ibapi fetch AAPL --output test.json

# Check what was fetched
cat test.json
```

## Next Steps

After running examples:

1. **Explore the data** - Query DuckDB files created by examples
2. **Customize config** - Adjust bar sizes, durations, timeouts
3. **Add more symbols** - Modify examples to fetch your watchlist
4. **Load to other destinations** - Change `destination="duckdb"` to `"postgres"`, `"snowflake"`, etc.
5. **Schedule pipelines** - Use cron or Airflow to run periodically

## Learn More

- **API Reference** - See main README for complete API documentation
- **Configuration Guide** - See CONFIG_DESIGN.md for configuration architecture
- **DLT Documentation** - https://dlthub.com/docs/
- **IB API Reference** - https://interactivebrokers.github.io/
