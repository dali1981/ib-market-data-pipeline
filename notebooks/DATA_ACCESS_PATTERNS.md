# Data Access Patterns in Notebooks

## Overview

The `dlt-ibapi` notebooks use different data access patterns depending on the use case. This document explains when to use each pattern and why.

## Access Methods

### 1. Reader API (EquityBarsReader, OptionChainSnapshotReader)

**Use When**: Querying data for a **specific contract** or **single symbol** with simple filters.

**Example**:
```python
from dlt_ibapi.repositories import EquityBarsReader

equity_reader = EquityBarsReader(database_path='../data_delta', dataset_name='stocks')
bars = equity_reader.get_bars(
    symbol='AAPL',
    bar_size='1 day',
    start_date=date(2025, 11, 1),
    end_date=date(2025, 11, 30)
)
```

**Strengths**:
- Type-safe Python API
- Clean, readable code
- Handles parameter validation
- Consistent interface across readers

**Limitations**:
- Designed for single-contract queries
- Not optimized for bulk reads
- Limited aggregation capabilities

### 2. Raw DuckDB Queries

**Use When**:
- Loading **all options** for an underlying (multiple strikes/expirations)
- Performing **aggregations** or **complex joins**
- Working with **batch operations** across many contracts
- Need **custom SQL logic**

**Example**:
```python
import duckdb

con = duckdb.connect()

# Load ALL option data for TMC around earnings
options_df = con.execute(f"""
    SELECT
        date, time, expiry, strike, "right",
        open, high, low, close, volume
    FROM parquet_scan('../data_delta/options/option_bars_backfill/**/*.parquet',
                      hive_partitioning=true)
    WHERE underlying = 'TMC'
      AND (date LIKE '20251112%' OR date LIKE '20251113%' OR date LIKE '20251114%')
    ORDER BY date, time, expiry, strike, "right"
""").df()
```

**Strengths**:
- Efficient bulk reads (single scan)
- Full SQL capabilities (GROUP BY, JOIN, etc.)
- Direct control over query optimization
- Works well with Hive partitioning

**Limitations**:
- String-based queries (no type safety)
- More verbose
- Requires SQL knowledge
- Manual datetime parsing needed

## OptionBarsReader Limitations

### Why Not Use OptionBarsReader for Notebooks?

The `OptionBarsReader.get_bars()` method is designed for **single-contract queries**:

```python
# OptionBarsReader signature
def get_bars(
    self,
    underlying: str,
    expiry: date,        # ← Single expiration required
    strike: float,       # ← Single strike required
    right: str,          # ← Single option type required
    bar_size: str,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
) -> pd.DataFrame:
```

**Problem**: To load all options for volatility analysis, you would need to:

```python
# ❌ INEFFICIENT: N queries for N contracts
contracts = get_contracts_for_underlying('TMC')  # Get contract list first

all_bars = []
for contract in contracts:  # Loop through each contract
    bars = option_reader.get_bars(
        underlying='TMC',
        expiry=contract['expiry'],
        strike=contract['strike'],
        right=contract['right'],
        bar_size='1 hour',
        start_date=start_date,
        end_date=end_date
    )
    all_bars.append(bars)

options_df = pd.concat(all_bars)  # Combine results
```

**Issues**:
1. **N+1 queries**: One query to get contracts, then N queries for bars
2. **Slower**: Multiple parquet scans instead of one
3. **More complex**: Loop + concat logic in notebook
4. **Less readable**: Business logic obscured by iteration

**Solution**: Use raw DuckDB query for bulk reads:

```python
# ✅ EFFICIENT: Single query for all contracts
options_df = con.execute(f"""
    SELECT *
    FROM parquet_scan('../data_delta/options/option_bars_backfill/**/*.parquet',
                      hive_partitioning=true)
    WHERE underlying = 'TMC'
      AND date LIKE '202511%'
""").df()
```

**Benefits**:
1. **Single scan**: DuckDB reads parquet files once
2. **Faster**: Leverages Hive partitioning (underlying=TMC)
3. **Simpler**: One query, no loops
4. **Flexible**: Easy to add filters, aggregations, etc.

## Design Rationale

### Reader API Philosophy

Readers are designed for **application code** where:
- You know the specific contract you want
- Type safety matters
- You want a stable API
- You're building reusable components

**Example Use Case**: A trading bot that needs to fetch bars for a specific option leg.

### Raw DuckDB Philosophy

Raw queries are appropriate for **analytical/notebook code** where:
- You're exploring data across many contracts
- You need aggregations or complex logic
- Performance matters (bulk operations)
- Flexibility is more important than type safety

**Example Use Case**: Calculating IV surfaces across all strikes and expirations.

## When Readers Are Still Used in Notebooks

Even in notebooks that use raw DuckDB for option data, we still use readers for:

### EquityBarsReader
```python
# ✅ Good use of Reader API
equity_reader = EquityBarsReader(database_path='../data_delta', dataset_name='stocks')
spot_data = equity_reader.get_bars(
    symbol='TMC',
    bar_size='1 day',
    start_date=date(2025, 11, 1),
    end_date=date(2025, 11, 30)
)
```

**Why**: We only need **one symbol** with daily bars - perfect fit for the Reader API.

### EarningsCalendarReader
```python
# ✅ Good use of Reader API
earnings_reader = EarningsCalendarReader(database_path='../data', dataset_name='earnings')
earnings_info = earnings_reader.get_earnings_for_symbol(
    symbol='TMC',
    start_date=date(2025, 11, 1),
    end_date=date(2025, 11, 30)
)
```

**Why**: Single symbol lookup with semantic query method.

## Best Practices

### For Application Code
```python
# Use Readers for type safety and stability
from dlt_ibapi.repositories import OptionBarsReader

option_reader = OptionBarsReader(database_path='./data', dataset_name='options')

# Query specific contract
bars = option_reader.get_bars(
    underlying='AAPL',
    expiry=date(2025, 11, 21),
    strike=150.0,
    right='C',
    bar_size='1 hour'
)
```

### For Notebooks/Analysis
```python
# Use DuckDB for bulk reads and aggregations
import duckdb

con = duckdb.connect()

# Load all contracts for analysis
options_df = con.execute("""
    SELECT *
    FROM parquet_scan('../data_delta/options/**/*.parquet', hive_partitioning=true)
    WHERE underlying = 'AAPL'
      AND date >= '2025-11-01'
      AND date <= '2025-11-30'
""").df()

# Aggregate by strike
strike_summary = con.execute("""
    SELECT strike, AVG(close) as avg_price, COUNT(*) as bars
    FROM options_df
    GROUP BY strike
    ORDER BY strike
""").df()
```

## Common Patterns

### Pattern 1: Load Spot Prices (Use Reader)
```python
equity_reader = EquityBarsReader(database_path='../data_delta', dataset_name='stocks')
spot_data = equity_reader.get_bars(symbol='TMC', bar_size='1 day')
```

### Pattern 2: Load All Options (Use DuckDB)
```python
options_df = con.execute(f"""
    SELECT * FROM parquet_scan('../data_delta/options/**/*.parquet', ...)
    WHERE underlying = 'TMC'
""").df()
```

### Pattern 3: Load Specific Option Legs (Use Reader)
```python
# When you know exactly which contract you want
option_reader = OptionBarsReader(database_path='../data_delta', dataset_name='options')
short_call = option_reader.get_bars(
    underlying='TMC',
    expiry=date(2025, 11, 21),
    strike=5.0,
    right='C',
    bar_size='1 hour'
)
```

### Pattern 4: Complex Analytics (Use DuckDB)
```python
# Calculate implied volatility surface across all contracts
iv_surface = con.execute("""
    SELECT
        expiry,
        strike,
        AVG(close) as avg_price,
        COUNT(*) as sample_size
    FROM parquet_scan('../data_delta/options/**/*.parquet', hive_partitioning=true)
    WHERE underlying = 'TMC'
      AND "right" = 'C'
    GROUP BY expiry, strike
    ORDER BY expiry, strike
""").df()
```

## Future Improvements

Potential enhancements to make Readers more notebook-friendly:

### Bulk Query Method
```python
# Hypothetical future API
option_reader = OptionBarsReader(database_path='../data_delta', dataset_name='options')

# Query all contracts for an underlying
all_bars = option_reader.get_bars_bulk(
    underlying='TMC',
    start_date=date(2025, 11, 1),
    end_date=date(2025, 11, 30),
    bar_size='1 hour',
    filters={'right': 'C'}  # Optional contract filters
)
```

This would internally use a single DuckDB query but expose a clean Python API.

### Trade-offs
- **Pro**: Type-safe, consistent with Reader pattern
- **Con**: Adds complexity to Reader classes
- **Decision**: For now, raw DuckDB is simpler and more flexible for bulk operations

## Summary

| Use Case | Method | Reason |
|----------|--------|--------|
| Single symbol equity bars | `EquityBarsReader` | Simple, type-safe |
| Single option contract | `OptionBarsReader.get_bars()` | Type-safe, validated |
| All options for underlying | Raw DuckDB | Efficient bulk read |
| Aggregations/analytics | Raw DuckDB | Full SQL capabilities |
| Earnings lookup | `EarningsCalendarReader` | Semantic query methods |
| Application code | Readers | Stability, type safety |
| Notebook exploration | DuckDB or Readers | Flexibility based on use case |

**Key Principle**: Use Readers for **focused queries**, use DuckDB for **bulk operations** and **analytics**.
