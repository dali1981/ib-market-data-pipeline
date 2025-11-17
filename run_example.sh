dlt-ibapi load-earnings ./earnings_raw/earnings_2025-11-17.json
dlt-ibapi list-earnings --days-ahead 30

dlt-ibapi resolve-contracts --earnings-date 2025-11-17
dlt-ibapi snapshot --earnings-date 2025-11-17   --min-dte 0   --max-dte 90

## List all snapshots for earnings symbols on 2025-11-17
#  dlt-ibapi snapshot list --earnings-date 2025-11-17

# List snapshots on a specific date
dlt-ibapi snapshot list --date 2025-11-17

#  # List snapshots for specific symbols
#  dlt-ibapi snapshot list --symbols "AAPL,MSFT,GOOGL"
#  dlt-ibapi snapshot list --symbols ACM --symbols ARBE

#  All command variations tested successfully:
  #
  #  # List all equity bars with earnings filter
  #  dlt-ibapi equity list --earnings-date 2025-11-17
  #  # ✅ Shows 29 symbols
  #
  #  # Filter specific symbols (comma-separated)
  #  dlt-ibapi equity list --symbols ACM,ARBE,HP
  #  # ✅ Shows 3 symbols
  #
  #  # Filter specific symbols (multiple flags)
  #  dlt-ibapi equity list --symbols ACM --symbols ARBE
  #  # ✅ Shows 2 symbols

dlt-ibapi resolve-contracts --sec-type OPT --snapshot-date 2025-11-17

dlt-ibapi backfill-options --earnings-date 2025-11-17 --k-expirations 2 --k-strikes 2 --bar-size "5 mins" --start 2025-11-10 --end 2025-11-17 --client-id 2


#   # Show all candidates
  #  dlt-ibapi strategy select --earnings-date 2025-11-17
  #
  #  # Filter to top 5
  #  dlt-ibapi strategy select --earnings-date 2025-11-17 --top-n 5
  #
  #  # Filter by IV ratio threshold
  #  dlt-ibapi strategy select --earnings-date 2025-11-17 --min-iv-ratio 1.5
  #
  #  # Combine filters
  #  dlt-ibapi strategy select --earnings-date 2025-11-17 --min-iv-ratio 1.5 --top-n 10
  #
  #  The rank column lets you easily identify the best candidates even when viewing all results!


