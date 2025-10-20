# Parquet Migration Plan

**Date**: 2025-10-20
**Status**: In Progress
**Goal**: Migrate all market data storage from DuckDB files to Parquet files

---

## Overview

Convert the dlt-ibapi project to store all **market data** in Parquet files, while keeping DuckDB for **metadata/state only**. Use DLT's filesystem destination for writing and a hybrid query approach (DuckDB for small data, PyArrow for large datasets).

---

## Architecture Changes

### Current Architecture
```
DLT Pipeline → DuckDB (.duckdb files)
              ├── Market data (equity bars, option bars, snapshots)
              └── DLT metadata (_dlt_loads, _dlt_pipeline_state)

Query: DuckDB SQL queries via BaseReader
```

### New Architecture
```
DLT Pipeline → Filesystem Destination (Parquet)
              ├── Market data → Parquet files (partitioned by date/symbol)
              └── DLT metadata → DuckDB (small .duckdb file)

Query:
  - Small data (snapshots, metadata) → DuckDB in-memory queries on Parquet
  - Large data (historical bars) → PyArrow dataset with predicate pushdown
```

---

## File Structure (After Migration)

```
trading_project/dlt-ibapi/
├── data/                                    # NEW: Parquet data directory
│   ├── equity_bars/                         # Equity historical data
│   │   ├── date=2025-10-20/
│   │   │   ├── symbol=AAPL/*.parquet
│   │   │   ├── symbol=MSFT/*.parquet
│   │   │   └── symbol=GOOGL/*.parquet
│   │   └── date=2025-10-21/
│   │       └── ...
│   ├── option_bars/                         # Option historical data
│   │   ├── date=2025-10-20/
│   │   │   ├── symbol=AAPL/*.parquet
│   │   │   └── ...
│   │   └── ...
│   ├── option_chain_snapshot/               # Option chain snapshots
│   │   ├── date=2025-10-20/
│   │   │   └── symbol=AAPL/*.parquet
│   │   └── ...
│   └── _dlt/                                # DLT metadata tables
│       ├── _dlt_loads.parquet
│       ├── _dlt_pipeline_state.parquet
│       └── _dlt_version.parquet
│
├── .dlt-ibapi/
│   ├── cache/contracts/                     # Contract cache (unchanged)
│   ├── ib_gateway.yaml                      # Config (unchanged)
│   └── pipeline_metadata.duckdb             # NEW: Small DuckDB for DLT state only
│
└── ib_option_chains.duckdb                  # REMOVE: No longer needed
```

---

## Implementation Phases

### Phase 1: Update DLT Pipeline Configuration ✅ COMPLETE
**Estimated**: 1-2 hours
**Actual**: TBD

**Files Modified:**
- [x] `.dlt/config.toml` - Created DLT configuration
- [x] `pyproject.toml` - Added filesystem and parquet extras to DLT
- [ ] Update all pipeline creation calls

**Changes:**
- Set Parquet as default file format
- Configure filesystem destination with date/symbol partitioning
- Keep DuckDB for metadata only

---

### Phase 2: Create Hybrid Reader Repositories
**Estimated**: 3-4 hours

**Files to Create:**
- [ ] `src/dlt_ibapi/repositories/parquet_reader.py` (~300 lines)

**Files to Modify:**
- [ ] `src/dlt_ibapi/repositories/base.py` (~100 line changes)
- [ ] `src/dlt_ibapi/repositories/equity_bars.py` (~50 line changes)
- [ ] `src/dlt_ibapi/repositories/option_bars.py` (~50 line changes)
- [ ] `src/dlt_ibapi/repositories/option_chain.py` (~50 line changes)

**New Capabilities:**
- DuckDB in-memory queries for small data (snapshots, aggregations)
- PyArrow dataset queries for large data (historical bars)
- Automatic query routing based on data size/type

---

### Phase 3: Update DLT Resources for Partitioning
**Estimated**: 2-3 hours

**Files to Modify:**
- [ ] `src/dlt_ibapi/backfill/resources.py`

**Changes:**
- Add date extraction to all yielded records
- Add partition column hints to resource decorators
- Ensure all resources yield flat dictionaries (no nested arrays)

---

### Phase 4: Update Examples and CLI
**Estimated**: 1-2 hours

**Files to Modify:**
- [ ] `examples/option_chain_snapshot.py`
- [ ] `examples/equity_backfill.py`
- [ ] `examples/option_backfill_complete.py`
- [ ] `examples/basic_pipeline.py`
- [ ] `examples/multi_symbol.py`
- [ ] `src/dlt_ibapi/cli.py`

**Changes:**
- Update all pipeline creations to use filesystem destination
- Update all reader initializations to point to Parquet directory
- Ensure loader_file_format="parquet" is set

---

### Phase 5: Update Tests
**Estimated**: 2-3 hours

**Files to Modify:**
- [ ] `tests/unit/test_repositories.py`
- [ ] `tests/integration/test_snapshot_resource.py`
- [ ] `tests/integration/test_backfill_resource.py`

**Changes:**
- Update fixtures to create temporary Parquet data directories
- Update all reader tests to use new Parquet readers
- Add tests for hybrid query routing

---

### Phase 6: Update Documentation
**Estimated**: 1 hour

**Files to Modify:**
- [ ] `README.md`
- [ ] `docs/BACKFILL_GUIDE.md`
- [ ] `docs/API_REFERENCE.md`
- [ ] `IMPLEMENTATION_STATUS.md`

**Changes:**
- Update all references from DuckDB files to Parquet directories
- Add section explaining Parquet storage and partitioning
- Update query examples to show DuckDB in-memory usage
- Document when to use DuckDB vs PyArrow queries

---

### Phase 7: Add Final Configuration
**Estimated**: 30 min

**Tasks:**
- [ ] Test end-to-end with real IB data
- [ ] Benchmark query performance (DuckDB vs PyArrow)
- [ ] Clean up old DuckDB files
- [ ] Update .gitignore for Parquet directories

---

## Design Decisions

### Partitioning Strategy
**Chosen**: `date=YYYY-MM-DD/symbol=TICKER`

**Rationale**:
- Most queries filter by date range first
- Symbol is secondary partition for efficient per-symbol queries
- Hive-style partitioning is well-supported by DuckDB and PyArrow

### Query Routing Strategy

**Use DuckDB in-memory for**:
- Option chain snapshots (small datasets ~1K rows per symbol)
- Metadata queries (distinct symbols, date ranges, counts)
- Aggregations (min/max dates, row counts)
- Gap detection queries

**Use PyArrow for**:
- Equity bars (large datasets, millions of rows)
- Option bars (large datasets, millions of rows)
- Historical scans across multiple symbols/dates
- Queries with predicate pushdown (filters on partitions)

### DLT Metadata Storage

**Chosen**: Separate small DuckDB file (`.dlt-ibapi/pipeline_metadata.duckdb`)

**Rationale**:
- DLT needs persistent state for tracking loads and schema
- Metadata is small (<1MB typically)
- Separating from market data keeps it manageable
- Easier to backup/restore pipeline state

---

## Benefits

1. **Storage Efficiency**: Parquet compression (~10x better than DuckDB for OHLCV data)
2. **Scalability**: Can handle billions of rows without memory issues
3. **Cloud-Ready**: Easy to migrate to S3/GCS later (just change bucket_url)
4. **Query Performance**:
   - DuckDB in-memory is fast for small queries
   - PyArrow predicate pushdown is fast for large scans
5. **Partitioning**: Date/symbol partitions enable efficient filtering
6. **DLT Benefits**: Still get schema evolution, deduplication, state management

---

## Risks & Mitigation

### Risk 1: Array Normalization
**Issue**: DLT auto-normalizes arrays into child tables, which might not work well with Parquet partitioning

**Mitigation**:
- Flatten arrays before yielding from resources
- Store arrays as JSON strings if needed
- Use separate Parquet files for child relationships

### Risk 2: Query Performance
**Issue**: PyArrow queries might be slower than DuckDB for some use cases

**Mitigation**:
- Hybrid approach lets us choose best tool per query
- Benchmark both approaches and document recommendations
- Cache frequently-accessed data in memory

### Risk 3: Migration Disruption
**Issue**: Changing storage format might break existing workflows

**Mitigation**:
- Thorough testing before merging
- Consider gradual migration with feature flag
- Keep old DuckDB readers as fallback initially

---

## Dependencies

**New packages** (already in pyproject.toml):
```toml
"dlt[filesystem,parquet,duckdb]>=0.4.0"
"pyarrow>=21.0.0"
```

---

## Testing Strategy

1. **Unit Tests**: Test individual reader methods with mock Parquet files
2. **Integration Tests**: Test end-to-end with real DLT pipeline writes
3. **Performance Tests**: Benchmark query times DuckDB vs PyArrow
4. **Data Validation**: Ensure data integrity after migration

---

## Rollback Plan

If migration fails:
1. Revert code changes (git reset)
2. Restore from backup `.duckdb` files
3. Document issues encountered
4. Iterate on plan before retry

---

## Success Criteria

- [ ] All market data stored in Parquet files
- [ ] DuckDB file size < 10MB (metadata only)
- [ ] Query performance equal or better than DuckDB-only
- [ ] All tests passing
- [ ] Documentation updated
- [ ] No data loss or corruption

---

## Timeline

**Start Date**: 2025-10-20
**Target Completion**: TBD
**Total Estimated Effort**: 11-16 hours

---

## Progress Tracking

See `PARQUET_MIGRATION_STATUS.md` for current implementation status.
