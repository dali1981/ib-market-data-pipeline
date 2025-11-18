#!/bin/bash
# Auto-generated script to download tick data for TOP 10 IV ratio opportunities
# Generated from notebook: 06c_iv_ratio_ranking_adjusted_times.ipynb

set -e  # Exit on error


# 1. ARMK - Earnings 2025-11-17 (PRE_MARKET)
echo 'Downloading ARMK entry ticks...'
dlt-ibapi backfill-ticks ARMK 20251121 38.0 C --start "2025-11-16 15:00" --end "2025-11-16 16:00"
echo 'Downloading ARMK exit ticks...'
dlt-ibapi backfill-ticks ARMK 20251121 38.0 C --start "2025-11-17 09:00" --end "2025-11-17 10:00"

# 2. SOHU - Earnings 2025-11-17 (PRE_MARKET)
echo 'Downloading SOHU entry ticks...'
dlt-ibapi backfill-ticks SOHU 20251121 15.0 C --start "2025-11-16 15:00" --end "2025-11-16 16:00"
echo 'Downloading SOHU exit ticks...'
dlt-ibapi backfill-ticks SOHU 20251121 15.0 C --start "2025-11-17 09:00" --end "2025-11-17 10:00"

# 3. LFMD - Earnings 2025-11-17 (AFTER_HOURS)
echo 'Downloading LFMD entry ticks...'
dlt-ibapi backfill-ticks LFMD 20251121 5.0 C --start "2025-11-17 15:00" --end "2025-11-17 16:00"
echo 'Downloading LFMD exit ticks...'
dlt-ibapi backfill-ticks LFMD 20251121 5.0 C --start "2025-11-18 09:00" --end "2025-11-18 10:00"

# 4. YSG - Earnings 2025-11-17 (PRE_MARKET)
echo 'Downloading YSG entry ticks...'
dlt-ibapi backfill-ticks YSG 20251121 7.5 C --start "2025-11-16 15:00" --end "2025-11-16 16:00"
echo 'Downloading YSG exit ticks...'
dlt-ibapi backfill-ticks YSG 20251121 7.5 C --start "2025-11-17 09:00" --end "2025-11-17 10:00"

# 5. JJSF - Earnings 2025-11-17 (PRE_MARKET)
echo 'Downloading JJSF entry ticks...'
dlt-ibapi backfill-ticks JJSF 20251121 85.0 C --start "2025-11-16 15:00" --end "2025-11-16 16:00"
echo 'Downloading JJSF exit ticks...'
dlt-ibapi backfill-ticks JJSF 20251121 85.0 C --start "2025-11-17 09:00" --end "2025-11-17 10:00"

# 6. ACM - Earnings 2025-11-17 (AFTER_HOURS)
echo 'Downloading ACM entry ticks...'
dlt-ibapi backfill-ticks ACM 20251121 135.0 C --start "2025-11-17 15:00" --end "2025-11-17 16:00"
echo 'Downloading ACM exit ticks...'
dlt-ibapi backfill-ticks ACM 20251121 135.0 C --start "2025-11-18 09:00" --end "2025-11-18 10:00"

# 7. NIU - Earnings 2025-11-17 (PRE_MARKET)
echo 'Downloading NIU entry ticks...'
dlt-ibapi backfill-ticks NIU 20251121 5.0 C --start "2025-11-16 15:00" --end "2025-11-16 16:00"
echo 'Downloading NIU exit ticks...'
dlt-ibapi backfill-ticks NIU 20251121 5.0 C --start "2025-11-17 09:00" --end "2025-11-17 10:00"

# 8. NKLR - Earnings 2025-11-17 (PRE_MARKET)
echo 'Downloading NKLR entry ticks...'
dlt-ibapi backfill-ticks NKLR 20251121 5.0 C --start "2025-11-16 15:00" --end "2025-11-16 16:00"
echo 'Downloading NKLR exit ticks...'
dlt-ibapi backfill-ticks NKLR 20251121 5.0 C --start "2025-11-17 09:00" --end "2025-11-17 10:00"

# 9. HP - Earnings 2025-11-17 (AFTER_HOURS)
echo 'Downloading HP entry ticks...'
dlt-ibapi backfill-ticks HP 20251121 27.5 C --start "2025-11-17 15:00" --end "2025-11-17 16:00"
echo 'Downloading HP exit ticks...'
dlt-ibapi backfill-ticks HP 20251121 27.5 C --start "2025-11-18 09:00" --end "2025-11-18 10:00"

# 10. IMTX - Earnings 2025-11-17 (UNKNOWN)
echo 'Downloading IMTX entry ticks...'
dlt-ibapi backfill-ticks IMTX 20251121 10.0 C --start "2025-11-17 15:00" --end "2025-11-17 16:00"
echo 'Downloading IMTX exit ticks...'
dlt-ibapi backfill-ticks IMTX 20251121 10.0 C --start "2025-11-18 09:00" --end "2025-11-18 10:00"
