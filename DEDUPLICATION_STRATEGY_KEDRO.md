# Deduplication Strategy: Kedro-Based Approach

## Philosophy

**Separation of Concerns:**
- **DLT:** Fast data ingestion (append-only, no dedup overhead)
- **Kedro:** Data maintenance and transformation (dedup, validation, quality checks)

This keeps each tool focused on what it does best.

---

## Architecture

```
┌─────────────────────────────────────────────┐
│ Ingestion Layer (DLT)                       │
│ - Fast append-only writes                   │
│ - Gap detection (prevents most duplicates)  │
│ - No dedup overhead                         │
└─────────────────┬───────────────────────────┘
                  │
                  │ writes to
                  ▼
┌─────────────────────────────────────────────┐
│ Raw Parquet Files (may have duplicates)    │
│ data/                                       │
│ ├── stocks/                                 │
│ │   └── historical_bars/*.parquet           │
│ └── options/                                │
│     └── option_bars_backfill/*.parquet      │
└─────────────────┬───────────────────────────┘
                  │
                  │ processes
                  ▼
┌─────────────────────────────────────────────┐
│ Maintenance Layer (Kedro Pipeline)          │
│ - Deduplication                             │
│ - Validation                                │
│ - Compaction                                │
│ - Quality checks                            │
└─────────────────┬───────────────────────────┘
                  │
                  │ writes to
                  ▼
┌─────────────────────────────────────────────┐
│ Clean Parquet Files (deduplicated)         │
│ data_clean/                                 │
│ ├── stocks/                                 │
│ │   └── historical_bars/*.parquet           │
│ └── options/                                │
│     └── option_bars_backfill/*.parquet      │
└─────────────────┬───────────────────────────┘
                  │
                  │ reads from
                  ▼
┌─────────────────────────────────────────────┐
│ Query Layer (Repositories)                  │
│ - Point to data_clean/ by default          │
│ - Option to read from data/ for debugging  │
└─────────────────────────────────────────────┘
```

---

## Kedro Pipeline Implementation

### Project Structure

```
trading_project/
├── dlt-ibapi/                    # DLT connector (ingestion only)
│   ├── src/dlt_ibapi/
│   └── data/                     # Raw Parquet (may have duplicates)
│
└── kedro-pipeline/               # NEW: Kedro project (maintenance)
    ├── conf/
    │   ├── base/
    │   │   ├── catalog.yml       # Dataset definitions
    │   │   └── parameters.yml    # Pipeline params
    │   └── local/
    ├── src/kedro_pipeline/
    │   ├── pipelines/
    │   │   ├── deduplication/
    │   │   │   ├── __init__.py
    │   │   │   ├── nodes.py      # Dedup logic
    │   │   │   └── pipeline.py   # Pipeline definition
    │   │   ├── validation/
    │   │   └── compaction/
    │   └── hooks.py
    └── pyproject.toml
```

---

## Kedro Pipeline: Deduplication

### 1. Catalog Definition (`conf/base/catalog.yml`)

```yaml
# Raw data (from DLT)
equity_bars_raw:
  type: pandas.ParquetDataset
  filepath: ../dlt-ibapi/data/stocks/historical_bars/**/*.parquet
  load_args:
    engine: pyarrow
    use_pandas_metadata: true
  save_args:
    engine: pyarrow
    compression: snappy

# Clean data (after dedup)
equity_bars_clean:
  type: pandas.ParquetDataset
  filepath: data/clean/stocks/historical_bars
  load_args:
    engine: pyarrow
  save_args:
    engine: pyarrow
    compression: snappy
    partition_cols: [date, symbol]
    use_dictionary: true

# Deduplication stats
dedup_stats:
  type: pandas.JSONDataset
  filepath: data/stats/dedup_stats_{run_timestamp}.json
```

### 2. Deduplication Nodes (`pipelines/deduplication/nodes.py`)

```python
"""
Deduplication nodes for market data.

These nodes handle deduplication at the Parquet file level,
independent of DLT.
"""

import pandas as pd
import duckdb
from typing import Dict, Any
from pathlib import Path
import logging

logger = logging.getLogger(__name__)


def deduplicate_equity_bars(
    equity_bars_raw_path: str,
    primary_key: list[str] = ["symbol", "bar_size", "time"],
) -> pd.DataFrame:
    """
    Deduplicate equity bars using DuckDB.

    Primary key: (symbol, bar_size, time)
    Keep latest by _dlt_load_id.

    Args:
        equity_bars_raw_path: Path pattern to raw Parquet files
        primary_key: Columns that define uniqueness

    Returns:
        Deduplicated DataFrame
    """
    logger.info(f"Deduplicating equity bars from {equity_bars_raw_path}")

    conn = duckdb.connect(":memory:")

    # Read all raw Parquet files
    df = conn.execute(f"""
        SELECT
            COUNT(*) as total_rows,
            COUNT(DISTINCT (symbol, bar_size, time)) as unique_rows
        FROM parquet_scan('{equity_bars_raw_path}', hive_partitioning=true)
    """).df()

    total = df.iloc[0]['total_rows']
    unique = df.iloc[0]['unique_rows']
    duplicates = total - unique

    logger.info(f"Total rows: {total}, Unique: {unique}, Duplicates: {duplicates}")

    if duplicates == 0:
        logger.info("No duplicates found, returning all data")
        return conn.execute(f"""
            SELECT * FROM parquet_scan('{equity_bars_raw_path}', hive_partitioning=true)
        """).df()

    # Deduplicate: keep latest by _dlt_load_id
    deduped = conn.execute(f"""
        SELECT DISTINCT ON (symbol, bar_size, time)
            *
        FROM parquet_scan('{equity_bars_raw_path}', hive_partitioning=true)
        ORDER BY symbol, bar_size, time, _dlt_load_id DESC
    """).df()

    logger.info(f"Removed {duplicates} duplicate rows")

    conn.close()
    return deduped


def deduplicate_option_bars(
    option_bars_raw_path: str,
    primary_key: list[str] = ["underlying", "expiry", "strike", "right", "bar_size", "time"],
) -> pd.DataFrame:
    """
    Deduplicate option bars using DuckDB.

    Primary key: (underlying, expiry, strike, right, bar_size, time)
    Keep latest by _dlt_load_id.
    """
    logger.info(f"Deduplicating option bars from {option_bars_raw_path}")

    conn = duckdb.connect(":memory:")

    # Check for duplicates
    df = conn.execute(f"""
        SELECT
            COUNT(*) as total_rows,
            COUNT(DISTINCT (underlying, expiry, strike, right, bar_size, time)) as unique_rows
        FROM parquet_scan('{option_bars_raw_path}', hive_partitioning=true)
    """).df()

    total = df.iloc[0]['total_rows']
    unique = df.iloc[0]['unique_rows']
    duplicates = total - unique

    logger.info(f"Total rows: {total}, Unique: {unique}, Duplicates: {duplicates}")

    if duplicates == 0:
        return conn.execute(f"""
            SELECT * FROM parquet_scan('{option_bars_raw_path}', hive_partitioning=true)
        """).df()

    # Deduplicate
    deduped = conn.execute(f"""
        SELECT DISTINCT ON (underlying, expiry, strike, right, bar_size, time)
            *
        FROM parquet_scan('{option_bars_raw_path}', hive_partitioning=true)
        ORDER BY underlying, expiry, strike, right, bar_size, time, _dlt_load_id DESC
    """).df()

    logger.info(f"Removed {duplicates} duplicate rows")

    conn.close()
    return deduped


def generate_dedup_stats(
    raw_df: pd.DataFrame,
    clean_df: pd.DataFrame,
    dataset_name: str,
) -> Dict[str, Any]:
    """Generate statistics about deduplication."""
    return {
        "dataset": dataset_name,
        "raw_rows": len(raw_df),
        "clean_rows": len(clean_df),
        "duplicates_removed": len(raw_df) - len(clean_df),
        "dedup_percentage": round(
            (len(raw_df) - len(clean_df)) / len(raw_df) * 100, 2
        ) if len(raw_df) > 0 else 0,
    }
```

### 3. Pipeline Definition (`pipelines/deduplication/pipeline.py`)

```python
"""
Deduplication pipeline.

Runs independently of DLT ingestion.
Can be scheduled (e.g., daily at 2 AM) or triggered manually.
"""

from kedro.pipeline import Pipeline, node, pipeline
from .nodes import (
    deduplicate_equity_bars,
    deduplicate_option_bars,
    generate_dedup_stats,
)


def create_pipeline(**kwargs) -> Pipeline:
    """Create deduplication pipeline."""
    return pipeline(
        [
            # Deduplicate equity bars
            node(
                func=deduplicate_equity_bars,
                inputs="params:equity_bars_raw_path",
                outputs="equity_bars_deduped",
                name="deduplicate_equity_bars_node",
            ),
            # Save clean equity bars
            node(
                func=lambda df: df,
                inputs="equity_bars_deduped",
                outputs="equity_bars_clean",
                name="save_equity_bars_clean_node",
            ),
            # Generate stats
            node(
                func=generate_dedup_stats,
                inputs={
                    "raw_df": "equity_bars_raw",
                    "clean_df": "equity_bars_deduped",
                    "dataset_name": "params:dataset_name",
                },
                outputs="dedup_stats",
                name="generate_dedup_stats_node",
            ),

            # Same for options (if needed)
            # node(...),
        ],
        tags=["deduplication", "maintenance"],
    )
```

### 4. Parameters (`conf/base/parameters.yml`)

```yaml
# Deduplication parameters
deduplication:
  equity_bars_raw_path: "../dlt-ibapi/data/stocks/historical_bars/**/*.parquet"
  option_bars_raw_path: "../dlt-ibapi/data/options/option_bars_backfill/**/*.parquet"
  dataset_name: "stocks"
```

---

## Usage

### Manual Run

```bash
# Run deduplication pipeline
cd kedro-pipeline
kedro run --pipeline deduplication

# Run specific node
kedro run --node deduplicate_equity_bars_node

# Run with parameters
kedro run --pipeline deduplication --params "dataset_name=options"
```

### Scheduled Run (Cron)

```bash
# Daily at 2 AM
0 2 * * * cd /path/to/kedro-pipeline && kedro run --pipeline deduplication

# Weekly on Sunday
0 2 * * 0 cd /path/to/kedro-pipeline && kedro run --pipeline deduplication
```

### Airflow DAG (Production)

```python
from airflow import DAG
from airflow.operators.bash import BashOperator
from datetime import datetime, timedelta

default_args = {
    'owner': 'data-team',
    'depends_on_past': False,
    'start_date': datetime(2025, 10, 21),
    'email_on_failure': True,
    'email_on_retry': False,
    'retries': 2,
    'retry_delay': timedelta(minutes=5),
}

dag = DAG(
    'market_data_deduplication',
    default_args=default_args,
    description='Deduplicate market data Parquet files',
    schedule_interval='0 2 * * *',  # Daily at 2 AM
    catchup=False,
)

deduplicate_task = BashOperator(
    task_id='deduplicate_market_data',
    bash_command='cd /path/to/kedro-pipeline && kedro run --pipeline deduplication',
    dag=dag,
)
```

---

## Update dlt-ibapi Readers to Use Clean Data

### Configuration

```python
# src/dlt_ibapi/config.py

class DataConfig(BaseModel):
    """Configuration for data storage paths."""
    raw_data_dir: str = "data"          # DLT writes here
    clean_data_dir: str = "data_clean"  # Kedro dedup writes here
    use_clean_data: bool = True         # Default to clean data
```

### Reader Updates

```python
# src/dlt_ibapi/repositories/parquet_reader.py

class ParquetReaderBase(ABC):
    def __init__(
        self,
        database_path: Union[str, Path],
        dataset_name: str = "stocks",
        use_clean_data: bool = True,  # NEW
    ):
        """
        Initialize Parquet reader.

        Args:
            database_path: Path to Parquet data directory
            dataset_name: DLT dataset name
            use_clean_data: If True, read from data_clean/ (deduplicated)
                           If False, read from data/ (raw, may have duplicates)
        """
        self.database_path = Path(database_path)
        self.dataset_name = dataset_name
        self.destination_type = "filesystem"

        # Choose raw or clean data
        if use_clean_data:
            # Check if clean data exists
            clean_root = self.database_path.parent / "data_clean" / dataset_name
            if clean_root.exists():
                self.data_root = clean_root
                logger.info(f"Using clean data from {clean_root}")
            else:
                logger.warning(f"Clean data not found at {clean_root}, using raw data")
                self.data_root = self.database_path / dataset_name
        else:
            self.data_root = self.database_path / dataset_name

        if not self.data_root.exists():
            raise ValueError(f"Data directory does not exist: {self.data_root}")
```

---

## Benefits of Kedro Approach

### 1. **Separation of Concerns**

| Tool | Responsibility | Focus |
|------|---------------|-------|
| DLT | Ingestion | Speed, reliability |
| Kedro | Maintenance | Quality, validation |
| Query Layer | Analytics | Performance |

### 2. **Independent Scheduling**

```
Ingestion (DLT):     Every 5 minutes (real-time)
Deduplication (Kedro): Daily at 2 AM (batch)
Compaction (Kedro):   Weekly on Sunday
Validation (Kedro):   After each dedup
```

### 3. **Easy to Test**

```bash
# Test dedup logic independently
kedro test

# Test specific node
kedro run --node deduplicate_equity_bars_node

# Dry run
kedro run --pipeline deduplication --dry-run
```

### 4. **Observable**

Kedro provides:
- Pipeline visualization (`kedro viz`)
- Execution logs
- Data lineage
- Performance metrics

### 5. **Extensible**

Easy to add more pipelines:

```
kedro-pipeline/
├── pipelines/
│   ├── deduplication/       # Remove duplicates
│   ├── validation/          # Check data quality
│   ├── compaction/          # Merge small files
│   ├── aggregation/         # Create summary tables
│   └── backtest_prep/       # Prepare data for backtesting
```

---

## Migration Path

### Phase 1: Keep DLT As-Is (Week 1)

- ✅ No changes to dlt-ibapi
- ✅ Create Kedro project
- ✅ Implement dedup pipeline
- ✅ Test on copy of data

### Phase 2: Add Clean Data Path (Week 2)

- Update readers to support `use_clean_data=True`
- Add configuration option
- Test with both raw and clean data

### Phase 3: Schedule Dedup Job (Week 3)

- Set up daily cron job or Airflow DAG
- Monitor dedup stats
- Alert on anomalies

### Phase 4: Expand Maintenance (Month 2+)

- Add validation pipeline
- Add compaction pipeline
- Add quality checks

---

## Immediate Next Steps

1. **Create Kedro project:**
   ```bash
   cd /path/to/trading_project
   kedro new --name kedro-pipeline
   cd kedro-pipeline
   kedro install
   ```

2. **Implement dedup nodes** (copy code above)

3. **Test locally:**
   ```bash
   kedro run --pipeline deduplication
   ```

4. **Schedule:**
   ```bash
   # Add to crontab
   crontab -e
   # Add: 0 2 * * * cd /path/to/kedro-pipeline && kedro run --pipeline deduplication
   ```

---

## Summary

**DLT's Job:** Fast append-only ingestion (no dedup overhead)

**Kedro's Job:** Maintain clean data (dedup, validate, compact)

**Query Layer:** Read from clean data by default

This is the **standard pattern** for modern data pipelines:
- Ingest → raw zone (fast)
- Transform → clean zone (quality)
- Consume → clean zone (correct)

**Estimated effort:** 4-6 hours to set up basic Kedro dedup pipeline

---

**Prepared by:** Architecture Design
**Date:** 2025-10-21
**Recommendation:** ✅ Implement Kedro-based deduplication
