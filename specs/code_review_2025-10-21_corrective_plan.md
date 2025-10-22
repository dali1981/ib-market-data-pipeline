# Corrective Plan — dlt-ibapi (2025-10-21)

## Goals

- Align implementation with Parquet-first architecture and unit test expectations.
- Remove subtle correctness pitfalls (date filter types, validation, error messages).
- Improve CLI coherence with filesystem-based storage.

## Scope

Includes minor code adjustments in readers, gap detection utilities, and CLI; optional cleanups in market calendar and integration tests.

## Tasks (Prioritized)

1) Expose destination type in Parquet readers (Quick Win)
- File: `src/dlt_ibapi/repositories/parquet_reader.py`
- Change: In `__init__`, set `self.destination_type = "filesystem"`.
- Acceptance:
  - `tests/unit/test_repositories.py` passes assertion for destination type.

2) Fix OptionBarsReader PyArrow date filter (Quick Win)
- File: `src/dlt_ibapi/repositories/option_bars.py`
- Change:
  - Import `pyarrow as pa` (if not already).
  - Build filter: `(pc.field("expiry") == pa.scalar(expiry))` where `expiry` is `datetime.date`. Keep `bar_size`, `strike`, `right`, `underlying` filters as-is, ensuring proper types.
- Acceptance:
  - Querying a specific contract by `expiry` returns expected rows.
  - Large scans still work; no type warnings in filter evaluation.

3) Add range validation and unify error messages in gap detection (Quick Win)
- File: `src/dlt_ibapi/backfill/gap_detection.py`
- Changes:
  - At start of `business_day_range(start, end)`, if `start > end`: raise `ValueError("start_date must be <= end_date")`.
  - In `validate_date_range(start, end)`, raise the same message string.
- Acceptance:
  - `tests/unit/test_gap_detection.py` range-related tests pass.

4) Update CLI stats to scan Parquet (High Priority)
- File: `src/dlt_ibapi/cli.py`
- Changes:
  - Use `duckdb.connect(":memory:")` and `parquet_scan('{data_dir}/{dataset}/**/*.parquet', hive_partitioning=true)`.
  - Consider renaming `--database/--db` to `--data-dir` (keep `--database` as alias for backward compatibility).
  - For each table (subdir), compute row counts and date ranges via SQL on `parquet_scan`.
- Acceptance:
  - Running `dlt-ibapi stats ./data --dataset stocks` prints row counts and date ranges using Parquet files.
  - Works without any `.duckdb` file present.

5) Market calendar partial-day parameter clarity (Medium)
- File: `src/dlt_ibapi/backfill/market_calendar.py`
- Options:
  - Implement `include_partial=False` filtering by checking early close days and excluding them when `False`.
  - Or remove parameter and references if not needed (breaking change; announce in docs).
- Acceptance:
  - If implemented, add unit test to verify exclusion of early close days when `include_partial=False`.

6) Integration tests alignment (Optional)
- Files: `tests/integration/test_snapshot_resource.py`, `tests/integration/test_backfill_resource.py`
- Changes:
  - Replace `ib_async` mocks with `ib_connector` service mocks or adapters.
  - Ensure pipeline writes Parquet and verifications use `parquet_scan()`.
- Acceptance:
  - Integration tests run (if enabled) and assert Parquet-based outputs.

7) Minor polish (Optional)
- File: `src/dlt_ibapi/config_loader.py`
- Change: In `create_user_config_template`, wrap write in try/except and show friendly message if filesystem is read-only.
- Acceptance:
  - CLI `init` surfaces clear errors in restricted environments.

## Estimated Effort

- Tasks 1–3: ~1–2 hours total (including test runs).
- Task 4: ~1–2 hours.
- Task 5: ~1–3 hours (depending on approach).
- Task 6: ~3–5 hours (mocking and alignment) — optional.
- Task 7: ~0.5 hour — optional.

## Risk & Mitigations

- Changing CLI flags: keep aliases to avoid breaking scripts.
- Date/type filters: ensure correct Arrow scalar types to maintain predicate pushdown and correctness.
- Calendar behavior: document behavior clearly if parameter is retained.

## Test Plan

- Run unit tests: `uv run pytest tests/unit/`.
- Local manual checks:
  - Create sample Parquet via DLT as in `tests/unit/test_repositories.py` and validate `stats` output.
  - OptionBarsReader queries with specific `(underlying, expiry, strike, right, bar_size)` and with date ranges.

## Rollout

- Implement tasks 1–4 in a single PR; include small doc updates.
- Follow up with tasks 5–7 in subsequent PR(s) if desired.

Prepared by: Code Review Bot
Date: 2025-10-21
