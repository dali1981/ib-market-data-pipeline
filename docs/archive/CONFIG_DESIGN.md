# Configuration Design for dlt-ibapi

## Problem: Where to Put Config Files in a Library?

When building a library that will be installed in other projects, configuration file location is tricky:

- ❌ **Don't hardcode paths** - Won't work when installed as a package
- ❌ **Don't require global config** - Not suitable for multiple projects
- ✅ **Ship defaults with package** - Package data
- ✅ **Allow user overrides** - Per-project config

## Solution: Hierarchical Configuration

We implement a 4-tier configuration system:

### 1. Default Config (Lowest Priority)

**Location:** `src/dlt_ibapi/config_files/ib_gateway.yaml`

- Shipped with the package as package data
- Used when no user config exists
- Safe defaults for development
- Never modified by users

```python
# Accessed via:
from pathlib import Path
default = Path(__file__).parent / "config_files" / "ib_gateway.yaml"
```

### 2. User Project Config

**Location:** `.dlt-ibapi/ib_gateway.yaml` (in project root)

- Created by user with `dlt-ibapi init`
- Searched by walking up directory tree from `cwd`
- Project-specific settings
- Committed to project repo (not secrets!)

```python
# Auto-detected by searching:
Path.cwd() / ".dlt-ibapi" / "ib_gateway.yaml"
Path.cwd().parent / ".dlt-ibapi" / "ib_gateway.yaml"
# ... and so on up the tree
```

### 3. Environment Variables

**Variables:**
```bash
IB_HOST=127.0.0.1
IB_PORT=4002
IB_CLIENT_ID=1
IB_READY_TIMEOUT=10.0
IB_HIST_DURATION="1 W"
IB_HIST_BAR_SIZE="5 mins"
# ... etc
```

- Override both default and user config
- Great for deployment/CI/CD
- Keep secrets out of config files
- Per-environment customization

### 4. Explicit Python Objects (Highest Priority)

```python
from dlt_ibapi.config import IBConnectionConfig

config = IBConnectionConfig(
    host="127.0.0.1",
    port=7497,
    client_id=1,
)

data = ib_historical_bars(
    symbol="AAPL",
    connection_config=config,  # Overrides everything
)
```

- Full programmatic control
- Overrides all other sources
- Type-safe with Pydantic
- Good for testing

## Config Loading Logic

```python
def load_config():
    # 1. Load defaults (always present)
    config = load_default_config()

    # 2. Merge user config if found
    user_config = find_user_config()
    if user_config:
        config = merge(config, user_config)

    # 3. Merge environment variables
    env_config = load_env_vars()
    config = merge(config, env_config)

    # 4. User can still override with explicit objects
    return config
```

## Why This Works

### ✅ Library Installation
- Default config ships with package (package data)
- Works immediately after `pip install dlt-ibapi`
- No manual setup required

### ✅ Project Customization
- Each project has `.dlt-ibapi/` directory
- Config is version-controlled with project
- Different projects can have different settings

### ✅ Environment Flexibility
- Dev, staging, prod can use env vars
- Secrets never in config files
- CI/CD friendly

### ✅ Developer Experience
- `dlt-ibapi init` creates template
- `dlt-ibapi show-config` shows merged result
- Auto-detection "just works"

## Directory Structure

```
my-trading-project/
├── .dlt-ibapi/              # Project config
│   └── ib_gateway.yaml      # Created by `dlt-ibapi init`
├── src/
│   └── my_pipeline.py       # Uses config automatically
├── .env                     # Environment overrides (gitignored)
└── README.md

# When installed:
site-packages/
└── dlt_ibapi/
    ├── config_files/        # Default configs
    │   └── ib_gateway.yaml  # Package defaults
    ├── config_loader.py     # Config loading logic
    └── sources.py           # Uses config
```

## Best Practices

### Development
```bash
# 1. Initialize config in your project
dlt-ibapi init

# 2. Edit .dlt-ibapi/ib_gateway.yaml
vim .dlt-ibapi/ib_gateway.yaml

# 3. Test connection
dlt-ibapi test-connection

# 4. Use in code (auto-loads config)
python my_pipeline.py
```

### Production
```bash
# Set env vars for secrets
export IB_HOST=prod.ib.gateway
export IB_PORT=4001
export IB_CLIENT_ID=10

# Config file has non-secret defaults
python my_pipeline.py
```

### Testing
```python
# Override everything in tests
def test_pipeline():
    test_config = IBConnectionConfig(
        host="localhost",
        port=4002,
        client_id=999,
    )

    data = ib_historical_bars(
        symbol="AAPL",
        connection_config=test_config,
    )
```

## Similar Patterns

This pattern is used by many popular libraries:

- **pytest** - `pytest.ini` in project root
- **black** - `pyproject.toml` in project root
- **docker** - `.docker/` or `docker-compose.yml`
- **git** - `.git/config` per project
- **dlt** - `.dlt/` directory pattern

## Implementation Files

1. **`config_files/ib_gateway.yaml`** - Default config (package data)
2. **`config_loader.py`** - Config loading logic
3. **`config.py`** - Pydantic models
4. **`cli.py`** - `dlt-ibapi init` command
5. **`pyproject.toml`** - Package data configuration

## Usage Examples

See `examples/config_example.py` for complete examples of:
- Auto-loading from YAML
- Using config loader utilities
- Viewing merged configuration
- Overriding with code
- Sharing config across resources
