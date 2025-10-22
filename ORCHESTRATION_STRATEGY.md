# Orchestration Strategy: Dagster vs Kedro

## Executive Summary

**Recommendation:** Use **Dagster with native DLT integration** instead of Kedro.

**Key Reasons:**
- ✅ Native DLT integration via `dagster-dlt` package
- ✅ Built-in scheduling and orchestration (no need for external tools)
- ✅ Asset-first model perfect for versioned data artifacts
- ✅ Great local development UI
- ✅ Easy to extend for feature engineering and backtesting

---

## Comparison Table

| Feature | Dagster + DLT | Kedro + DLT | Winner |
|---------|---------------|-------------|---------|
| **DLT Integration** | Native (`dagster-dlt`) | Manual wrapping needed | 🏆 Dagster |
| **Scheduling** | Built-in schedules & sensors | None (need Airflow/Prefect) | 🏆 Dagster |
| **Local Dev UI** | Excellent (`dagster dev`) | Basic CLI | 🏆 Dagster |
| **Code Structure** | Asset-based dependencies | Node-based pipelines | Tie |
| **Data Versioning** | Asset versioning built-in | Via data catalog | 🏆 Dagster |
| **Learning Curve** | Medium | Medium-Low | Tie |
| **Production Ready** | Yes (all-in-one) | No (need orchestrator) | 🏆 Dagster |
| **Community** | Growing fast | Established | Tie |
| **Use Case Fit** | Data pipelines, ML | ML projects, team standards | 🏆 Dagster (for this project) |

**Result:** Dagster wins 6/9 categories for this use case.

---

## Detailed Analysis

### Dagster Strengths

#### 1. Native DLT Integration

```python
# Dagster with dagster-dlt
from dagster_dlt import dlt_assets, DagsterDltResource

@dlt_assets(
    dlt_source=ib_historical_bars(...),
    dlt_pipeline=dlt.pipeline(
        destination=dlt.destinations.filesystem(bucket_url="data"),
        dataset_name="stocks"
    ),
    name="equity_bars_raw"
)
def equity_bars_ingestion():
    pass  # dagster-dlt handles everything!
```

**vs Kedro** (manual):
```python
# Kedro - need custom wrapper
def ingest_equity_bars():
    pipeline = dlt.pipeline(...)
    info = pipeline.run(ib_historical_bars(...))
    return info
```

#### 2. Scheduling Built-In

```python
# Dagster schedules
from dagster import schedule, ScheduleDefinition

@schedule(cron_schedule="*/5 * * * *", job=dlt_ingestion_job)
def ingestion_schedule(context):
    return {}

@schedule(cron_schedule="0 2 * * *", job=dedup_job)
def dedup_schedule(context):
    return {}
```

**vs Kedro** (need external tool):
```bash
# Cron (brittle)
*/5 * * * * kedro run --pipeline ingestion

# OR Airflow (extra complexity)
from airflow import DAG
from airflow.providers.kedro import KedroOperator
# ... lots of boilerplate
```

#### 3. Asset Lineage & Dependencies

```python
# Dagster assets automatically track dependencies
@asset(deps=[equity_bars_raw])
def equity_bars_clean(context, equity_bars_raw):
    # Deduplication logic
    return deduplicated_df

@asset(deps=[equity_bars_clean])
def technical_indicators(context, equity_bars_clean):
    # Feature engineering
    return features_df
```

**Lineage visualization in UI:**
```
equity_bars_raw → equity_bars_clean → technical_indicators → backtest_dataset
```

**vs Kedro** - Similar node dependencies but:
- ❌ No built-in lineage UI
- ❌ Need external tool for visualization
- ❌ No asset versioning out of the box

#### 4. Sensors for Event-Driven Pipelines

```python
# Dagster sensor - run when new data arrives
from dagster import sensor, RunRequest

@sensor(job=dedup_job)
def new_data_sensor(context):
    # Check if new Parquet files exist
    new_files = check_for_new_data()
    if new_files:
        return RunRequest(run_key=str(new_files))
```

**vs Kedro** - No native sensor support.

---

### Kedro Strengths

#### 1. Software Engineering Discipline

Kedro enforces:
- ✅ Strict project structure
- ✅ Separation of parameters, catalog, pipelines
- ✅ Modular, reusable nodes
- ✅ Testing best practices

**Great for:** Large teams, strict ML engineering standards

**Our case:** Single developer, data-focused (not ML-heavy yet)

**Verdict:** ⚠️ Kedro's discipline is valuable but overkill for current needs

#### 2. Data Catalog

```yaml
# Kedro catalog.yml
equity_bars_raw:
  type: pandas.ParquetDataset
  filepath: data/stocks/historical_bars/**/*.parquet
  load_args:
    engine: pyarrow
  save_args:
    compression: snappy
```

**Pros:**
- ✅ Centralized data definitions
- ✅ Easy to swap backends (local ↔ S3)
- ✅ Automatic data loading/saving

**Dagster equivalent:**
```python
# Dagster I/O managers
@io_manager
def parquet_io_manager():
    # Handle load/save logic
    pass
```

**Verdict:** Both support data abstraction, Dagster's is more flexible

#### 3. Hooks for MLOps

```python
# Kedro hook for experiment tracking
class MLflowHook:
    def before_pipeline_run(self):
        mlflow.start_run()

    def after_pipeline_run(self):
        mlflow.end_run()
```

**Good for:** ML experiment tracking

**Our case:** Not doing ML training yet (just data prep)

**Verdict:** Useful later, but Dagster has similar capabilities

---

## Why NOT Kedro for This Project

### 1. Missing Core Requirements

**You need:**
- ✅ Scheduling (Kedro: ❌)
- ✅ DLT integration (Kedro: ❌ manual)
- ✅ Orchestration UI (Kedro: ❌ basic)
- ✅ Asset versioning (Kedro: ⚠️ limited)

**Workaround:** Add Airflow/Prefect
**Problem:** Now managing 2 tools instead of 1

### 2. Not ML-First (Yet)

Kedro shines for:
- ML experiment tracking
- Feature store management
- Model training pipelines
- Team collaboration on ML projects

Your current focus:
- Data ingestion (DLT)
- Data quality (deduplication)
- Data transformation (basic cleaning)
- **Future:** Feature engineering, backtesting

**Verdict:** Kedro's ML focus doesn't match current needs

### 3. Extra Complexity Without Benefit

**Kedro setup:**
```
dlt-ibapi/          # DLT connector
kedro-pipeline/     # Kedro project
airflow/            # Orchestrator (needed!)
```

**Dagster setup:**
```
dlt-ibapi/          # DLT connector
dagster-pipeline/   # All-in-one: orchestration + structure
```

**Simpler = Better**

---

## Recommended Architecture: Dagster + DLT

### Project Structure

```
trading_project/
├── dlt-ibapi/                    # DLT connector (unchanged)
│   ├── src/dlt_ibapi/
│   ├── data/                     # Raw Parquet (from DLT)
│   └── data_clean/               # Clean Parquet (from Dagster dedup)
│
└── dagster-ib-pipeline/          # NEW: Dagster orchestration
    ├── dagster_ib_pipeline/
    │   ├── __init__.py
    │   ├── assets/
    │   │   ├── __init__.py
    │   │   ├── dlt_ingestion.py       # DLT assets (dagster-dlt)
    │   │   ├── deduplication.py       # Dedup logic
    │   │   ├── feature_engineering.py # (Future)
    │   │   └── backtesting.py         # (Future)
    │   ├── resources/
    │   │   ├── __init__.py
    │   │   └── duckdb_resource.py     # DuckDB connection
    │   ├── schedules/
    │   │   └── __init__.py
    │   ├── sensors/
    │   │   └── __init__.py
    │   └── jobs/
    │       └── __init__.py
    ├── setup.py
    └── pyproject.toml
```

### Data Flow

```
1. DLT Ingestion (Dagster Asset)
   ↓
   data/stocks/historical_bars/*.parquet (raw)
   ↓
2. Deduplication (Dagster Asset, depends on #1)
   ↓
   data_clean/stocks/historical_bars/*.parquet (clean)
   ↓
3. Feature Engineering (Dagster Asset, depends on #2)
   ↓
   data_clean/stocks/features/*.parquet
   ↓
4. Backtesting (Dagster Asset, depends on #3)
   ↓
   data_clean/backtest_results/*.parquet
```

### Scheduling

```python
# schedules/__init__.py

from dagster import ScheduleDefinition, DefaultScheduleStatus

# Run DLT ingestion every 5 minutes during market hours
ingestion_schedule = ScheduleDefinition(
    name="dlt_ingestion_schedule",
    cron_schedule="*/5 9-16 * * 1-5",  # Mon-Fri, 9am-4pm
    job_name="dlt_ingestion_job",
    default_status=DefaultScheduleStatus.RUNNING,
)

# Run deduplication daily at 2 AM
dedup_schedule = ScheduleDefinition(
    name="dedup_schedule",
    cron_schedule="0 2 * * *",  # Daily 2 AM
    job_name="dedup_job",
    default_status=DefaultScheduleStatus.RUNNING,
)

# Run feature engineering daily at 3 AM (after dedup)
features_schedule = ScheduleDefinition(
    name="features_schedule",
    cron_schedule="0 3 * * *",  # Daily 3 AM
    job_name="features_job",
    default_status=DefaultScheduleStatus.RUNNING,
)
```

### Sensors (Event-Driven)

```python
# sensors/__init__.py

from dagster import sensor, RunRequest, SensorEvaluationContext
from pathlib import Path

@sensor(job_name="dedup_job", minimum_interval_seconds=300)
def new_data_sensor(context: SensorEvaluationContext):
    """
    Trigger dedup when new raw data arrives.
    Checks every 5 minutes for new Parquet files.
    """
    raw_data_path = Path("../dlt-ibapi/data/stocks/historical_bars")

    # Get modification time of newest file
    latest_file = max(raw_data_path.glob("*.parquet"), key=lambda p: p.stat().st_mtime)
    latest_mtime = latest_file.stat().st_mtime

    # Get last processed time from cursor
    last_mtime = context.cursor or "0"

    if latest_mtime > float(last_mtime):
        # New data detected!
        context.update_cursor(str(latest_mtime))
        return RunRequest(
            run_key=f"new_data_{latest_mtime}",
            run_config={"ops": {"deduplicate": {"config": {"trigger": "sensor"}}}}
        )
```

---

## Implementation Phases

### Phase 1: Setup (Week 1)

**Goal:** Get Dagster running with basic DLT integration

**Tasks:**
1. Create Dagster project: `dagster-ib-pipeline`
2. Install dependencies: `dagster`, `dagster-dlt`, `dagster-webserver`
3. Wrap `dlt-ibapi` sources as Dagster assets
4. Test in Dagster UI (`dagster dev`)

**Deliverables:**
- Working Dagster project
- DLT ingestion as Dagster asset
- Local UI at `localhost:3000`

### Phase 2: Deduplication (Week 2)

**Goal:** Add dedup asset that depends on DLT ingestion

**Tasks:**
1. Create deduplication asset in `assets/deduplication.py`
2. Implement DuckDB-based dedup logic (DISTINCT ON)
3. Write clean data to `data_clean/`
4. Add dedup schedule (daily 2 AM)
5. Test asset dependencies

**Deliverables:**
- Deduplicated Parquet files in `data_clean/`
- Scheduled dedup job
- Asset lineage visualization

### Phase 3: Feature Engineering (Month 2)

**Goal:** Add technical indicators and option Greeks

**Tasks:**
1. Create feature engineering assets
2. Add TA-Lib indicators (SMA, EMA, RSI, MACD, etc.)
3. Calculate option Greeks (if applicable)
4. Store features as partitioned Parquet
5. Schedule after dedup completes

**Deliverables:**
- Feature datasets
- Dependency: `equity_bars_clean → technical_indicators`

### Phase 4: Backtesting Integration (Month 3+)

**Goal:** Prepare data for backtesting frameworks

**Tasks:**
1. Create backtest prep assets
2. Format data for vectorbt/backtrader
3. Add sensor to trigger on new features
4. Store backtest results as assets
5. Add Dagster asset checks for data quality

**Deliverables:**
- Backtest-ready datasets
- Automated backtest triggering
- Results tracking

---

## Local Development Workflow

### 1. Start Dagster UI

```bash
cd dagster-ib-pipeline
dagster dev
```

Opens UI at `http://localhost:3000`

### 2. View Asset Lineage

Navigate to **Assets** → See dependency graph:
```
[equity_bars_raw] → [equity_bars_clean] → [technical_indicators]
```

### 3. Materialize Assets

**Option A:** Click "Materialize" in UI

**Option B:** CLI
```bash
dagster asset materialize --select equity_bars_raw
dagster asset materialize --select equity_bars_clean
dagster asset materialize --select "*"  # All assets
```

### 4. View Runs

Navigate to **Runs** → See execution history, logs, errors

### 5. Test Schedules

```bash
# Test schedule without actually running
dagster schedule list
dagster schedule preview dedup_schedule

# Start/stop schedules
dagster schedule start dedup_schedule
dagster schedule stop dedup_schedule
```

### 6. Test Sensors

```bash
# Test sensor evaluation
dagster sensor preview new_data_sensor
```

---

## Deployment (Future)

When ready for production, Dagster supports:

- **Dagster Cloud** (managed service)
- **Docker** (self-hosted)
- **Kubernetes** (helm charts available)
- **AWS/GCP/Azure** (various deployment guides)

**For now:** Local development only (as requested)

---

## Cost-Benefit Analysis

### Dagster Setup Cost

| Task | Time |
|------|------|
| Install & setup | 1 hour |
| Learn basics | 2 hours |
| Wrap DLT sources | 2 hours |
| Create dedup asset | 3 hours |
| Set up schedules | 1 hour |
| **Total** | **9 hours** |

### Kedro + Airflow Setup Cost

| Task | Time |
|------|------|
| Install Kedro | 1 hour |
| Learn basics | 3 hours |
| Create pipelines | 4 hours |
| Install Airflow | 2 hours |
| Create DAGs | 3 hours |
| Connect Kedro ↔ Airflow | 2 hours |
| **Total** | **15 hours** |

**Savings:** 6 hours + ongoing maintenance simplicity

### Ongoing Maintenance

**Dagster:**
- 1 tool to update
- 1 UI to monitor
- 1 set of concepts to remember

**Kedro + Airflow:**
- 2 tools to update
- 2 UIs to monitor
- 2 sets of concepts to juggle

---

## Decision Matrix

| Criteria | Weight | Dagster | Kedro + Airflow | Winner |
|----------|--------|---------|-----------------|---------|
| DLT Integration | 10 | 10 (native) | 5 (manual) | 🏆 Dagster |
| Scheduling | 10 | 10 (built-in) | 10 (Airflow) | Tie |
| Setup Time | 8 | 9 (1 tool) | 5 (2 tools) | 🏆 Dagster |
| Local Dev UX | 8 | 10 (great UI) | 7 (CLI only) | 🏆 Dagster |
| Learning Curve | 6 | 7 | 6 | 🏆 Dagster |
| Code Structure | 7 | 9 (assets) | 9 (nodes) | Tie |
| Future ML Needs | 5 | 8 | 9 | Kedro |
| Community Support | 4 | 8 | 8 | Tie |

**Weighted Score:**
- **Dagster:** 8.9 / 10
- **Kedro + Airflow:** 7.5 / 10

**Winner:** 🏆 **Dagster**

---

## Conclusion

**Use Dagster** for this project because:

1. ✅ **Native DLT integration** saves time and reduces errors
2. ✅ **All-in-one solution** (no need for Airflow/Prefect)
3. ✅ **Asset model** perfect for versioned data artifacts
4. ✅ **Great local dev** experience with UI
5. ✅ **Flexible enough** for future ML workflows

**When to revisit Kedro:**
- If project becomes primarily ML-focused (model training, not just data prep)
- If need to enforce strict team standards across large team
- If Dagster proves insufficient for specific ML workflows

**For now:** Start with Dagster, can always migrate later if needs change.

---

## Next Steps

1. ✅ **Approve this plan** (done)
2. ⏳ **Create Dagster project structure**
3. ⏳ **Install dependencies**
4. ⏳ **Implement DLT assets**
5. ⏳ **Add deduplication**
6. ⏳ **Test in UI**
7. ⏳ **Document**

---

**Prepared by:** Architecture Planning
**Date:** 2025-10-21
**Status:** ✅ APPROVED - Ready for implementation
