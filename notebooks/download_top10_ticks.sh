#!/bin/bash
# Auto-generated script to download tick data for TOP 10 IV ratio opportunities
# Generated from notebook: 06c_iv_ratio_ranking_adjusted_times.ipynb

set -e  # Exit on error


# 1. DIS - Earnings 2025-11-13 (PRE_MARKET)
echo 'Downloading DIS entry ticks...'
dlt-ibapi backfill-ticks DIS 20251114 110.0 C --start "2025-11-12 15:00" --end "2025-11-12 16:00"
echo 'Downloading DIS exit ticks...'
dlt-ibapi backfill-ticks DIS 20251114 110.0 C --start "2025-11-13 09:00" --end "2025-11-13 10:00"

# 2. BTM - Earnings 2025-11-13 (PRE_MARKET)
echo 'Downloading BTM entry ticks...'
dlt-ibapi backfill-ticks BTM 20251121 2.0 C --start "2025-11-12 15:00" --end "2025-11-12 16:00"
echo 'Downloading BTM exit ticks...'
dlt-ibapi backfill-ticks BTM 20251121 2.0 C --start "2025-11-13 09:00" --end "2025-11-13 10:00"

# 3. BN - Earnings 2025-11-13 (PRE_MARKET)
echo 'Downloading BN entry ticks...'
dlt-ibapi backfill-ticks BN 20251121 45.0 C --start "2025-11-12 15:00" --end "2025-11-12 16:00"
echo 'Downloading BN exit ticks...'
dlt-ibapi backfill-ticks BN 20251121 45.0 C --start "2025-11-13 09:00" --end "2025-11-13 10:00"

# 4. AMAT - Earnings 2025-11-13 (AFTER_HOURS)
echo 'Downloading AMAT entry ticks...'
dlt-ibapi backfill-ticks AMAT 20251114 225.0 C --start "2025-11-13 15:00" --end "2025-11-13 16:00"
echo 'Downloading AMAT exit ticks...'
dlt-ibapi backfill-ticks AMAT 20251114 225.0 C --start "2025-11-14 09:00" --end "2025-11-14 10:00"

# 5. CEPO - Earnings 2025-11-13 (UNKNOWN)
echo 'Downloading CEPO entry ticks...'
dlt-ibapi backfill-ticks CEPO 20251121 10.0 C --start "2025-11-13 15:00" --end "2025-11-13 16:00"
echo 'Downloading CEPO exit ticks...'
dlt-ibapi backfill-ticks CEPO 20251121 10.0 C --start "2025-11-14 09:00" --end "2025-11-14 10:00"

# 6. BAP - Earnings 2025-11-13 (AFTER_HOURS)
echo 'Downloading BAP entry ticks...'
dlt-ibapi backfill-ticks BAP 20251121 250.0 C --start "2025-11-13 15:00" --end "2025-11-13 16:00"
echo 'Downloading BAP exit ticks...'
dlt-ibapi backfill-ticks BAP 20251121 250.0 C --start "2025-11-14 09:00" --end "2025-11-14 10:00"

# 7. CYBN - Earnings 2025-11-13 (PRE_MARKET)
echo 'Downloading CYBN entry ticks...'
dlt-ibapi backfill-ticks CYBN 20251121 5.0 C --start "2025-11-12 15:00" --end "2025-11-12 16:00"
echo 'Downloading CYBN exit ticks...'
dlt-ibapi backfill-ticks CYBN 20251121 5.0 C --start "2025-11-13 09:00" --end "2025-11-13 10:00"

# 8. BITF - Earnings 2025-11-13 (PRE_MARKET)
echo 'Downloading BITF entry ticks...'
dlt-ibapi backfill-ticks BITF 20251114 3.0 C --start "2025-11-12 15:00" --end "2025-11-12 16:00"
echo 'Downloading BITF exit ticks...'
dlt-ibapi backfill-ticks BITF 20251114 3.0 C --start "2025-11-13 09:00" --end "2025-11-13 10:00"

# 9. BZH - Earnings 2025-11-13 (AFTER_HOURS)
echo 'Downloading BZH entry ticks...'
dlt-ibapi backfill-ticks BZH 20251121 22.0 C --start "2025-11-13 15:00" --end "2025-11-13 16:00"
echo 'Downloading BZH exit ticks...'
dlt-ibapi backfill-ticks BZH 20251121 22.0 C --start "2025-11-14 09:00" --end "2025-11-14 10:00"

# 10. CSIQ - Earnings 2025-11-13 (PRE_MARKET)
echo 'Downloading CSIQ entry ticks...'
dlt-ibapi backfill-ticks CSIQ 20251114 29.0 C --start "2025-11-12 15:00" --end "2025-11-12 16:00"
echo 'Downloading CSIQ exit ticks...'
dlt-ibapi backfill-ticks CSIQ 20251114 29.0 C --start "2025-11-13 09:00" --end "2025-11-13 10:00"
