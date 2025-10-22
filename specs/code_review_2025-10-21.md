# Code Review — dlt-ibapi (2025-10-21)

## Overview

This review covers the current state of the dlt-ibapi repository after the migration to filesystem + Parquet storage with Hive-style partitioning. It assesses architecture, correctness, consistency, tests/docs, and performance/resilience, and proposes prioritized improvements.

## Architecture

- Data Acquisition (DLT Resources): `src/dlt_ibapi/sources.py` exposes resources for historical bars, market data snapshot, option chain params, contract details, and a composite `ib_source`.
- Backfill Framework: `src/dlt_ibapi/backfill/resources.py` implements gap-aware backfills for equities and options using readers to detect missing dates.
- Contract Resolution & Cache: `src/dlt_ibapi/resolution/resolver.py` + `src/dlt_ibapi/resolution/contract_cache.py` resolve contracts with rate limiting and persist metadata in a Parquet cache.
- Read-Side Repositories (Parquet): Hybrid readers in `src/dlt_ibapi/repositories/*` route metadata/aggregations to DuckDB and scans to PyArrow (`parquet_scan`/predicate pushdown), aligned to Hive partitions.
- Configuration: Pydantic models in `src/dlt_ibapi/config.py` with hierarchical loader (package defaults → user YAML → env) in `src/dlt_ibapi/config_loader.py`.
- CLI: `src/dlt_ibapi/cli.py` provides init/show-config/fetch/snapshot/backfill/stats commands.

## Strengths

- Clear separation of concerns between resource-side ingestion, backfill logic, and read-side repositories.
- Backfill gap detection uses market calendars and Hive partitions to minimize redundant IB API calls.
- Readers efficiently combine DuckDB (aggregations/metadata) and PyArrow (scans) for performance.
- Documentation and examples were updated to reflect the Parquet-first model; unit tests cover readers, gap detection, and contract selection.

## Issues & Risks

### Correctness / Bugs

1) Parquet reader type/attribute mismatch
- Issue: Parquet reader base does not expose `destination_type`, but tests expect `"filesystem"`.
- Location: `src/dlt_ibapi/repositories/parquet_reader.py`
- Impact: Test failures, user-facing inconsistency.

2) OptionBarsReader date filter type mismatch
- Issue: PyArrow filter compares `expiry` (date) to a string via `expiry.isoformat()`.
- Location: `src/dlt_ibapi/repositories/option_bars.py`
- Impact: Incorrect/no predicate pushdown and potential empty/incorrect results.

3) business_day_range missing range validation
- Issue: No `start <= end` validation; unit tests expect `ValueError("start_date must be <= end_date")`.
- Location: `src/dlt_ibapi/backfill/gap_detection.py`
- Impact: Unhandled edge case; tests fail; confusing behavior.

4) validate_date_range error message mismatch
- Issue: Error message differs from tests’ expectation (`"start_date must be <= end_date"`).
- Location: `src/dlt_ibapi/backfill/gap_detection.py`
- Impact: Test failure and inconsistent error semantics.

5) CLI stats not Parquet-first
- Issue: `stats` command connects to a DuckDB database file instead of scanning Parquet with DuckDB in-memory.
- Location: `src/dlt_ibapi/cli.py`
- Impact: Conceptual mismatch with the filesystem+Parquet strategy; fragile/defaults to nonexistent .duckdb.

### Consistency / Design

- Dual reader bases: SQL `BaseReader` and Parquet `ParquetReaderBase` coexist. This is acceptable, but can create confusion; consider deprecating or clearly documenting scope.
- Market calendar `include_partial` flag is not implemented; consider implementing or removing to avoid confusion.

### Tests & Docs

- Unit tests are comprehensive and aligned with Parquet. A few expectations require code tweaks (above).
- Integration tests reference legacy IB mocks (`ib_async`) and DB flows; they read like design guides but are inconsistent with current `ib_connector`/Parquet approach.

### Performance & Resilience

- Contract cache writes use `overwrite_or_ignore` for idempotency, which is good. Consider concurrency notes if multi-process writes are expected.
- Readers guard against empty Parquet datasets and use DuckDB views in-memory, which is robust.

## Recommendations (Prioritized)

1) Fix small correctness issues to align with tests
- Add `destination_type = "filesystem"` to `ParquetReaderBase` constructor.
- Use date-typed scalar in OptionBarsReader PyArrow filter for `expiry`.
- Add `start <= end` validation and unify error messages in gap detection.

2) Make CLI stats Parquet-aware
- Use DuckDB in-memory with `parquet_scan('<data_dir>/<dataset>/**.parquet', hive_partitioning=true)` to compute sizes/date ranges.

3) Clarify/implement market calendar partial-day behavior
- Either implement `include_partial` or remove parameter to avoid confusing signatures.

4) Align or quarantine integration tests
- Update mocks to reflect `ib_connector` service layer and filesystem+Parquet, or mark as legacy/experimental.

5) Minor polish
- Add friendly error handling in `create_user_config_template` for read-only FS.
- Add a brief developer note in OptionBarsReader about date vs string filter types.

## Affected Files (non-exhaustive)

- Readers
  - `src/dlt_ibapi/repositories/parquet_reader.py`
  - `src/dlt_ibapi/repositories/option_bars.py`
- Backfill / Gap detection
  - `src/dlt_ibapi/backfill/gap_detection.py`
  - `src/dlt_ibapi/backfill/market_calendar.py`
- CLI
  - `src/dlt_ibapi/cli.py`
- Docs/Tests (optional alignment)
  - `tests/integration/*.py`
  - `docs/*` (small clarifications)

## Validation

- Run unit tests: `uv run pytest tests/unit/`
- For CLI stats changes: create temporary data dir with DLT (as in `tests/unit/test_repositories.py`) and verify counters and date ranges via `parquet_scan()`.
- Verify OptionBarsReader filters by selecting a single contract and checking row counts with/without date filters.

---

Prepared by: Code Review Bot
Date: 2025-10-21
