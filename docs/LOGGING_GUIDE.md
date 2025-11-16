# dlt-ibapi Logging Guide

**Complete guide to logging configuration and output**

Version: 1.0
Last Updated: 2025-11-16

---

## Table of Contents

1. [Overview](#overview)
2. [Quick Start](#quick-start)
3. [Log Levels](#log-levels)
4. [Output Formats](#output-formats)
5. [File Logging](#file-logging)
6. [Structured Logging](#structured-logging)
7. [Command-Specific Examples](#command-specific-examples)
8. [Advanced Usage](#advanced-usage)
9. [Troubleshooting](#troubleshooting)

---

## Overview

dlt-ibapi uses [structlog](https://www.structlog.org/) for structured, context-aware logging with support for:

- **Console output**: Human-readable colored logs (default)
- **File logging**: Automatic rotation (10MB max, 5 backups)
- **JSON logs**: Machine-parseable structured logs
- **Multiple levels**: DEBUG, INFO, WARNING, ERROR
- **Context binding**: Automatic metadata (symbol, operation, etc.)

### Default Behavior

By default (no logging flags):
- **Console output**: INFO level and above
- **Colored logs**: When outputting to terminal
- **Third-party loggers**: Suppressed (urllib3, requests, ibapi, dlt)

---

## Quick Start

### Basic Usage (Console Logging)

```bash
# Default: INFO level to console
dlt-ibapi backfill-options AAPL 150.0 --mode atm
```

### Enable Debug Logging

```bash
# See all DEBUG messages
dlt-ibapi backfill-options AAPL 150.0 --verbose
# or
dlt-ibapi backfill-options AAPL 150.0 -v
```

### Quiet Mode (Warnings/Errors Only)

```bash
# Only show WARNING and ERROR
dlt-ibapi backfill-options AAPL 150.0 --quiet
# or
dlt-ibapi backfill-options AAPL 150.0 -q
```

### Log to File

```bash
# Write logs to file with automatic rotation
dlt-ibapi backfill-options AAPL 150.0 --log-file backfill.log
```

### JSON Output (for Production/Monitoring)

```bash
# Structured JSON logs
dlt-ibapi backfill-options AAPL 150.0 --json-logs
```

---

## Log Levels

### Hierarchy

| Level | Use Case | Enabled By |
|-------|----------|------------|
| **DEBUG** | Detailed diagnostic info (function calls, parameters) | `--verbose` or `-v` |
| **INFO** | Normal operation info (progress, status) | Default |
| **WARNING** | Important issues that don't stop execution | Always shown |
| **ERROR** | Errors that cause operation failure | Always shown |

### Examples

**INFO** (default):
```
2025-11-16 21:30:00 | INFO     | Starting backfill for AAPL
2025-11-16 21:30:05 | INFO     | Fetched 100 bars
2025-11-16 21:30:10 | INFO     | Backfill completed successfully
```

**DEBUG** (`--verbose`):
```
2025-11-16 21:30:00 | DEBUG    | loaded_connection_config: host=127.0.0.1, port=4002
2025-11-16 21:30:01 | DEBUG    | extracting_spot_price: symbol=AAPL
2025-11-16 21:30:02 | DEBUG    | spot_price_selected: symbol=AAPL, earnings_time=PRE_MARKET, spot_price_date=2025-11-12, spot_price=180.50
2025-11-16 21:30:05 | INFO     | Fetched 100 bars
```

**QUIET** (`--quiet`):
```
2025-11-16 21:30:15 | WARNING  | No equity data for XYZ - skipping
2025-11-16 21:30:20 | ERROR    | Connection failed: [Errno 61] Connection refused
```

---

## Output Formats

### Console Format (Default)

Human-readable, colored output for terminal viewing:

```bash
dlt-ibapi backfill-options AAPL 150.0 --mode atm
```

**Example output**:
```
2025-11-16T21:30:00.123Z [info     ] starting_options_backfill   underlying=AAPL spot_price=150.0
2025-11-16T21:30:05.456Z [info     ] loaded_connection_config
2025-11-16T21:30:10.789Z [info     ] options_backfill_complete   underlying=AAPL duration=10.67
```

**Features**:
- Colored output (when terminal supports it)
- ISO 8601 timestamps (UTC)
- Key-value pairs for context
- Automatic line wrapping

### JSON Format

Machine-parseable structured logs for production/monitoring systems:

```bash
dlt-ibapi backfill-options AAPL 150.0 --json-logs
```

**Example output**:
```json
{"event": "starting_options_backfill", "underlying": "AAPL", "spot_price": 150.0, "level": "info", "timestamp": "2025-11-16T21:30:00.123456Z"}
{"event": "loaded_connection_config", "level": "info", "timestamp": "2025-11-16T21:30:05.456789Z"}
{"event": "options_backfill_complete", "underlying": "AAPL", "duration": 10.67, "level": "info", "timestamp": "2025-11-16T21:30:10.789012Z"}
```

**Features**:
- One JSON object per line (newline-delimited)
- Easy to parse with jq, grep, or log aggregators
- All context fields as JSON keys
- Precise timestamps

---

## File Logging

### Enable File Logging

```bash
dlt-ibapi backfill-options AAPL 150.0 --log-file logs/backfill.log
```

### Rotation Behavior

**Automatic rotation** when file reaches 10MB:
```
logs/
├── backfill.log          # Current log (0-10MB)
├── backfill.log.1        # Previous rotation
├── backfill.log.2        # 2nd previous
├── backfill.log.3        # 3rd previous
├── backfill.log.4        # 4th previous
└── backfill.log.5        # 5th previous (oldest kept)
```

**Configuration**:
- **Max file size**: 10 MB
- **Backup count**: 5 files
- **Total disk space**: ~50-60 MB max

### File Format

By default, file logs use standard format (not colored):

```
2025-11-16 21:30:00 | INFO     | dlt_ibapi.cli.backfill | starting_options_backfill underlying=AAPL spot_price=150.0
2025-11-16 21:30:05 | INFO     | dlt_ibapi.config_loader | loaded_connection_config
2025-11-16 21:30:10 | INFO     | dlt_ibapi.cli.backfill | options_backfill_complete underlying=AAPL duration=10.67
```

### JSON File Logs

Combine `--log-file` and `--json-logs` for structured file logs:

```bash
dlt-ibapi backfill-options AAPL 150.0 --log-file logs/backfill.json --json-logs
```

**File content** (`logs/backfill.json`):
```json
{"event": "starting_options_backfill", "underlying": "AAPL", "spot_price": 150.0, "level": "info", "timestamp": "2025-11-16T21:30:00.123456Z", "logger": "dlt_ibapi.cli.backfill"}
{"event": "loaded_connection_config", "level": "info", "timestamp": "2025-11-16T21:30:05.456789Z", "logger": "dlt_ibapi.config_loader"}
```

**Benefits**:
- Easy to query with jq: `jq 'select(.level == "error")' logs/backfill.json`
- Import into log aggregators (Elasticsearch, Splunk, Datadog)
- Machine-parseable for analysis

---

## Structured Logging

### Context Binding

Logs automatically include operation context:

**Example** (earnings batch backfill):
```
2025-11-16T21:30:00Z [info] processing_symbol_earnings symbol=AAPL
2025-11-16T21:30:01Z [debug] extracting_spot_price symbol=AAPL earnings_time=PRE_MARKET spot_price_date=2025-11-12
2025-11-16T21:30:02Z [info] spot_price_selected symbol=AAPL earnings_time=PRE_MARKET spot_price_date=2025-11-12 spot_price=180.50
2025-11-16T21:30:05Z [debug] loading_expirations symbol=AAPL
2025-11-16T21:30:10Z [info] symbol_backfill_complete symbol=AAPL contracts=15 bars=1500
```

**Key-value pairs**:
- `symbol`: Stock ticker
- `earnings_time`: "PRE_MARKET", "AFTER_HOURS", "UNKNOWN"
- `spot_price_date`: Date used for spot price
- `spot_price`: Extracted spot price
- `contracts`: Number of option contracts processed
- `bars`: Number of bars fetched

### Event Names

Structured event names follow snake_case convention:

| Event | Description | Context |
|-------|-------------|---------|
| `starting_options_backfill` | Backfill operation started | `underlying`, `spot_price`, `start_date`, `end_date` |
| `loaded_earnings_symbols` | Symbols loaded from earnings calendar | `count` |
| `applied_symbols_filter` | Symbols filtered | `original_count`, `filtered_count`, `filter` |
| `spot_price_selected` | Spot price extracted | `symbol`, `earnings_time`, `spot_price_date`, `spot_price` |
| `processing_symbol_earnings` | Processing individual symbol | `symbol` |
| `symbol_backfill_complete` | Symbol processing done | `symbol`, `contracts`, `bars` |
| `options_backfill_complete` | Full backfill done | `duration` |
| `no_equity_data` | Missing equity data | `symbol`, `spot_price_date`, `earnings_time` |
| `missing_filtered_symbols` | Requested symbols not found | `symbols` |

---

## Command-Specific Examples

### Option Backfill (Single Symbol)

```bash
# Debug logs + file output
dlt-ibapi backfill-options AAPL 150.0 \
  --mode atm --k-strikes 3 \
  --verbose \
  --log-file logs/aapl_backfill.log
```

**Log events**:
```
starting_options_backfill
loaded_connection_config
creating_backfill_config
fetching_option_bars
options_backfill_complete
```

### Option Backfill (Earnings Batch)

```bash
# JSON logs for monitoring + file rotation
dlt-ibapi backfill-options --earnings-date 2025-11-13 \
  --symbols AAPL,MSFT,GOOGL \
  --k-expirations 6 --k-strikes 5 \
  --json-logs \
  --log-file logs/earnings_batch.json
```

**Log events**:
```
starting_options_backfill_earnings
loading_symbols_from_earnings
loaded_earnings_symbols (count=3)
applied_symbols_filter (original_count=50, filtered_count=3)
processing_symbol_earnings (symbol=AAPL)
extracting_spot_price (symbol=AAPL, earnings_time=PRE_MARKET)
spot_price_selected (symbol=AAPL, spot_price_date=2025-11-12, spot_price=180.50)
loading_expirations (symbol=AAPL)
symbol_backfill_complete (symbol=AAPL, contracts=15, bars=1500)
processing_symbol_earnings (symbol=MSFT)
...
options_backfill_complete (duration=120.5)
```

### Equity Backfill

```bash
# Quiet mode + file logging (only warnings/errors to console)
dlt-ibapi backfill-equity AAPL MSFT GOOGL \
  --bar-size "1 day" \
  --quiet \
  --log-file logs/equity_backfill.log
```

**Console output** (only warnings/errors):
```
2025-11-16 21:30:15 | WARNING  | No data for MSFT before 2020-01-01
```

**File output** (all levels):
```
2025-11-16 21:30:00 | INFO     | starting_equity_backfill symbols=['AAPL', 'MSFT', 'GOOGL']
2025-11-16 21:30:05 | INFO     | processing_symbol symbol=AAPL
2025-11-16 21:30:10 | INFO     | backfill_complete symbol=AAPL bars=1000
2025-11-16 21:30:15 | WARNING  | No data for MSFT before 2020-01-01
2025-11-16 21:30:20 | INFO     | equity_backfill_complete symbols_processed=3 total_bars=2500
```

### Snapshot

```bash
# Verbose debug + JSON logs
dlt-ibapi snapshot --earnings-date 2025-11-13 \
  --min-dte 7 --max-dte 60 \
  --verbose \
  --json-logs
```

---

## Advanced Usage

### Combining Options

All logging options can be combined:

```bash
# Verbose + JSON + File
dlt-ibapi backfill-options --earnings-date 2025-11-13 \
  --verbose \
  --json-logs \
  --log-file logs/debug.json
```

**Result**:
- Console: Colored JSON logs (DEBUG level)
- File: JSON logs with rotation (`logs/debug.json`)

### Log File Organization

**Recommended structure**:
```
logs/
├── backfill/
│   ├── options_2025-11-16.log
│   ├── options_2025-11-16.log.1
│   ├── equity_2025-11-16.log
│   └── equity_2025-11-16.log.1
├── snapshots/
│   ├── earnings_2025-11-13.log
│   └── earnings_2025-11-13.log.1
└── errors/
    └── backfill_errors_2025-11-16.log
```

**Example commands**:
```bash
# Separate log files per operation type
dlt-ibapi backfill-options --earnings-date 2025-11-13 \
  --log-file logs/backfill/options_$(date +%Y-%m-%d).log

dlt-ibapi backfill-equity --earnings-date 2025-11-13 \
  --log-file logs/backfill/equity_$(date +%Y-%m-%d).log

dlt-ibapi snapshot --earnings-date 2025-11-13 \
  --log-file logs/snapshots/earnings_2025-11-13.log
```

### Parsing JSON Logs with jq

**Filter by level**:
```bash
# Show only errors
jq 'select(.level == "error")' logs/backfill.json

# Show warnings and errors
jq 'select(.level == "warning" or .level == "error")' logs/backfill.json
```

**Filter by event**:
```bash
# Show all spot price selections
jq 'select(.event == "spot_price_selected")' logs/backfill.json

# Show spot price selections with specific earnings_time
jq 'select(.event == "spot_price_selected" and .earnings_time == "PRE_MARKET")' logs/backfill.json
```

**Extract specific fields**:
```bash
# Get all symbols processed
jq -r 'select(.event == "processing_symbol_earnings") | .symbol' logs/backfill.json

# Get spot prices for each symbol
jq -r 'select(.event == "spot_price_selected") | "\(.symbol): \(.spot_price)"' logs/backfill.json
```

**Calculate statistics**:
```bash
# Count events by type
jq -r '.event' logs/backfill.json | sort | uniq -c

# Count by log level
jq -r '.level' logs/backfill.json | sort | uniq -c

# Average duration
jq 'select(.event == "options_backfill_complete") | .duration' logs/backfill.json | \
  awk '{sum+=$1; count++} END {print sum/count}'
```

### Redirecting Logs

**Separate stdout/stderr**:
```bash
# Progress to stdout, logs to stderr
dlt-ibapi backfill-options AAPL 150.0 > progress.txt 2> errors.log

# Only errors to file
dlt-ibapi backfill-options AAPL 150.0 --quiet 2> errors.log
```

**Tee for both console and file**:
```bash
# See on console AND save to file
dlt-ibapi backfill-options AAPL 150.0 --json-logs 2>&1 | tee logs/backfill.json
```

---

## Troubleshooting

### No Logs Appearing

**Check log level**:
```bash
# If using --quiet, only warnings/errors shown
dlt-ibapi backfill-options AAPL 150.0 --quiet

# Use --verbose to see everything
dlt-ibapi backfill-options AAPL 150.0 --verbose
```

### Log File Not Created

**Check path permissions**:
```bash
# Create log directory first
mkdir -p logs/
dlt-ibapi backfill-options AAPL 150.0 --log-file logs/backfill.log

# Use absolute path
dlt-ibapi backfill-options AAPL 150.0 --log-file /tmp/backfill.log
```

### Too Many Logs

**Use quiet mode**:
```bash
# Only show important messages
dlt-ibapi backfill-options AAPL 150.0 --quiet
```

**Filter specific loggers**:
```python
# In Python code (advanced)
import logging
logging.getLogger("dlt").setLevel(logging.ERROR)
logging.getLogger("ibapi").setLevel(logging.ERROR)
```

### Log Rotation Not Working

**Check disk space**:
```bash
df -h logs/
```

**Verify max size setting** (code in `utils/structlog_config.py`):
```python
maxBytes=10 * 1024 * 1024,  # 10 MB
backupCount=5,
```

### JSON Parsing Errors

**Ensure newline-delimited JSON**:
```bash
# Each line is valid JSON
jq '.' logs/backfill.json

# If file is single JSON array, use jq differently
jq '.[]' logs/backfill.json
```

---

## Best Practices

1. **Use `--verbose` for development/debugging**
   ```bash
   dlt-ibapi backfill-options AAPL 150.0 --verbose
   ```

2. **Use `--quiet` for production/cron jobs**
   ```bash
   dlt-ibapi backfill-options AAPL 150.0 --quiet --log-file logs/backfill.log
   ```

3. **Use `--json-logs` for monitoring systems**
   ```bash
   dlt-ibapi backfill-options AAPL 150.0 --json-logs --log-file logs/backfill.json
   ```

4. **Always use `--log-file` for long-running operations**
   ```bash
   dlt-ibapi backfill-options --earnings-date 2025-11-13 --log-file logs/earnings_batch.log
   ```

5. **Organize logs by date and operation**
   ```bash
   --log-file logs/backfill/options_$(date +%Y-%m-%d).log
   ```

6. **Monitor log files for errors**
   ```bash
   # Tail logs in real-time
   tail -f logs/backfill.log

   # Watch for errors
   tail -f logs/backfill.log | grep ERROR
   ```

---

## Summary

| Option | Shorthand | Purpose | Default |
|--------|-----------|---------|---------|
| `--verbose` | `-v` | DEBUG level logging | OFF (INFO level) |
| `--quiet` | `-q` | WARNING/ERROR only | OFF (INFO level) |
| `--json-logs` | - | JSON output format | OFF (console format) |
| `--log-file` | - | Write to file with rotation | OFF (console only) |

**Examples**:
```bash
# Development
dlt-ibapi backfill-options AAPL 150.0 --verbose

# Production
dlt-ibapi backfill-options AAPL 150.0 --quiet --log-file logs/backfill.log

# Monitoring
dlt-ibapi backfill-options AAPL 150.0 --json-logs --log-file logs/backfill.json

# Debug to file
dlt-ibapi backfill-options AAPL 150.0 --verbose --log-file logs/debug.log
```
