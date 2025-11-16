# Historical Tick Data Infrastructure - Implementation Plan

## Executive Summary

**Objective**: Add support for downloading and storing historical tick-by-tick data from Interactive Brokers for options contracts, enabling ultra-precise execution analysis.

**Scope**:
- Extend `ib-connector` with tick data service
- Add tick data resources to `dlt-ibapi`
- Create tick data readers for analysis
- Document usage and limitations

**Timeline**: 8-10 hours total implementation

---

## Background

### Current State
- **ib-connector**: No tick data support (only bar data via `HistoricalService`)
- **dlt-ibapi**: Supports bar sizes from 1 sec to 1 month, no tick-level data
- **Use Case**: Need tick-by-tick data to analyze bid/ask spreads, volume, and execution feasibility at precise times (e.g., 3:55pm entry)

### IB API Tick Data Capabilities

**Method**: `reqHistoricalTicks(contract, startDateTime, endDateTime, numberOfTicks, whatToShow, useRth, ignoreSize)`

**Tick Types (`whatToShow`)**:
- `BID_ASK`: Bid/ask prices and sizes
- `TRADES`: Last trade prices and sizes
- `MIDPOINT`: Midpoint prices

**Limitations**:
- Maximum 1000 ticks per request
- No more than 1 tick request per instrument within 15 seconds
- Max 60 requests within any 10-minute period
- Cannot span multiple trading sessions in single request
- **Options**: Only available historically (not real-time)
- Time range: Up to 6 months for granular data

---

## Phase 1: Extend ib-connector with TickHistoricalService

### 1.1 Create TickHistoricalService Class

**File**: `ib-connector/src/ib_connector/services/tick_historical.py`

**Implementation**:

```python
"""
Historical tick-by-tick data service.

Provides wrapper for IB's reqHistoricalTicks API with pagination support.
"""

from datetime import datetime, timedelta
from typing import List, Literal, Optional
from dataclasses import dataclass
from ib_async import Contract, IB
import logging

logger = logging.getLogger(__name__)


@dataclass
class HistoricalTick:
    """Single tick data point."""
    time: datetime
    price: Optional[float] = None
    size: Optional[int] = None
    bid_price: Optional[float] = None
    ask_price: Optional[float] = None
    bid_size: Optional[int] = None
    ask_size: Optional[int] = None
    exchange: Optional[str] = None
    special_conditions: Optional[str] = None


class TickHistoricalService:
    """
    Service for fetching historical tick-by-tick data.

    Handles IB API pagination and rate limiting.
    """

    def __init__(self, ib: IB):
        self.ib = ib
        self._last_request_time = {}  # Track per-contract rate limiting

    def fetch_historical_ticks(
        self,
        contract: Contract,
        start_time: datetime,
        end_time: datetime,
        tick_type: Literal['BID_ASK', 'TRADES', 'MIDPOINT'] = 'BID_ASK',
        use_rth: bool = True,
        ignore_size: bool = False,
        max_ticks: Optional[int] = None
    ) -> List[HistoricalTick]:
        """
        Fetch historical tick data with automatic pagination.

        Args:
            contract: IB Contract object
            start_time: Start datetime (UTC)
            end_time: End datetime (UTC)
            tick_type: Type of tick data to fetch
            use_rth: Use regular trading hours only
            ignore_size: Ignore size information
            max_ticks: Maximum ticks to fetch (None = all)

        Returns:
            List of HistoricalTick objects

        Raises:
            ValueError: If time range spans multiple trading days
            RuntimeError: If IB API request fails
        """
        # Validate time range (IB limitation: cannot span sessions)
        if (end_time - start_time).days > 1:
            raise ValueError(
                "Cannot fetch ticks spanning multiple days in single request. "
                "Use fetch_historical_ticks_range() for multi-day queries."
            )

        # Enforce rate limiting (15 seconds between requests per contract)
        self._rate_limit_check(contract)

        all_ticks = []
        current_end = end_time

        while True:
            # IB API: numberOfTicks=1000 for max ticks per request
            ticks = self.ib.reqHistoricalTicks(
                contract=contract,
                startDateTime=start_time.strftime('%Y%m%d %H:%M:%S'),
                endDateTime=current_end.strftime('%Y%m%d %H:%M:%S'),
                numberOfTicks=1000,
                whatToShow=tick_type,
                useRth=use_rth,
                ignoreSize=ignore_size
            )

            if not ticks:
                break

            # Convert to HistoricalTick objects
            converted_ticks = self._convert_ticks(ticks, tick_type)
            all_ticks.extend(converted_ticks)

            # Check if we've reached limit
            if max_ticks and len(all_ticks) >= max_ticks:
                all_ticks = all_ticks[:max_ticks]
                break

            # If we got less than 1000, we're done
            if len(ticks) < 1000:
                break

            # Otherwise, paginate: next request ends where this one started
            current_end = ticks[0].time

        self._update_rate_limit(contract)
        return all_ticks

    def fetch_historical_ticks_range(
        self,
        contract: Contract,
        start_date: datetime,
        end_date: datetime,
        tick_type: Literal['BID_ASK', 'TRADES', 'MIDPOINT'] = 'BID_ASK',
        use_rth: bool = True
    ) -> List[HistoricalTick]:
        """
        Fetch tick data across multiple days by splitting into daily requests.

        Handles IB limitation of single-session requests.
        """
        all_ticks = []
        current_date = start_date.date()
        end = end_date.date()

        while current_date <= end:
            # Define daily time window (9:30 - 16:00 for US markets if RTH)
            if use_rth:
                day_start = datetime.combine(current_date, datetime.min.time()) + timedelta(hours=9, minutes=30)
                day_end = datetime.combine(current_date, datetime.min.time()) + timedelta(hours=16)
            else:
                day_start = datetime.combine(current_date, datetime.min.time())
                day_end = datetime.combine(current_date, datetime.min.time()) + timedelta(hours=23, minutes=59)

            # Adjust for start/end boundaries
            if current_date == start_date.date():
                day_start = max(day_start, start_date)
            if current_date == end_date.date():
                day_end = min(day_end, end_date)

            # Fetch ticks for this day
            logger.info(f"Fetching ticks for {current_date}: {day_start} to {day_end}")

            try:
                day_ticks = self.fetch_historical_ticks(
                    contract=contract,
                    start_time=day_start,
                    end_time=day_end,
                    tick_type=tick_type,
                    use_rth=use_rth
                )
                all_ticks.extend(day_ticks)
            except Exception as e:
                logger.error(f"Failed to fetch ticks for {current_date}: {e}")
                # Continue with next day

            current_date += timedelta(days=1)

        return all_ticks

    def _convert_ticks(self, raw_ticks, tick_type: str) -> List[HistoricalTick]:
        """Convert IB tick objects to HistoricalTick dataclass."""
        converted = []

        for tick in raw_ticks:
            if tick_type == 'BID_ASK':
                converted.append(HistoricalTick(
                    time=tick.time,
                    bid_price=tick.priceBid,
                    ask_price=tick.priceAsk,
                    bid_size=tick.sizeBid,
                    ask_size=tick.sizeAsk
                ))
            elif tick_type == 'TRADES':
                converted.append(HistoricalTick(
                    time=tick.time,
                    price=tick.price,
                    size=tick.size,
                    exchange=tick.exchange,
                    special_conditions=tick.specialConditions
                ))
            elif tick_type == 'MIDPOINT':
                converted.append(HistoricalTick(
                    time=tick.time,
                    price=tick.price
                ))

        return converted

    def _rate_limit_check(self, contract: Contract):
        """Enforce 15-second rate limit per contract."""
        contract_key = f"{contract.symbol}_{contract.strike}_{contract.expiry}"
        last_request = self._last_request_time.get(contract_key)

        if last_request:
            elapsed = (datetime.now() - last_request).total_seconds()
            if elapsed < 15:
                wait_time = 15 - elapsed
                logger.warning(f"Rate limit: waiting {wait_time:.1f}s for {contract_key}")
                import time
                time.sleep(wait_time)

    def _update_rate_limit(self, contract: Contract):
        """Update last request timestamp."""
        contract_key = f"{contract.symbol}_{contract.strike}_{contract.expiry}"
        self._last_request_time[contract_key] = datetime.now()
```

### 1.2 Register Service in ib-connector

**File**: `ib-connector/src/ib_connector/__init__.py`

Add export:
```python
from .services.tick_historical import TickHistoricalService, HistoricalTick

__all__ = [
    # ... existing exports
    'TickHistoricalService',
    'HistoricalTick',
]
```

### 1.3 Add to IBRuntime

**File**: `ib-connector/src/ib_connector/runtime.py`

Add service property:
```python
@property
def tick_historical(self) -> TickHistoricalService:
    """Access tick historical data service."""
    if not hasattr(self, '_tick_historical'):
        self._tick_historical = TickHistoricalService(self.ib)
    return self._tick_historical
```

---

## Phase 2: Add Tick Data Resources to dlt-ibapi

### 2.1 Create Tick Data Schema

**File**: `dlt-ibapi/src/dlt_ibapi/schemas/tick_data.py`

```python
"""
Schema definitions for tick-by-tick data.
"""

from typing import Literal
from datetime import datetime

# Tick data schema (bid/ask)
TICK_BID_ASK_SCHEMA = {
    "tick_time": datetime,       # Tick timestamp
    "bid_price": float,          # Bid price
    "ask_price": float,          # Ask price
    "bid_size": int,             # Bid size
    "ask_size": int,             # Ask size
    "spread": float,             # ask - bid
    "spread_pct": float,         # spread / midpoint * 100
    "midpoint": float,           # (bid + ask) / 2
    # Contract identifiers
    "underlying": str,
    "expiry": str,               # ISO date
    "strike": float,
    "right": Literal['C', 'P'],
    # Partitions
    "date": str,                 # ISO date (YYYY-MM-DD)
    "symbol": str,               # Same as underlying
}

# Tick data schema (trades)
TICK_TRADES_SCHEMA = {
    "tick_time": datetime,
    "price": float,
    "size": int,
    "exchange": str,
    "special_conditions": str,
    # Contract identifiers
    "underlying": str,
    "expiry": str,
    "strike": float,
    "right": Literal['C', 'P'],
    # Partitions
    "date": str,
    "symbol": str,
}
```

### 2.2 Create Tick Backfill Resource

**File**: `dlt-ibapi/src/dlt_ibapi/backfill/tick_resources.py`

```python
"""
DLT resources for backfilling tick-by-tick data.
"""

import dlt
from datetime import datetime, date, timedelta
from typing import Iterator, Literal, Optional
from ib_connector import IBRuntime, HistoricalTick
from ib_connector.helpers import make_option

from ..config import IBConnectionConfig
from ..transformers import normalize_tick_data


@dlt.resource(
    name="option_ticks_bid_ask",
    write_disposition="append",
    primary_key=["underlying", "expiry", "strike", "right", "tick_time"],
    columns={
        "date": {"partition": True},
        "symbol": {"partition": True},
    }
)
def backfill_option_ticks_bid_ask(
    underlying: str,
    expiry: date,
    strike: float,
    right: Literal['C', 'P'],
    start_datetime: datetime,
    end_datetime: datetime,
    exchange: str = "SMART",
    currency: str = "USD",
    connection_config: Optional[IBConnectionConfig] = None,
    use_rth: bool = True,
) -> Iterator[dict]:
    """
    Backfill bid/ask tick data for a single option contract.

    Args:
        underlying: Underlying symbol
        expiry: Option expiration date
        strike: Strike price
        right: 'C' for call, 'P' for put
        start_datetime: Start time (UTC)
        end_datetime: End time (UTC)
        exchange: Exchange (default SMART)
        currency: Currency (default USD)
        connection_config: IB connection config
        use_rth: Use regular trading hours only

    Yields:
        Normalized tick dictionaries

    Example:
        >>> from datetime import datetime, date
        >>> import dlt
        >>>
        >>> pipeline = dlt.pipeline(
        ...     pipeline_name="ib_ticks",
        ...     destination=dlt.destinations.filesystem(bucket_url="./data_delta"),
        ...     dataset_name="option_ticks"
        ... )
        >>>
        >>> # Fetch ticks for TMC $5 call around 3:55pm entry
        >>> data = backfill_option_ticks_bid_ask(
        ...     underlying="TMC",
        ...     expiry=date(2025, 11, 21),
        ...     strike=5.0,
        ...     right='C',
        ...     start_datetime=datetime(2025, 11, 12, 15, 50),  # 3:50pm
        ...     end_datetime=datetime(2025, 11, 12, 16, 0),     # 4:00pm
        ... )
        >>>
        >>> info = pipeline.run(data, loader_file_format="parquet")
    """
    config = connection_config or IBConnectionConfig()

    with IBRuntime(config) as runtime:
        # Create option contract
        contract = make_option(
            symbol=underlying,
            lastTradeDateOrContractMonth=expiry.strftime('%Y%m%d'),
            strike=strike,
            right=right,
            exchange=exchange,
            currency=currency
        )

        # Fetch ticks
        ticks = runtime.tick_historical.fetch_historical_ticks_range(
            contract=contract,
            start_date=start_datetime,
            end_date=end_datetime,
            tick_type='BID_ASK',
            use_rth=use_rth
        )

        # Transform and yield
        for tick in ticks:
            yield normalize_tick_data(
                tick=tick,
                underlying=underlying,
                expiry=expiry,
                strike=strike,
                right=right,
                tick_type='BID_ASK'
            )


@dlt.resource(
    name="option_ticks_trades",
    write_disposition="append",
    primary_key=["underlying", "expiry", "strike", "right", "tick_time"],
    columns={
        "date": {"partition": True},
        "symbol": {"partition": True},
    }
)
def backfill_option_ticks_trades(
    underlying: str,
    expiry: date,
    strike: float,
    right: Literal['C', 'P'],
    start_datetime: datetime,
    end_datetime: datetime,
    exchange: str = "SMART",
    currency: str = "USD",
    connection_config: Optional[IBConnectionConfig] = None,
    use_rth: bool = True,
) -> Iterator[dict]:
    """
    Backfill trade tick data for a single option contract.

    Similar to backfill_option_ticks_bid_ask but returns trade ticks.
    """
    config = connection_config or IBConnectionConfig()

    with IBRuntime(config) as runtime:
        contract = make_option(
            symbol=underlying,
            lastTradeDateOrContractMonth=expiry.strftime('%Y%m%d'),
            strike=strike,
            right=right,
            exchange=exchange,
            currency=currency
        )

        ticks = runtime.tick_historical.fetch_historical_ticks_range(
            contract=contract,
            start_date=start_datetime,
            end_date=end_datetime,
            tick_type='TRADES',
            use_rth=use_rth
        )

        for tick in ticks:
            yield normalize_tick_data(
                tick=tick,
                underlying=underlying,
                expiry=expiry,
                strike=strike,
                right=right,
                tick_type='TRADES'
            )
```

### 2.3 Add Tick Transformer

**File**: `dlt-ibapi/src/dlt_ibapi/transformers.py`

Add function:
```python
def normalize_tick_data(
    tick: HistoricalTick,
    underlying: str,
    expiry: date,
    strike: float,
    right: str,
    tick_type: Literal['BID_ASK', 'TRADES']
) -> dict:
    """
    Normalize tick data to DLT schema.

    Args:
        tick: HistoricalTick object from ib-connector
        underlying: Underlying symbol
        expiry: Expiration date
        strike: Strike price
        right: 'C' or 'P'
        tick_type: Type of tick data

    Returns:
        Dictionary matching tick schema
    """
    base = {
        "tick_time": tick.time,
        "underlying": underlying,
        "expiry": expiry.isoformat(),
        "strike": strike,
        "right": right.upper(),
        "date": tick.time.date().isoformat(),
        "symbol": underlying,
    }

    if tick_type == 'BID_ASK':
        midpoint = (tick.bid_price + tick.ask_price) / 2 if tick.bid_price and tick.ask_price else None
        spread = tick.ask_price - tick.bid_price if tick.bid_price and tick.ask_price else None
        spread_pct = (spread / midpoint * 100) if spread and midpoint else None

        return {
            **base,
            "bid_price": tick.bid_price,
            "ask_price": tick.ask_price,
            "bid_size": tick.bid_size,
            "ask_size": tick.ask_size,
            "spread": spread,
            "spread_pct": spread_pct,
            "midpoint": midpoint,
        }
    elif tick_type == 'TRADES':
        return {
            **base,
            "price": tick.price,
            "size": tick.size,
            "exchange": tick.exchange,
            "special_conditions": tick.special_conditions,
        }
```

---

## Phase 3: Create Tick Data Reader

### 3.1 OptionTicksReader Class

**File**: `dlt-ibapi/src/dlt_ibapi/repositories/option_ticks.py`

```python
"""
Reader for option tick-by-tick data.
"""

import pandas as pd
from datetime import datetime, date
from typing import Literal, Optional

from .parquet_reader import ParquetReaderBase


class OptionTicksReader(ParquetReaderBase):
    """
    Reader for querying option tick data from Parquet files.
    """

    def __init__(self, database_path: str, dataset_name: str = "option_ticks"):
        super().__init__(database_path, dataset_name)

    def get_ticks(
        self,
        underlying: str,
        expiry: date,
        strike: float,
        right: Literal['C', 'P'],
        start_datetime: datetime,
        end_datetime: datetime,
        tick_type: Literal['bid_ask', 'trades'] = 'bid_ask'
    ) -> pd.DataFrame:
        """
        Get tick data for specific option contract and time window.

        Args:
            underlying: Underlying symbol
            expiry: Option expiration
            strike: Strike price
            right: 'C' or 'P'
            start_datetime: Start time
            end_datetime: End time
            tick_type: 'bid_ask' or 'trades'

        Returns:
            DataFrame with tick data, sorted by tick_time
        """
        table_name = f"option_ticks_{tick_type}"

        query = f"""
            SELECT *
            FROM parquet_scan('{self.data_path}/{table_name}/**/*.parquet',
                            hive_partitioning=true)
            WHERE underlying = '{underlying}'
              AND expiry = '{expiry.isoformat()}'
              AND strike = {strike}
              AND "right" = '{right.upper()}'
              AND tick_time >= '{start_datetime.isoformat()}'
              AND tick_time <= '{end_datetime.isoformat()}'
            ORDER BY tick_time
        """

        return self._execute_query(query)

    def get_spread_at_time(
        self,
        underlying: str,
        expiry: date,
        strike: float,
        right: Literal['C', 'P'],
        target_time: datetime,
        window_seconds: int = 5
    ) -> Optional[float]:
        """
        Get bid/ask spread at specific time (±window).

        Returns average spread within window, or None if no ticks.
        """
        start = target_time - pd.Timedelta(seconds=window_seconds)
        end = target_time + pd.Timedelta(seconds=window_seconds)

        ticks = self.get_ticks(
            underlying=underlying,
            expiry=expiry,
            strike=strike,
            right=right,
            start_datetime=start,
            end_datetime=end,
            tick_type='bid_ask'
        )

        if ticks.empty:
            return None

        return ticks['spread'].mean()

    def get_volume_window(
        self,
        underlying: str,
        expiry: date,
        strike: float,
        right: Literal['C', 'P'],
        start_datetime: datetime,
        end_datetime: datetime
    ) -> int:
        """
        Get total trade volume in time window.

        Returns:
            Sum of trade sizes (number of contracts traded)
        """
        ticks = self.get_ticks(
            underlying=underlying,
            expiry=expiry,
            strike=strike,
            right=right,
            start_datetime=start_datetime,
            end_datetime=end_datetime,
            tick_type='trades'
        )

        if ticks.empty:
            return 0

        return int(ticks['size'].sum())
```

### 3.2 Register Reader

**File**: `dlt-ibapi/src/dlt_ibapi/repositories/__init__.py`

Add:
```python
from .option_ticks import OptionTicksReader

__all__ = [
    # ... existing
    'OptionTicksReader',
]
```

---

## Phase 4: CLI Command for Tick Backfill

### 4.1 Add CLI Command

**File**: `dlt-ibapi/src/dlt_ibapi/cli_app.py`

Add command:
```python
@app.command()
def backfill-ticks(
    symbol: str,
    expiry: str,  # YYYYMMDD format
    strike: float,
    right: str,  # C or P
    start: str,  # YYYY-MM-DD HH:MM
    end: str,    # YYYY-MM-DD HH:MM
    tick_type: str = 'bid_ask',  # bid_ask or trades
    database_path: str = './data_delta',
    dataset_name: str = 'option_ticks',
):
    """
    Backfill tick-by-tick data for option contract.

    Example:
        dlt-ibapi backfill-ticks TMC 20251121 5.0 C \\
          --start "2025-11-12 15:50" \\
          --end "2025-11-12 16:00" \\
          --tick-type bid_ask
    """
    from datetime import datetime
    from dlt_ibapi.backfill.tick_resources import (
        backfill_option_ticks_bid_ask,
        backfill_option_ticks_trades
    )

    # Parse dates
    expiry_date = datetime.strptime(expiry, '%Y%m%d').date()
    start_dt = datetime.strptime(start, '%Y-%m-%d %H:%M')
    end_dt = datetime.strptime(end, '%Y-%m-%d %H:%M')

    # Create pipeline
    pipeline = dlt.pipeline(
        pipeline_name="ib_tick_backfill",
        destination=dlt.destinations.filesystem(bucket_url=database_path),
        dataset_name=dataset_name,
    )

    # Select resource
    if tick_type == 'bid_ask':
        resource = backfill_option_ticks_bid_ask
    else:
        resource = backfill_option_ticks_trades

    # Run backfill
    console.print(f"[bold]Backfilling {tick_type} ticks for {symbol} ${strike}{right} exp {expiry}[/bold]")
    console.print(f"Time window: {start_dt} to {end_dt}")

    data = resource(
        underlying=symbol,
        expiry=expiry_date,
        strike=strike,
        right=right.upper(),
        start_datetime=start_dt,
        end_datetime=end_dt,
    )

    info = pipeline.run(data, loader_file_format="parquet")

    # Display results
    console.print(f"\n[green]✓ Backfill complete[/green]")
    console.print(f"Loaded {info.metrics.get('rows', 0)} ticks")
```

---

## Phase 5: Documentation and Testing

### 5.1 Usage Documentation

**File**: `docs/TICK_DATA_GUIDE.md`

Create comprehensive guide covering:
- When to use tick data vs bar data
- CLI usage examples
- Programmatic usage (Python API)
- Rate limiting and pagination
- Storage structure
- Query examples with OptionTicksReader
- Limitations and best practices

### 5.2 Example Workflow

```bash
# 1. Backfill entry window ticks (3:50pm - 4:00pm)
dlt-ibapi backfill-ticks TMC 20251121 5.0 C \
  --start "2025-11-12 15:50" \
  --end "2025-11-12 16:00" \
  --tick-type bid_ask

# 2. Backfill exit window ticks (9:30am - 9:40am)
dlt-ibapi backfill-ticks TMC 20251121 5.0 C \
  --start "2025-11-14 09:30" \
  --end "2025-11-14 09:40" \
  --tick-type bid_ask

# 3. Query in notebook
from dlt_ibapi.repositories import OptionTicksReader
from datetime import datetime, date

reader = OptionTicksReader('./data_delta', 'option_ticks')

# Get spread at 3:55pm entry
spread_355 = reader.get_spread_at_time(
    underlying='TMC',
    expiry=date(2025, 11, 21),
    strike=5.0,
    right='C',
    target_time=datetime(2025, 11, 12, 15, 55),
    window_seconds=30  # ±30 seconds
)

print(f"Spread at entry: ${spread_355:.4f}")

# Get all ticks in exit window
exit_ticks = reader.get_ticks(
    underlying='TMC',
    expiry=date(2025, 11, 21),
    strike=5.0,
    right='C',
    start_datetime=datetime(2025, 11, 14, 9, 30),
    end_datetime=datetime(2025, 11, 14, 9, 40),
    tick_type='bid_ask'
)

print(f"Exit window: {len(exit_ticks)} ticks")
print(f"Avg spread: ${exit_ticks['spread'].mean():.4f}")
```

### 5.3 Unit Tests

**File**: `tests/unit/test_tick_resources.py`

Test:
- Tick data normalization
- Schema validation
- Error handling (rate limits, invalid contracts)

**File**: `tests/integration/test_tick_backfill.py`

Test:
- End-to-end tick backfill
- Multi-day pagination
- Reader queries
- (Requires IB Gateway)

---

## Implementation Checklist

### ib-connector
- [ ] Create `services/tick_historical.py` with `TickHistoricalService`
- [ ] Add `HistoricalTick` dataclass
- [ ] Implement `fetch_historical_ticks()` with pagination
- [ ] Implement `fetch_historical_ticks_range()` for multi-day
- [ ] Add rate limiting logic (15 sec per contract)
- [ ] Register in `__init__.py`
- [ ] Add to `IBRuntime` as property
- [ ] Write unit tests

### dlt-ibapi
- [ ] Create `schemas/tick_data.py` with schemas
- [ ] Create `backfill/tick_resources.py` with DLT resources
- [ ] Add `normalize_tick_data()` to transformers
- [ ] Create `repositories/option_ticks.py` with `OptionTicksReader`
- [ ] Add `backfill-ticks` CLI command
- [ ] Register tick resources in `__init__.py`
- [ ] Write integration tests
- [ ] Create `docs/TICK_DATA_GUIDE.md`

### Documentation
- [ ] Update `docs/DATA_ACQUISITION_WORKFLOW.md` with tick data step
- [ ] Update `notebooks/SPECS_PRICE_REALISM_ANALYSIS.md` with tick usage
- [ ] Add examples to README
- [ ] Document rate limits and limitations

---

## Expected Outcomes

### Data Storage Structure

```
data_delta/option_ticks/
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

### Typical Tick Counts

For 10-minute window (e.g., 3:50-4:00pm):
- Liquid options: 100-500 ticks
- Moderate liquidity: 50-100 ticks
- Illiquid: < 50 ticks

### Use Cases Enabled

1. **Precise Spread Analysis**: Exact bid/ask at entry/exit times
2. **Volume Distribution**: When trades occurred within hour
3. **Realistic Fill Simulation**: Model limit orders vs market orders
4. **Microstructure Analysis**: Opening/closing auction behavior
5. **Slippage Estimation**: Historical spread distributions

---

## Timeline Estimate

| Phase | Task | Hours |
|-------|------|-------|
| 1 | TickHistoricalService implementation | 2-3 |
| 2 | DLT tick resources | 2 |
| 3 | OptionTicksReader | 1 |
| 4 | CLI command | 1 |
| 5 | Documentation + tests | 2-3 |
| **Total** | | **8-10 hours** |

---

## Risks and Mitigations

### Risk: Rate Limiting
**Impact**: Slow backfill for many contracts
**Mitigation**:
- Implement smart rate limiting in service
- Use batch mode CLI for multiple contracts
- Cache fetched data aggressively

### Risk: Data Volume
**Impact**: Large parquet files
**Mitigation**:
- Use time-based partitioning (date + symbol)
- Compress parquet files
- Document typical storage requirements

### Risk: IB API Changes
**Impact**: Breaking changes in tick API
**Mitigation**:
- Version pin ib_async dependency
- Add integration tests
- Document API version used

---

## Future Enhancements

1. **Real-time Tick Streaming**: Add `reqTickByTickData()` for live data
2. **Tick Aggregation**: Convert ticks to custom bar sizes
3. **Advanced Analytics**: VWAP, TWAP from tick data
4. **Trade Reconstruction**: Simulate order book from ticks
5. **Cross-Asset Support**: Extend to equity/futures tick data

---

## Success Criteria

- [x] Can fetch tick data for option contracts via CLI
- [x] Data stored in partitioned Parquet format
- [x] OptionTicksReader provides easy query API
- [x] Rate limiting prevents IB API violations
- [x] Multi-day queries handled automatically
- [x] Documentation covers all use cases
- [x] Integration tests pass with IB Gateway