#!/bin/bash
#
# Daily Calendar Spread Data Collection
#
# Automates complete data collection pipeline for today's earnings.
# Designed to be run daily via cron job.
#
# Usage:
#   ./scripts/collect_daily.sh
#   ./scripts/collect_daily.sh --verbose
#   ./scripts/collect_daily.sh --workers 10
#
# Cron setup (daily at 6 PM EST, after market close):
#   0 18 * * * cd /path/to/dlt-ibapi && ./scripts/collect_daily.sh >> logs/cron.log 2>&1
#

set -euo pipefail

# ============================================================================
# Configuration
# ============================================================================

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
PYTHON_SCRIPT="$SCRIPT_DIR/collect_calendar_spread_data.py"
LOGS_DIR="$PROJECT_DIR/logs"
EARNINGS_DATE=$(date +%Y-%m-%d)
WORKERS=5
VERBOSE=""

# ============================================================================
# Parse arguments
# ============================================================================

while [[ $# -gt 0 ]]; do
    case $1 in
        --workers)
            WORKERS="$2"
            shift 2
            ;;
        --verbose|-v)
            VERBOSE="--verbose"
            shift
            ;;
        --date)
            EARNINGS_DATE="$2"
            shift 2
            ;;
        --help|-h)
            echo "Usage: $0 [OPTIONS]"
            echo ""
            echo "Options:"
            echo "  --workers N      Parallel workers (default: 5)"
            echo "  --verbose, -v    Enable verbose logging"
            echo "  --date YYYY-MM-DD  Earnings date (default: today)"
            echo "  --help, -h       Show this help"
            exit 0
            ;;
        *)
            echo "Unknown option: $1"
            echo "Use --help for usage information"
            exit 1
            ;;
    esac
done

# ============================================================================
# Pre-flight checks
# ============================================================================

echo "========================================================================"
echo "DAILY CALENDAR SPREAD DATA COLLECTION"
echo "========================================================================"
echo "Date:        $(date)"
echo "Earnings:    $EARNINGS_DATE"
echo "Workers:     $WORKERS"
echo "Project Dir: $PROJECT_DIR"
echo "========================================================================"
echo ""

# Check if IB Gateway is running
if ! pgrep -f "ibgateway" > /dev/null 2>&1 && ! pgrep -f "Trader Workstation" > /dev/null 2>&1; then
    echo "ERROR: IB Gateway/TWS is not running"
    echo "Please start IB Gateway before running this script"
    exit 1
fi

echo "✓ IB Gateway/TWS is running"

# Check if Python script exists
if [ ! -f "$PYTHON_SCRIPT" ]; then
    echo "ERROR: Python script not found: $PYTHON_SCRIPT"
    exit 1
fi

echo "✓ Python script found"

# Create logs directory
mkdir -p "$LOGS_DIR"

echo "✓ Logs directory ready: $LOGS_DIR"
echo ""

# ============================================================================
# Run collection
# ============================================================================

cd "$PROJECT_DIR"

# Set log file path
LOG_FILE="$LOGS_DIR/collect_${EARNINGS_DATE}.log"

echo "Starting data collection..."
echo "Logs: $LOG_FILE"
echo ""

# Run Python script with uv
if uv run python "$PYTHON_SCRIPT" \
    "$EARNINGS_DATE" \
    --workers "$WORKERS" \
    --output "$LOGS_DIR" \
    $VERBOSE \
    2>&1 | tee "$LOG_FILE"; then

    echo ""
    echo "========================================================================"
    echo "SUCCESS: Data collection completed"
    echo "========================================================================"
    exit 0
else
    EXIT_CODE=$?
    echo ""
    echo "========================================================================"
    echo "FAILED: Data collection failed with exit code $EXIT_CODE"
    echo "========================================================================"
    echo "Check logs: $LOG_FILE"
    exit $EXIT_CODE
fi
