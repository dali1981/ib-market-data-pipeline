# Architecture Clarification: DLT vs Dagster

## The Confusion

**Question:** Should DLT resources be used directly as Dagster assets, or called from within Dagster assets?

## The Answer

**DLT resources should be CALLED FROM WITHIN Dagster assets, not BE the assets themselves.**

---

## DLT's Role

DLT is a **data ingestion library**. It provides:
- Resources (generators that yield data)
- Pipeline orchestration (run resources, write to destinations)
- Schema management
- Incremental loading

DLT is NOT an orchestrator like Dagster. It's a tool for ETL.

---

## Dagster's Role

Dagster is an **orchestration framework**. It provides:
- Asset lineage and dependencies
- Scheduling
- Monitoring and observability
- Multi-asset coordination
- State management

---

## How They Work Together

```python
# ❌ WRONG: DLT resource AS a Dagster asset
@asset
def stock_data():
    # This makes the asset tightly coupled to DLT internals
    return backfill_equity_bars(...)  # DLT resource


# ✅ CORRECT: DLT resource CALLED FROM Dagster asset
@asset
def stock_historical_data(context, ticker_contracts):
    """Dagster asset that orchestrates DLT pipeline"""
    symbols = ticker_contracts["tickers_resolved"]

    # Dagster handles orchestration
    # DLT handles data ingestion
    pipeline = dlt.pipeline(
        pipeline_name="stock_historical_data",
        destination="filesystem",
        dataset_name="stocks",
    )

    for symbol in symbols:
        # Call DLT resource (library code)
        resource = backfill_equity_bars(
            symbol=symbol,
            database_path=config.database_path,
            ...
        )

        # DLT writes to Parquet
        pipeline.run(resource)

    # Dagster tracks completion
    return {"symbols_processed": symbols}
```

---

## The Architecture Layers

```
┌─────────────────────────────────────────┐
│         Dagster (Orchestration)         │
│  - Asset dependencies                   │
│  - Scheduling                           │
│  - Monitoring                           │
│  - Returns: Status/Metadata             │
└─────────────────┬───────────────────────┘
                  │ calls
                  ↓
┌─────────────────────────────────────────┐
│      DLT Library (Data Ingestion)       │
│  - Resources (generators)               │
│  - Pipeline.run()                       │
│  - Writes: Parquet files                │
└─────────────────┬───────────────────────┘
                  │ uses
                  ↓
┌─────────────────────────────────────────┐
│    IB Connector Services (Data Source)  │
│  - HistoricalService                    │
│  - ContractDetailsService               │
│  - SecDefService                        │
└─────────────────┬───────────────────────┘
                  │ fetches from
                  ↓
┌─────────────────────────────────────────┐
│         IB Gateway (External API)       │
└─────────────────────────────────────────┘
```

---

## What Lives Where

### In `src/dlt_ibapi/` (Library - Reusable)

**Services:** (`services/`)
- Contract resolution logic
- Data transformation logic
- Business logic (reusable outside Dagster)

**Resources:** (`backfill/resources.py`)
- DLT resources (generators)
- `backfill_equity_bars()`
- `snapshot_option_chain()`
- `backfill_option_bars()`
- **NEW: `select_option_contracts_resource()`**

**Repositories:** (`repositories/`)
- Parquet readers (DuckDB queries)
- `EquityBarsReader`
- `OptionChainSnapshotReader`
- **NEW: `SelectedContractsReader`**

### In `dagster_options/` (Orchestration - Dagster-specific)

**Assets:** (`assets.py`)
- Thin wrappers
- Call library DLT resources
- Handle asset dependencies
- Return lightweight status
- Log progress

**Definitions:** (`definitions.py`)
- Job definitions
- Asset groupings
- Schedules (if any)

**Config:** (`config.py`)
- Pipeline configuration
- Dagster-specific settings

---

## Example Flow: `select_option_contracts`

### WRONG (Current Implementation)
```python
# dagster_options/assets.py
@asset
def select_option_contracts(context, ...):
    # ❌ Complex logic IN the asset
    stock_reader = EquityBarsReader(...)
    chain_reader = OptionChainSnapshotReader(...)

    runtime = IBRuntime(...)  # ❌ Direct IB connection in asset
    details_service = ContractDetailsService(runtime)

    for symbol in symbols:
        stock_data = stock_reader.get_bars(...)  # ❌ Business logic in asset
        chain = chain_reader.get_chain(...)

        for expiry in expirations:
            for strategy in strategies:
                selected = select_contracts_by_strategy(...)  # ❌ Complex loop

                for contract in selected:
                    opt_contract = make_option(...)
                    details = details_service.fetch(...)  # ❌ IB calls in asset
                    all_contracts.append(...)

    return pd.DataFrame(all_contracts)  # ❌ Returns data, not status
```

### CORRECT (Proposed)
```python
# src/dlt_ibapi/backfill/resources.py
@dlt.resource(
    name="selected_option_contracts",
    write_disposition="replace",
    primary_key=["underlying", "expiry", "strike", "right"],
)
def select_option_contracts_resource(
    symbols: List[str],
    snapshot_date: date,
    database_path: str,
    delta_config: DeltaSelectionConfig,
    connection_config: IBConnectionConfig,
) -> Iterator[dict]:
    """
    DLT resource to select and resolve option contracts.

    1. Reads option chains from Parquet
    2. Reads stock prices from Parquet
    3. Applies delta selection strategies
    4. Resolves contracts via IB Gateway
    5. Yields contract records to DLT
    """
    # All the complex logic lives here
    stock_reader = EquityBarsReader(database_path, "stocks")
    chain_reader = OptionChainSnapshotReader(database_path, "option_chains")

    runtime = _get_runtime(connection_config)
    details_service = ContractDetailsService(runtime)

    try:
        for symbol in symbols:
            # Read from Parquet
            stock_data = stock_reader.get_bars(symbol, ...)
            chain = chain_reader.get_chain_for_date(symbol, snapshot_date)

            # Apply strategies
            for expiry in chain_reader.get_available_expirations(...):
                strikes = chain_reader.get_strikes_for_expiry(...)

                for strategy in ["closest_match", "black_scholes"]:
                    selected = select_contracts_by_strategy(
                        strikes, spot_price, strategy, delta_config
                    )

                    # Resolve contracts
                    for contract in selected:
                        opt_contract = make_option(...)
                        details = details_service.fetch(opt_contract)

                        if details:
                            yield {
                                "underlying": symbol,
                                "expiry": expiry,
                                "strike": contract["strike"],
                                "right": contract["right"],
                                "conid": details[0].contract.conId,
                                "local_symbol": details[0].contract.localSymbol,
                                "exchange": details[0].contract.exchange,
                                "trading_class": details[0].contract.tradingClass,
                                "multiplier": details[0].multiplier,
                                "strategy": strategy,
                                "delta": contract.get("delta"),
                            }
    finally:
        runtime.stop()


# dagster_options/assets.py
@asset(...)
def select_option_contracts(
    context,
    stock_historical_data,
    option_chain_snapshots,
):
    """Thin Dagster wrapper"""
    # ✅ Simple orchestration
    config = get_default_config()
    symbols = option_chain_snapshots["chains_captured"]
    snapshot_date = option_chain_snapshots["snapshot_date"]

    context.log.info(f"Selecting contracts for {len(symbols)} symbols")

    # ✅ Call DLT resource (library)
    pipeline = dlt.pipeline(
        pipeline_name="selected_option_contracts",
        destination="filesystem",
        dataset_name="selected_contracts",
    )

    resource = select_option_contracts_resource(
        symbols=symbols,
        snapshot_date=snapshot_date,
        database_path=config.database_path,
        delta_config=config.delta_config,
        connection_config=get_connection_config(),
    )

    # ✅ DLT writes to Parquet
    load_info = pipeline.run(resource)

    # ✅ Return status, not data
    return {
        "contracts_selected": count_rows(load_info),
        "symbols_processed": symbols,
    }
```

---

## Key Principles

1. **DLT resources are library code** - reusable, testable, Dagster-agnostic
2. **Dagster assets are thin wrappers** - orchestration, logging, status
3. **Complex logic lives in the library** - not in Dagster assets
4. **Assets return status** - not full DataFrames
5. **Data flows through Parquet** - not through asset return values

---

## Benefits

- ✅ **Reusability**: DLT resources can be used outside Dagster
- ✅ **Testability**: Test library code without Dagster
- ✅ **Maintainability**: Business logic separate from orchestration
- ✅ **Performance**: Data written to disk, not passed in memory
- ✅ **Scalability**: Parquet enables incremental processing

---

## Summary

**DLT is NOT used directly as Dagster assets.**

Instead:
1. Write DLT resources in the library (`src/dlt_ibapi/`)
2. Call those resources from thin Dagster assets (`dagster_options/`)
3. DLT handles data ingestion → Parquet
4. Dagster handles orchestration → Status tracking