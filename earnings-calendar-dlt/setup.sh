#!/bin/bash

# Setup script for earnings-calendar-dlt

set -e

echo "🚀 Setting up earnings-calendar-dlt..."
echo ""

# Check if uv is installed
if ! command -v uv &> /dev/null; then
    echo "❌ uv is not installed"
    echo "Please install uv: https://github.com/astral-sh/uv"
    exit 1
fi

echo "✅ uv is installed"
echo ""

# Install dependencies
echo "📦 Installing dependencies..."
uv sync
echo "✅ Dependencies installed"
echo ""

# Install package in editable mode
echo "📦 Installing package in editable mode..."
uv pip install -e .
echo "✅ Package installed"
echo ""

# Install Playwright
echo "🎭 Installing Playwright browsers..."
uv run playwright install chromium
echo "✅ Playwright installed"
echo ""

# Create data directory
echo "📁 Creating data directory..."
mkdir -p ./data/nasdaq_earnings/earnings_calendar
echo "✅ Data directory created"
echo ""

# Create config directory
echo "📝 Creating config directory..."
mkdir -p .earnings-calendar
echo "✅ Config directory created"
echo ""

# Create example config file
if [ ! -f ".earnings-calendar/config.yaml" ]; then
    echo "📄 Creating example config file..."
    cat > .earnings-calendar/config.yaml << EOF
# Earnings Calendar Configuration

scraper:
  days_ahead: 30
  use_playwright_fallback: true
  timeout: 30

dlt:
  destination: filesystem
  dataset_name: nasdaq_earnings
  bucket_url: file://./data
  write_disposition: replace
EOF
    echo "✅ Config file created at .earnings-calendar/config.yaml"
else
    echo "ℹ️  Config file already exists"
fi
echo ""

# Run tests
echo "🧪 Running tests..."
if uv run pytest tests/ -v; then
    echo "✅ Tests passed"
else
    echo "⚠️  Some tests failed (this is ok for initial setup)"
fi
echo ""

echo "✨ Setup complete!"
echo ""
echo "Next steps:"
echo "  1. Run the scraper:    uv run python examples/standalone_scraper.py"
echo "  2. Run the pipeline:   uv run python examples/run_pipeline.py"
echo "  3. Query the data:     uv run python examples/query_data.py"
echo "  4. Start Dagster:      uv run dagster dev -m dagster_earnings"
echo ""
echo "For more information, see README.md"
