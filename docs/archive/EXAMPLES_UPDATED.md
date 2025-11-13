# Examples Updated to Use Config System

All examples in the `examples/` directory have been updated to demonstrate the new configuration system.

## What Changed

### Before (Old Examples)
```python
# Hardcoded configuration in every example
connection_config = IBConnectionConfig(
    host="127.0.0.1",
    port=7497,
    client_id=1,
)
```

**Problems:**
- ❌ Hardcoded connection details
- ❌ No way to customize without editing code
- ❌ Not production-ready
- ❌ Doesn't show config best practices

### After (Updated Examples)
```python
# Load configuration from YAML/env vars/defaults
from dlt_ibapi.config_loader import get_connection_config

connection_config = get_connection_config()
```

**Benefits:**
- ✅ Loads from `.dlt-ibapi/ib_gateway.yaml`
- ✅ Respects environment variables
- ✅ Falls back to safe defaults
- ✅ Production-ready pattern
- ✅ Shows config best practices

## Updated Examples

### 1. `basic_pipeline.py`
**Changes:**
- Uses `get_connection_config()` and `get_historical_config()`
- Added `main_simple()` showing auto-load pattern
- Added setup instructions in docstring
- Prints config details before running

**New features:**
```python
# Shows what config is being used
print(f"Using connection: {connection_config.host}:{connection_config.port}")

# Also demonstrates the simplest pattern
def main_simple():
    # Config auto-loads from .dlt-ibapi/ib_gateway.yaml
    data = ib_historical_bars(symbol="AAPL")
```

---

### 2. `multi_symbol.py`
**Changes:**
- Uses `get_connection_config()`
- Added `main_simple()` showing auto-load
- Better output formatting

**New features:**
```python
# Load config from YAML/env/defaults
connection_config = get_connection_config()
print(f"Using connection: {connection_config.host}:{connection_config.port}")
```

---

### 3. `contract_details.py`
**Changes:**
- Uses `get_connection_config()`
- Added `query_contracts()` to show data querying
- Added `main_simple()` pattern
- Better formatted output

**New features:**
```python
# Query and display results after loading
def query_contracts(pipeline):
    conn = duckdb.connect(f"{pipeline.pipeline_name}.duckdb")
    result = conn.execute("SELECT * FROM ...").fetchdf()
    # Pretty print results
```

---

### 4. `config_example.py` (NEW)
**Completely new example** demonstrating all configuration patterns:

1. **Auto-load from YAML** - Simplest approach
2. **Config loader** - Explicit loading with inspection
3. **View merged config** - See final config after merging
4. **Override with code** - Programmatic overrides
5. **Multiple resources** - Share config across resources

**Can run individual examples:**
```bash
python config_example.py 3  # View config only (no IB connection)
python config_example.py 1  # Auto-load pattern
python config_example.py 5  # Multiple resources
```

---

## New Setup Instructions

All examples now include setup steps:

```bash
# 1. Initialize config in examples directory
cd examples
dlt-ibapi init

# 2. Edit config
vim .dlt-ibapi/ib_gateway.yaml

# 3. Test connection
dlt-ibapi test-connection

# 4. Run example
uv run python basic_pipeline.py
```

## Two Patterns Shown

Each example demonstrates both patterns:

### Pattern 1: Explicit Config (Main)
```python
def main():
    # Load config explicitly
    connection_config = get_connection_config()

    # Use it
    data = ib_historical_bars(
        symbol="AAPL",
        connection_config=connection_config,
    )
```

**When to use:**
- Want to inspect/modify config
- Need to print connection details
- Debugging configuration issues

### Pattern 2: Auto-load (Simple)
```python
def main_simple():
    # Config automatically loaded from .dlt-ibapi/ib_gateway.yaml
    data = ib_historical_bars(symbol="AAPL")
```

**When to use:**
- Config file is already set up
- Just want it to work
- Production scripts

## Added Documentation

### 1. `examples/README.md` (NEW)
Complete guide to running examples:
- Prerequisites
- Setup steps
- Description of each example
- How to query loaded data
- Troubleshooting guide
- Configuration patterns
- Next steps

### 2. Enhanced Example Docstrings
Every example now has:
```python
"""
Example: [Title]

This example demonstrates:
1. [Feature 1]
2. [Feature 2]
3. [Feature 3]

Before running:
1. Initialize config: dlt-ibapi init
2. Edit .dlt-ibapi/ib_gateway.yaml
3. Ensure IB Gateway/TWS is running
4. Test connection: dlt-ibapi test-connection
"""
```

## Benefits for Users

### For Beginners
- Clear setup instructions
- Works out of the box with `dlt-ibapi init`
- Test connection before running
- Examples show best practices

### For Advanced Users
- Can override with environment variables
- Can customize config per project
- Can override programmatically
- Production-ready patterns

### For Different Environments
- **Development**: Use `.dlt-ibapi/ib_gateway.yaml`
- **CI/CD**: Use environment variables
- **Production**: Mix of config file + env vars
- **Testing**: Override with code

## Migration Path

If you have old code using hardcoded config:

### Old Code
```python
connection_config = IBConnectionConfig(
    host="127.0.0.1",
    port=7497,
    client_id=1,
)
```

### New Code (Option 1: Config File)
```bash
# One-time setup
dlt-ibapi init
# Edit .dlt-ibapi/ib_gateway.yaml
```

```python
from dlt_ibapi.config_loader import get_connection_config
connection_config = get_connection_config()
```

### New Code (Option 2: Keep Code, Add Config File)
```python
# Keep your code as-is, but create config as override
connection_config = get_connection_config()

# Override specific settings if needed
connection_config.client_id = 2
```

### New Code (Option 3: Environment Variables)
```bash
export IB_HOST=127.0.0.1
export IB_PORT=7497
export IB_CLIENT_ID=1
```

```python
from dlt_ibapi.config_loader import get_connection_config
connection_config = get_connection_config()  # Loads from env vars
```

## Summary

✅ All examples updated to use config system
✅ Each example shows multiple config patterns
✅ Complete setup instructions added
✅ New `examples/README.md` guide
✅ Better formatted output
✅ Production-ready patterns
✅ Backwards compatible (old pattern still works)

Users can now:
- Run examples without editing code
- Configure once, use everywhere
- Override per-environment
- Follow production best practices
