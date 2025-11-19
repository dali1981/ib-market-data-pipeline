#!/usr/bin/env python3
"""
Check for duplicate records in ARBE option bars data.
Specifically looking for the 2025-12-19 3.0 Call contract.
"""

import duckdb
import pandas as pd
from pathlib import Path

# Connect to DuckDB
con = duckdb.connect(":memory:")

# Path to ARBE option data
data_path = "/Users/mohamedali/trading_project/dlt-ibapi/data_delta/options/option_bars_backfill/underlying=ARBE/*.parquet"

print("=" * 80)
print("ARBE Option Bars Duplicate Analysis")
print("=" * 80)

# Load all ARBE option data
print("\n1. Loading ARBE option data...")
query = f"""
SELECT *
FROM read_parquet('{data_path}', hive_partitioning=true)
"""
df_all = con.execute(query).fetchdf()
print(f"   Total rows for ARBE: {len(df_all)}")

# Filter for the specific contract: 2025-12-19 3.0 Call
print("\n2. Filtering for 2025-12-19 3.0 Call contract...")
# Convert expiry to date for comparison
df_all['expiry_date'] = pd.to_datetime(df_all['expiry']).dt.date
target_date = pd.to_datetime('2025-12-19').date()

df_contract = df_all[
    (df_all['expiry_date'] == target_date) &
    (df_all['strike'] == 3.0) &
    (df_all['right'] == 'C')
]
print(f"   Rows for ARBE 2025-12-19 3.0 Call: {len(df_contract)}")

if len(df_contract) == 0:
    print("\n   No data found for this contract. Showing available contracts:")
    contracts = df_all[['underlying', 'expiry_date', 'strike', 'right']].drop_duplicates()
    print(contracts.to_string())
    exit(0)

# Show contract details
print("\n3. Contract Details:")
if 'contract_id' in df_contract.columns:
    print(f"   Contract ID: {df_contract['contract_id'].iloc[0]}")
if 'local_symbol' in df_contract.columns:
    print(f"   Local Symbol: {df_contract['local_symbol'].iloc[0]}")

# Define primary key columns (note: contract_id may not exist, so use contract identifiers)
# According to the data, we have: symbol, expiry, strike, right to identify contract
pk_columns = ['symbol', 'expiry', 'strike', 'right', 'time', 'bar_size']

# Check which columns exist
available_pk_cols = [col for col in pk_columns if col in df_contract.columns]
print(f"\n4. Primary Key Columns (available): {available_pk_cols}")

# Check for duplicates based on primary key
print("\n5. Duplicate Analysis:")
print(f"   Total rows: {len(df_contract)}")
print(f"   Unique timestamps: {df_contract['time'].nunique()}")

# Group by primary key to find duplicates
if available_pk_cols:
    duplicate_mask = df_contract.duplicated(subset=available_pk_cols, keep=False)
    num_duplicates = duplicate_mask.sum()

    print(f"   Duplicate rows (by PK): {num_duplicates}")

    if num_duplicates > 0:
        print("\n6. DUPLICATES FOUND!")
        print("=" * 80)

        # Get duplicate rows
        duplicates_df = df_contract[duplicate_mask].sort_values(by=available_pk_cols)

        # Group by primary key to show which timestamps have duplicates
        dup_groups = duplicates_df.groupby(available_pk_cols).size().reset_index(name='count')
        dup_groups = dup_groups[dup_groups['count'] > 1].sort_values('count', ascending=False)

        print(f"\n   Timestamps with duplicates: {len(dup_groups)}")
        print("\n   Top 10 timestamps with most duplicates:")
        print(dup_groups.head(10).to_string())

        print("\n7. Sample of Duplicate Rows (first 10):")
        print("=" * 80)
        cols_to_show = ['time', 'open', 'high', 'low', 'close', 'volume', 'bar_size']
        if 'contract_id' in duplicates_df.columns:
            cols_to_show = ['contract_id'] + cols_to_show
        available_cols = [col for col in cols_to_show if col in duplicates_df.columns]

        print(duplicates_df[available_cols].head(10).to_string())

        # Show statistics about duplicate values
        print("\n8. Duplicate Value Analysis:")
        print("   Are duplicate rows identical?")
        value_cols = ['open', 'high', 'low', 'close', 'volume', 'wap', 'bar_count']
        available_value_cols = [col for col in value_cols if col in duplicates_df.columns]

        # For each duplicate group, check if values are identical
        for idx, row in dup_groups.head(5).iterrows():
            time_val = row['time']

            # Filter for this specific timestamp
            group_df = duplicates_df[duplicates_df['time'] == time_val]

            print(f"\n   Time: {time_val} ({row['count']} duplicates)")
            for col in available_value_cols:
                unique_vals = group_df[col].unique()
                if len(unique_vals) == 1:
                    print(f"     {col}: {unique_vals[0]} (identical)")
                else:
                    print(f"     {col}: {list(unique_vals)} (DIFFERENT!)")
    else:
        print("\n   ✓ No duplicates found - data is clean!")

# Summary statistics
print("\n9. Data Summary:")
print("=" * 80)
print(f"Date range: {df_contract['time'].min()} to {df_contract['time'].max()}")
if 'bar_size' in df_contract.columns:
    print(f"Bar sizes: {df_contract['bar_size'].unique()}")
print(f"Volume range: {df_contract['volume'].min()} to {df_contract['volume'].max()}")
print(f"Price range: ${df_contract['low'].min():.2f} to ${df_contract['high'].max():.2f}")

# Show all column names for reference
print("\n10. Available Columns:")
print(df_contract.columns.tolist())

print("\n" + "=" * 80)
print("Analysis complete!")
print("=" * 80)
