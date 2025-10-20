# dlt-ibapi API Reference

**Complete API documentation for backfill infrastructure**

Version: 1.0
Last Updated: 2025-01-20

---

## Table of Contents

1. [DLT Resources](#dlt-resources)
2. [Reader Repositories](#reader-repositories)
3. [Configuration Models](#configuration-models)
4. [Contract Selection](#contract-selection)
5. [Gap Detection](#gap-detection)
6. [Contract Resolution](#contract-resolution)

---

## DLT Resources

DLT resources are generators that yield normalized data dictionaries to DLT pipelines.

### snapshot_option_chain

Capture option chain snapshot (available strikes and expirations).

```python
@dlt.resource(
    name="option_chain_snapshot",
    write_disposition="replace",
    primary_key=["underlying", "as_of", "exchange", "trading_class"],
)
def snapshot_option_chain(
    underlying: str,
    snapshot_date: date,
    cache_path: str = ".dlt-ibapi/cache",
    connection_config: Optional[IBConnectionConfig] = None,
    min_dte: int = 7,
    max_dte: int = 365,
) -> Iterator[dict]
```

**Parameters:**
- `underlying` (str): Underlying symbol (e.g., "AAPL")
- `snapshot_date` (date): Date to capture snapshot
- `cache_path` (str): Path to contract cache directory
- `connection_config` (IBConnectionConfig | None): IB connection config (auto-loads if None)
- `min_dte` (int): Minimum days to expiration filter (default: 7)
- `max_dte` (int): Maximum days to expiration filter (default: 365)

**Yields:**
Dictionary with schema:
```python
{
    "underlying": str,           # Symbol (uppercase)
    "underlying_conid": int,     # IB contract ID
    "exchange": str,             # Exchange (e.g., "SMART")
    "trading_class": str,        # Trading class (e.g., "AAPL")
    "multiplier": str,           # Contract multiplier (e.g., "100")
    "expirations": List[str],    # List of expiration dates (YYYYMMDD)
    "strikes": List[float],      # List of strike prices
    "expiration_count": int,     # Number of expirations
    "strike_count": int,         # Number of strikes
    "as_of": date,               # Snapshot date
    "captured_at": datetime,     # UTC timestamp
}
```

**Example:**
```python
import dlt
from dlt_ibapi import snapshot_option_chain

pipeline = dlt.pipeline(
    pipeline_name="ib_options",
    destination="duckdb",
    dataset_name="options",
)

data = snapshot_option_chain(
    underlying="AAPL",
    snapshot_date=date.today(),
    min_dte=7,
    max_dte=60,
)

info = pipeline.run(data, write_disposition="replace")
```

**See also:**
- `option_chain_snapshots_source()` - Wrapper for multiple underlyings

---

### backfill_option_bars

Backfill historical option bars with gap detection and contract selection.

```python
@dlt.resource(
    name="option_bars_backfill",
    write_disposition="append",
    primary_key=["underlying", "expiry", "strike", "right", "bar_size", "time"],
)
def backfill_option_bars(
    underlying: str,
    spot_price: float,
    database_path: str,
    dataset_name: str = "options",
    cache_path: str = ".dlt-ibapi/cache",
    connection_config: Optional[IBConnectionConfig] = None,
    backfill_config: Optional[OptionBackfillConfig] = None,
) -> Iterator[dict]
```

**Parameters:**
- `underlying` (str): Underlying symbol
- `spot_price` (float): Current spot price (for contract selection)
- `database_path` (str): Path to DLT database (for gap detection)
- `dataset_name` (str): DLT dataset name (default: "options")
- `cache_path` (str): Path to contract cache
- `connection_config` (IBConnectionConfig | None): IB connection config
- `backfill_config` (OptionBackfillConfig | None): Backfill configuration

**Yields:**
Dictionary with schema:
```python
{
    "time": datetime,            # Bar timestamp
    "date": date,                # Bar date (derived from time)
    "trade_date": date,          # Trade date
    "underlying": str,           # Underlying symbol (uppercase)
    "expiry": date,              # Option expiration date
    "strike": float,             # Strike price
    "right": str,                # "C" or "P" (uppercase)
    "bar_size": str,             # Bar size (e.g., "1 min")
    "open": float,               # Open price
    "high": float,               # High price
    "low": float,                # Low price
    "close": float,              # Close price
    "volume": float,             # Volume
    "wap": float,                # Weighted average price (optional)
    "bar_count": int,            # Number of trades (optional)
    "symbol": str,               # Same as underlying
    "exchange": str,             # Exchange (e.g., "SMART")
    "currency": str,             # Currency (e.g., "USD")
}
```

**Example:**
```python
from dlt_ibapi import backfill_option_bars
from dlt_ibapi.backfill import OptionBackfillConfig, ContractSelectionMode

config = OptionBackfillConfig(
    start_date=date.today() - timedelta(days=7),
    end_date=date.today(),
    bar_size="1 day",
    selection_mode=ContractSelectionMode.K_AROUND_ATM,
    k_strikes=3,
    min_dte=7,
    max_dte=60,
)

data = backfill_option_bars(
    underlying="AAPL",
    spot_price=150.0,
    database_path="ib_options.duckdb",
    dataset_name="options",
    backfill_config=config,
)

pipeline.run(data, write_disposition="append")
```

**Workflow:**
1. Load option chain snapshot from database
2. Select contracts based on `selection_mode`
3. For each contract:
   - Query present dates (gap detection)
   - Find missing windows
   - Fetch bars from IB for each gap
   - Yield normalized bars

**Requirements:**
- Must run `snapshot_option_chain` first
- Database must exist and contain snapshot data

---

### backfill_equity_bars

Backfill historical equity bars with gap detection.

```python
@dlt.resource(
    name="equity_bars_backfill",
    write_disposition="append",
    primary_key=["symbol", "bar_size", "time"],
)
def backfill_equity_bars(
    symbol: str,
    database_path: str,
    dataset_name: str = "stocks",
    cache_path: str = ".dlt-ibapi/cache",
    connection_config: Optional[IBConnectionConfig] = None,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    bar_size: str = "1 day",
    what_to_show: str = "TRADES",
    use_rth: bool = True,
) -> Iterator[dict]
```

**Parameters:**
- `symbol` (str): Stock symbol
- `database_path` (str): Path to DLT database
- `dataset_name` (str): DLT dataset name (default: "stocks")
- `cache_path` (str): Path to contract cache
- `connection_config` (IBConnectionConfig | None): IB connection config
- `start_date` (date | None): Backfill start (default: 30 days ago)
- `end_date` (date | None): Backfill end (default: today)
- `bar_size` (str): IB bar size (default: "1 day")
- `what_to_show` (str): Data type (default: "TRADES")
- `use_rth` (bool): Regular trading hours only (default: True)

**Yields:**
Dictionary with schema:
```python
{
    "time": datetime,            # Bar timestamp
    "date": date,                # Bar date (derived from time)
    "symbol": str,               # Stock symbol (uppercase)
    "bar_size": str,             # Bar size (e.g., "1 day")
    "open": float,               # Open price
    "high": float,               # High price
    "low": float,                # Low price
    "close": float,              # Close price
    "volume": float,             # Volume
    "wap": float,                # Weighted average price (optional)
    "bar_count": int,            # Number of trades (optional)
    "exchange": str,             # Exchange (e.g., "SMART")
    "currency": str,             # Currency (e.g., "USD")
}
```

**Example:**
```python
from dlt_ibapi import backfill_equity_bars

data = backfill_equity_bars(
    symbol="AAPL",
    database_path="ib_stocks.duckdb",
    dataset_name="stocks",
    start_date=date.today() - timedelta(days=30),
    end_date=date.today(),
    bar_size="1 day",
)

pipeline.run(data)
```

---

## Reader Repositories

SQL-based query wrappers for reading DLT-written data.

### BaseReader

Abstract base class for all readers.

```python
class BaseReader(ABC):
    def __init__(
        self,
        database_path: Optional[Union[str, Path]] = None,
        dataset_name: str = "stocks",
        destination_type: str = "duckdb",
    )
```

**Parameters:**
- `database_path` (str | Path | None): Database file path (for DuckDB)
- `dataset_name` (str): DLT dataset name (SQL schema)
- `destination_type` (str): Destination type ("duckdb", "postgres", "snowflake")

**Methods:**

#### get_present_dates

```python
def get_present_dates(
    self,
    start_date: date,
    end_date: date,
    **filters
) -> Set[date]
```

Get set of dates with data in range (for gap detection).

**Parameters:**
- `start_date` (date): Start date (inclusive)
- `end_date` (date): End date (inclusive)
- `**filters`: Column filters (e.g., `symbol="AAPL"`, `bar_size="1 day"`)

**Returns:** Set of dates with available data

**Example:**
```python
present = reader.get_present_dates(
    start_date=date(2024, 1, 1),
    end_date=date(2024, 12, 31),
    symbol="AAPL",
    bar_size="1 day",
)
```

#### load

```python
def load(
    self,
    columns: Optional[List[str]] = None,
    limit: Optional[int] = None,
    **filters
) -> pd.DataFrame
```

Load data from table with optional filtering.

**Parameters:**
- `columns` (List[str] | None): Columns to select (None = all)
- `limit` (int | None): Maximum rows
- `**filters`: Column filters

**Returns:** DataFrame with query results

#### count

```python
def count(self, **filters) -> int
```

Count rows matching filters.

**Returns:** Row count

---

### EquityBarsReader

Reader for equity bars data.

```python
class EquityBarsReader(BaseReader):
    def __init__(
        self,
        database_path: Optional[Union[str, Path]] = None,
        dataset_name: str = "stocks",
        destination_type: str = "duckdb",
    )
```

**Table:** `equity_bars_backfill`
**Primary Key:** `[symbol, bar_size, time]`

**Methods:**

#### get_present_dates_for_symbol

```python
def get_present_dates_for_symbol(
    self,
    symbol: str,
    bar_size: str,
    start_date: date,
    end_date: date,
) -> Set[date]
```

Get dates with data for symbol (gap detection).

**Example:**
```python
reader = EquityBarsReader("ib_stocks.duckdb", "stocks")

present = reader.get_present_dates_for_symbol(
    symbol="AAPL",
    bar_size="1 day",
    start_date=date(2024, 1, 1),
    end_date=date(2024, 12, 31),
)
```

#### get_bars

```python
def get_bars(
    self,
    symbol: str,
    bar_size: str,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    limit: Optional[int] = None,
) -> pd.DataFrame
```

Get historical bars for symbol.

**Returns:** DataFrame with OHLCV bars

**Example:**
```python
bars = reader.get_bars(
    symbol="AAPL",
    bar_size="1 day",
    start_date=date(2024, 1, 1),
    end_date=date(2024, 12, 31),
)
print(bars[['time', 'open', 'high', 'low', 'close', 'volume']])
```

#### get_date_range

```python
def get_date_range(
    self,
    symbol: str,
    bar_size: str,
) -> tuple[Optional[date], Optional[date]]
```

Get date range (min, max) of available data.

**Returns:** Tuple of (min_date, max_date) or (None, None)

#### get_available_symbols

```python
def get_available_symbols(
    self,
    bar_size: Optional[str] = None,
) -> List[str]
```

Get list of symbols with available data.

**Returns:** List of symbols

#### get_symbols_summary

```python
def get_symbols_summary(
    self,
    bar_size: Optional[str] = None,
) -> pd.DataFrame
```

Get summary statistics for all symbols.

**Returns:** DataFrame with columns: `symbol`, `bar_size`, `first_bar`, `last_bar`, `bar_count`

---

### OptionBarsReader

Reader for option bars data.

```python
class OptionBarsReader(BaseReader):
    def __init__(
        self,
        database_path: Optional[Union[str, Path]] = None,
        dataset_name: str = "options",
        destination_type: str = "duckdb",
    )
```

**Table:** `option_bars_backfill`
**Primary Key:** `[underlying, expiry, strike, right, bar_size, time]`

**Methods:**

#### get_present_dates_for_contract

```python
def get_present_dates_for_contract(
    self,
    underlying: str,
    expiry: date,
    strike: float,
    right: str,
    bar_size: str,
    start_date: date,
    end_date: date,
) -> Set[date]
```

Get dates with data for specific option contract (gap detection).

**Parameters:**
- `underlying` (str): Underlying symbol
- `expiry` (date): Option expiration date
- `strike` (float): Strike price
- `right` (str): "C" or "P"
- `bar_size` (str): Bar size
- `start_date` (date): Start of range
- `end_date` (date): End of range

**Returns:** Set of dates with available bars

#### get_bars

```python
def get_bars(
    self,
    underlying: str,
    expiry: date,
    strike: float,
    right: str,
    bar_size: str,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    limit: Optional[int] = None,
) -> pd.DataFrame
```

Get historical bars for specific option contract.

**Returns:** DataFrame with OHLCV bars

**Example:**
```python
reader = OptionBarsReader("ib_options.duckdb", "options")

bars = reader.get_bars(
    underlying="AAPL",
    expiry=date(2024, 12, 20),
    strike=150.0,
    right="C",
    bar_size="1 day",
)
```

#### get_contracts_for_underlying

```python
def get_contracts_for_underlying(
    self,
    underlying: str,
    bar_size: Optional[str] = None,
    min_expiry: Optional[date] = None,
    max_expiry: Optional[date] = None,
) -> pd.DataFrame
```

Get list of option contracts available for underlying.

**Returns:** DataFrame with columns: `underlying`, `expiry`, `strike`, `right`, `bar_size`, `first_bar`, `last_bar`, `bar_count`

#### get_available_expirations

```python
def get_available_expirations(
    self,
    underlying: str,
    bar_size: Optional[str] = None,
) -> List[date]
```

Get available expiration dates for underlying.

**Returns:** List of expiration dates

---

### OptionChainSnapshotReader

Reader for option chain snapshots.

```python
class OptionChainSnapshotReader(BaseReader):
    def __init__(
        self,
        database_path: Optional[Union[str, Path]] = None,
        dataset_name: str = "options",
        destination_type: str = "duckdb",
    )
```

**Table:** `option_chain_snapshot`
**Primary Key:** `[underlying, as_of, exchange, trading_class]`

**Methods:**

#### get_available_snapshots

```python
def get_available_snapshots(
    self,
    underlying: str,
) -> List[date]
```

Get available snapshot dates for underlying.

**Returns:** List of snapshot dates

**Example:**
```python
reader = OptionChainSnapshotReader("ib_options.duckdb", "options")

snapshots = reader.get_available_snapshots("AAPL")
print(f"Snapshots: {snapshots}")
```

#### get_chain_for_date

```python
def get_chain_for_date(
    self,
    underlying: str,
    as_of: date,
    min_dte: Optional[int] = None,
    max_dte: Optional[int] = None,
    right: Optional[str] = None,
) -> pd.DataFrame
```

Get complete option chain for specific date.

**Parameters:**
- `underlying` (str): Underlying symbol
- `as_of` (date): Snapshot date
- `min_dte` (int | None): Minimum DTE filter
- `max_dte` (int | None): Maximum DTE filter
- `right` (str | None): "C" or "P" filter

**Returns:** DataFrame with chain parameters

#### get_available_expirations

```python
def get_available_expirations(
    self,
    underlying: str,
    as_of: date,
    min_dte: Optional[int] = None,
    max_dte: Optional[int] = None,
) -> List[date]
```

Get available expiration dates from snapshot.

**Returns:** List of expiration dates

#### get_strikes_for_expiry

```python
def get_strikes_for_expiry(
    self,
    underlying: str,
    as_of: date,
    expiry: date,
    right: Optional[str] = None,
) -> List[float]
```

Get available strikes for specific expiration.

**Returns:** List of strike prices

---

## Configuration Models

Pydantic models for type-safe configuration.

### BackfillConfig

Base configuration for equity bars backfill.

```python
from dlt_ibapi.backfill import BackfillConfig

config = BackfillConfig(
    start_date: date,
    end_date: date,
    bar_size: str = "1 day",
    what_to_show: str = "TRADES",
    use_rth: bool = True,
    max_days_per_request: int = 365,
)
```

**Fields:**
- `start_date` (date): Backfill start date (inclusive)
- `end_date` (date): Backfill end date (inclusive)
- `bar_size` (str): IB bar size (default: "1 day")
- `what_to_show` (str): Data type (default: "TRADES")
- `use_rth` (bool): Regular trading hours only (default: True)
- `max_days_per_request` (int): Max days per API call (default: 365)

**Validators:**
- Dates cannot be in future
- `end_date >= start_date`

---

### OptionBackfillConfig

Extended configuration for option bars backfill.

```python
from dlt_ibapi.backfill import OptionBackfillConfig, ContractSelectionMode

config = OptionBackfillConfig(
    start_date: date,
    end_date: date,
    bar_size: str = "1 day",
    selection_mode: ContractSelectionMode = ContractSelectionMode.K_AROUND_ATM,
    k_strikes: int = 5,
    moneyness_levels: Optional[List[float]] = None,
    target_deltas: Optional[List[float]] = None,
    min_dte: int = 7,
    max_dte: int = 90,
    include_calls: bool = True,
    include_puts: bool = True,
    what_to_show: str = "TRADES",
    use_rth: bool = True,
)
```

**Additional Fields:**
- `selection_mode` (ContractSelectionMode): Contract selection strategy
- `k_strikes` (int): For K_AROUND_ATM mode (default: 5)
- `moneyness_levels` (List[float] | None): For MONEYNESS mode (e.g., [0.9, 1.0, 1.1])
- `target_deltas` (List[float] | None): For DELTA mode (e.g., [0.25, 0.50, 0.75])
- `min_dte` (int): Minimum days to expiration (default: 7)
- `max_dte` (int): Maximum days to expiration (default: 90)
- `include_calls` (bool): Include call options (default: True)
- `include_puts` (bool): Include put options (default: True)

**Validators:**
- `moneyness_levels` required when `selection_mode=MONEYNESS`
- `target_deltas` required when `selection_mode=DELTA`
- Delta values must be between 0 and 1
- `max_dte > min_dte`

**Example:**
```python
config = OptionBackfillConfig(
    start_date=date.today() - timedelta(days=7),
    end_date=date.today(),
    bar_size="1 day",
    selection_mode=ContractSelectionMode.K_AROUND_ATM,
    k_strikes=3,
    min_dte=7,
    max_dte=60,
)
```

---

### ContractSelectionMode

Enum for contract selection strategies.

```python
from dlt_ibapi.backfill import ContractSelectionMode

mode = ContractSelectionMode.K_AROUND_ATM  # or MONEYNESS, DELTA, ALL
```

**Values:**
- `K_AROUND_ATM`: Select k strikes on each side of ATM
- `MONEYNESS`: Select by strike/spot ratios
- `DELTA`: Select by option delta (Black-Scholes)
- `ALL`: Select all available strikes

---

### OptionChainSnapshotConfig

Configuration for option chain snapshots.

```python
from dlt_ibapi.backfill import OptionChainSnapshotConfig

config = OptionChainSnapshotConfig(
    snapshot_date: date,
    min_dte: int = 7,
    max_dte: int = 365,
)
```

**Fields:**
- `snapshot_date` (date): Date to capture snapshot
- `min_dte` (int): Minimum DTE to include (default: 7)
- `max_dte` (int): Maximum DTE to include (default: 365)

**Validators:**
- `snapshot_date` cannot be in future

---

## Contract Selection

Functions for selecting which option contracts to backfill.

### select_k_around_atm

```python
def select_k_around_atm(
    strikes: List[float],
    spot_price: float,
    k: int = 5,
) -> List[float]
```

Select k strikes on each side of ATM.

**Algorithm:**
1. Find ATM strike (closest to spot)
2. Select k strikes below ATM
3. Select k strikes above ATM
4. Return sorted list (up to 2k+1 strikes)

**Parameters:**
- `strikes` (List[float]): Available strikes
- `spot_price` (float): Current spot price
- `k` (int): Number of strikes per side (default: 5)

**Returns:** List of selected strikes

**Example:**
```python
from dlt_ibapi.backfill import select_k_around_atm

strikes = [140, 145, 150, 155, 160, 165, 170]
spot = 150.0

selected = select_k_around_atm(strikes, spot, k=2)
# Returns: [145, 150, 155, 160] (2 on each side + ATM)
```

---

### select_by_moneyness

```python
def select_by_moneyness(
    strikes: List[float],
    spot_price: float,
    target_moneyness: List[float],
    tolerance: float = 0.05,
) -> List[float]
```

Select strikes by moneyness ratio (strike / spot).

**Algorithm:**
1. Calculate moneyness for each strike
2. For each target, find closest strike within tolerance
3. Return unique strikes

**Parameters:**
- `strikes` (List[float]): Available strikes
- `spot_price` (float): Current spot price
- `target_moneyness` (List[float]): Target ratios (e.g., [0.9, 1.0, 1.1])
- `tolerance` (float): Acceptable deviation (default: 0.05)

**Returns:** List of selected strikes

**Example:**
```python
from dlt_ibapi.backfill import select_by_moneyness

strikes = [135, 140, 145, 150, 155, 160, 165]
spot = 150.0
targets = [0.90, 0.95, 1.0, 1.05, 1.10]

selected = select_by_moneyness(strikes, spot, targets)
# Returns strikes near: 135 (0.90), 142.5 (0.95), 150 (1.0), 157.5 (1.05), 165 (1.10)
```

---

### select_by_delta

```python
def select_by_delta(
    strikes: List[float],
    spot_price: float,
    expiry: date,
    as_of: date,
    target_deltas: List[float],
    option_type: str,
    risk_free_rate: float = 0.05,
    volatility: float = 0.30,
    tolerance: float = 0.05,
) -> List[float]
```

Select strikes by option delta (Black-Scholes).

**Algorithm:**
1. Calculate time to expiry in years
2. Compute delta for each strike using Black-Scholes
3. For each target delta, find closest strike within tolerance
4. Return unique strikes

**Parameters:**
- `strikes` (List[float]): Available strikes
- `spot_price` (float): Current spot price
- `expiry` (date): Option expiration date
- `as_of` (date): Current date
- `target_deltas` (List[float]): Target delta values
  - For calls: [0.25, 0.50, 0.75]
  - For puts: [-0.25, -0.50, -0.75]
- `option_type` (str): "call" or "put"
- `risk_free_rate` (float): Risk-free rate (default: 0.05 = 5%)
- `volatility` (float): Implied volatility estimate (default: 0.30 = 30%)
- `tolerance` (float): Acceptable delta deviation (default: 0.05)

**Returns:** List of selected strikes

**Example:**
```python
from dlt_ibapi.backfill import select_by_delta

strikes = [135, 140, 145, 150, 155, 160, 165]
spot = 150.0
expiry = date(2024, 12, 20)
as_of = date(2024, 11, 20)

selected = select_by_delta(
    strikes, spot, expiry, as_of,
    target_deltas=[0.25, 0.50, 0.75],
    option_type="call",
    volatility=0.25,  # 25% IV
)
```

---

### filter_contracts_by_selection_mode

```python
def filter_contracts_by_selection_mode(
    chain_snapshot: pd.DataFrame,
    spot_price: float,
    as_of: date,
    selection_mode: str,
    k_strikes: int = 5,
    moneyness_levels: Optional[List[float]] = None,
    target_deltas: Optional[List[float]] = None,
    include_calls: bool = True,
    include_puts: bool = True,
    risk_free_rate: float = 0.05,
    volatility: float = 0.30,
) -> List[Tuple[date, float, str]]
```

Unified interface for contract selection.

**Parameters:**
- `chain_snapshot` (DataFrame): Option chain snapshot data
- `spot_price` (float): Current spot price
- `as_of` (date): Current date
- `selection_mode` (str): "K_AROUND_ATM", "MONEYNESS", "DELTA", or "ALL"
- `k_strikes` (int): For K_AROUND_ATM mode
- `moneyness_levels` (List[float] | None): For MONEYNESS mode
- `target_deltas` (List[float] | None): For DELTA mode
- `include_calls` (bool): Include call options
- `include_puts` (bool): Include put options
- `risk_free_rate` (float): For DELTA mode
- `volatility` (float): For DELTA mode

**Returns:** List of (expiry, strike, right) tuples

**Example:**
```python
from dlt_ibapi.backfill import filter_contracts_by_selection_mode
from dlt_ibapi.repositories import OptionChainSnapshotReader

reader = OptionChainSnapshotReader("ib_options.duckdb", "options")
chain = reader.get_chain_for_date("AAPL", date.today())

contracts = filter_contracts_by_selection_mode(
    chain_snapshot=chain,
    spot_price=150.0,
    as_of=date.today(),
    selection_mode="K_AROUND_ATM",
    k_strikes=3,
    include_calls=True,
    include_puts=True,
)

print(f"Selected {len(contracts)} contracts")
for expiry, strike, right in contracts[:5]:
    print(f"  {expiry} {strike} {right}")
```

---

## Gap Detection

Functions for identifying missing date ranges.

### business_day_range

```python
def business_day_range(
    start: date,
    end: date,
) -> List[date]
```

Generate list of business days (excludes weekends).

**Note:** Does NOT exclude market holidays. Use `pandas_market_calendars` for NYSE holidays.

**Parameters:**
- `start` (date): Start date (inclusive)
- `end` (date): End date (inclusive)

**Returns:** List of business days

**Example:**
```python
from dlt_ibapi.backfill import business_day_range

days = business_day_range(date(2024, 1, 1), date(2024, 1, 10))
# Returns: [2024-01-02, 2024-01-03, ..., 2024-01-10] (no weekends)
```

---

### missing_windows

```python
def missing_windows(
    present_dates: Set[date],
    start: date,
    end: date,
) -> List[Tuple[date, date]]
```

Find contiguous gaps in date coverage.

**Algorithm:**
1. Generate expected business days
2. Calculate missing = expected - present
3. Group consecutive missing dates into windows
4. Return list of (window_start, window_end) tuples

**Parameters:**
- `present_dates` (Set[date]): Dates with existing data
- `start` (date): Start of desired range
- `end` (date): End of desired range

**Returns:** List of (gap_start, gap_end) tuples

**Example:**
```python
from dlt_ibapi.backfill import missing_windows

present = {date(2024, 1, 2), date(2024, 1, 3), date(2024, 1, 8)}
start = date(2024, 1, 1)
end = date(2024, 1, 10)

gaps = missing_windows(present, start, end)
# Returns: [(2024-01-04, 2024-01-05), (2024-01-09, 2024-01-10)]
```

**Use in backfill:**
```python
reader = EquityBarsReader("ib_stocks.duckdb", "stocks")

present = reader.get_present_dates_for_symbol(
    "AAPL", "1 day", start, end
)

gaps = missing_windows(present, start, end)

for gap_start, gap_end in gaps:
    print(f"Need to fetch: {gap_start} to {gap_end}")
    # Fetch bars from IB for this gap...
```

---

## Contract Resolution

Resolve stock symbols to IB Contract objects with caching.

### ContractResolver

```python
from dlt_ibapi.resolution import ContractResolver, ContractCache
from ib_connector import IBRuntime

runtime = IBRuntime(host="127.0.0.1", port=4002, client_id=1)
runtime.start()

cache = ContractCache(cache_path=".dlt-ibapi/cache")
resolver = ContractResolver(runtime, cache)
```

**Methods:**

#### resolve_symbol

```python
def resolve_symbol(
    self,
    symbol: str,
    exchange: str = "SMART",
    currency: str = "USD",
    sec_type: str = "STK",
) -> Optional[dict]
```

Resolve symbol to contract with caching.

**Algorithm:**
1. Check cache
2. If miss: Create contract via `make_stock()`
3. Fetch details via ContractDetails API
4. Save to cache
5. Return contract dict

**Returns:** Dictionary with keys: `symbol`, `conid`, `exchange`, `currency`, `sec_type`, `local_symbol`, `trading_class`

**Example:**
```python
contract = resolver.resolve_symbol("AAPL", "SMART", "USD", "STK")
print(f"AAPL conid: {contract['conid']}")
```

#### resolve_symbols_batch

```python
def resolve_symbols_batch(
    self,
    symbols: List[str],
    exchange: str = "SMART",
    currency: str = "USD",
    sec_type: str = "STK",
) -> Dict[str, dict]
```

Batch resolution with progress tracking.

**Returns:** Dictionary mapping symbol to contract dict

**Rate Limiting:**
- MatchingSymbols: 1 call/sec
- ContractDetails: 50 calls/sec

---

## Type Hints

All functions use Python type hints for IDE autocomplete:

```python
from typing import List, Set, Tuple, Optional, Dict, Iterator
from datetime import date, datetime
from pathlib import Path
import pandas as pd
```

---

## Error Handling

### Common Exceptions

- `ValueError`: Invalid configuration (e.g., start_date > end_date)
- `FileNotFoundError`: Database file not found
- `IBError`: IB API errors (connection, rate limits, no data)
- `SymbolNotFoundError`: Symbol resolution failed
- `AmbiguousSymbolError`: Multiple matches for symbol

### Example

```python
try:
    data = backfill_equity_bars(...)
    pipeline.run(data)
except ValueError as e:
    print(f"Configuration error: {e}")
except FileNotFoundError as e:
    print(f"Database not found: {e}")
except Exception as e:
    print(f"Unexpected error: {e}")
```

---

## See Also

- **User Guide**: `BACKFILL_GUIDE.md` - Complete usage guide
- **Examples**: `examples/` directory - Working code samples
- **Specs**: `specs/BACKFILL_IMPLEMENTATION_PLAN.md` - Architecture details
