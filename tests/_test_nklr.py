import duckdb
result = duckdb.execute('''
  SELECT underlying, expiry, strike, COUNT(*) as ticks
  FROM parquet_scan('data_delta/ticks/option_ticks_bid_ask/*.parquet', hive_partitioning=false)
  WHERE underlying = 'NKLR'
  GROUP BY underlying, expiry, strike
''').fetchdf()

print(result)