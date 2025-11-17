#!/bin/bash

# Test tick data download with RECENT HISTORICAL DATA
# Using DIS 108C that expires 2025-12-05
# Data from last Friday (Nov 14, 2025)

echo "Testing tick data download for DIS 108C (Dec 5 expiry)"
echo "Using data from November 14, 2025 (last Friday)"
echo ""

# Download entry window ticks (3:00-3:30pm on Nov 14, 2025)
echo "1. Downloading entry ticks (3:00-3:30pm Nov 14)..."
dlt-ibapi backfill-ticks DIS 20251205 108.0 C \
  --start "2025-11-14 15:00" \
  --end "2025-11-14 15:30"

echo ""
echo "2. Downloading exit ticks (3:30-4:00pm Nov 14)..."
dlt-ibapi backfill-ticks DIS 20251205 108.0 C \
  --start "2025-11-14 15:30" \
  --end "2025-11-14 16:00"

echo ""
echo "✓ Test complete! Check data_delta/option_ticks/ for results"
