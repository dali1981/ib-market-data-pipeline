 Key Features:

  EarningsTimingCalculator Class

  Encapsulates the common logic for calculating entry/exit windows based on earnings timing:
  - PRE_MARKET: Entry previous day 3-4pm, exit same day 9-10am
  - AFTER_HOURS: Entry same day 3-4pm, exit next day 9-10am
  - UNKNOWN: Treated as AFTER_HOURS (conservative)

  Two Usage Modes

  Mode 1: Explicit Windows (backward compatible)
  dlt-ibapi backfill-ticks AAPL 20251121 150.0 C \
    --start "2025-11-16 15:00" \
    --end "2025-11-16 16:00"

  Mode 2: Earnings Mode (auto-calculates windows)
  # Entry window (3-4pm before earnings)
  dlt-ibapi backfill-ticks ARMK 20251121 38.0 C \
    --earnings-date 2025-11-17 \
    --earnings-time PRE_MARKET \
    --window entry

  # Exit window (9-10am after earnings)
  dlt-ibapi backfill-ticks ARMK 20251121 38.0 C \
    --earnings-date 2025-11-17 \
    --earnings-time PRE_MARKET \
    --window exit

  Real Example from Notebook

  Based on the TOP 10 table, here's how to download ticks for ARMK (rank #1):

  # Entry ticks (PRE_MARKET earnings → previous day 3-4pm)
  dlt-ibapi backfill-ticks ARMK 20251121 38.0 C \
    --earnings-date 2025-11-17 \
    --earnings-time PRE_MARKET \
    --window entry \
    --client-id 2

  # Exit ticks (PRE_MARKET earnings → same day 9-10am)
  dlt-ibapi backfill-ticks ARMK 20251121 38.0 C \
    --earnings-date 2025-11-17 \
    --earnings-time PRE_MARKET \
    --window exit \
    --client-id 2


  # ARMK (PRE_MARKET earnings on 2025-11-17)
  dlt-ibapi backfill-ticks ARMK 20251121 38.0 C --earnings-date 2025-11-17 --earnings-time PRE_MARKET --window entry
  dlt-ibapi backfill-ticks ARMK 20251121 38.0 C --earnings-date 2025-11-17 --earnings-time PRE_MARKET --window exit
  dlt-ibapi backfill-ticks ARMK 20251219 38.0 C --earnings-date 2025-11-17 --earnings-time PRE_MARKET --window entry
  dlt-ibapi backfill-ticks ARMK 20251219 38.0 C --earnings-date 2025-11-17 --earnings-time PRE_MARKET --window exit