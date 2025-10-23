"""
Unit tests for SelectedContractsReader.

Tests the Parquet reader for selected option contracts using test Parquet files.
"""

import pytest
from datetime import date, datetime
from pathlib import Path
import tempfile
import os
import dlt
import pandas as pd

from dlt_ibapi.repositories import SelectedContractsReader


@pytest.fixture
def test_parquet_dir():
    """Create temporary Parquet files with sample selected contracts data using DLT."""
    with tempfile.TemporaryDirectory() as tmpdir:
        data_dir = Path(tmpdir)

        # Create sample selected contracts data
        contracts_data = [
            {
                "underlying": "AAPL",
                "expiry": date(2024, 2, 16),
                "strike": 185.0,
                "right": "C",
                "conid": 12345,
                "local_symbol": "AAPL  240216C00185000",
                "exchange": "SMART",
                "trading_class": "AAPL",
                "multiplier": "100",
                "strategy": "closest_match",
                "delta": 0.50,
                "reason": "closest_match_call",
                "spot_price": 185.0,
                "snapshot_date": date(2024, 1, 15),
            },
            {
                "underlying": "AAPL",
                "expiry": date(2024, 2, 16),
                "strike": 190.0,
                "right": "C",
                "conid": 12346,
                "local_symbol": "AAPL  240216C00190000",
                "exchange": "SMART",
                "trading_class": "AAPL",
                "multiplier": "100",
                "strategy": "black_scholes",
                "delta": 0.30,
                "reason": "black_scholes_call",
                "spot_price": 185.0,
                "snapshot_date": date(2024, 1, 15),
            },
            {
                "underlying": "AAPL",
                "expiry": date(2024, 2, 16),
                "strike": 180.0,
                "right": "P",
                "conid": 12347,
                "local_symbol": "AAPL  240216P00180000",
                "exchange": "SMART",
                "trading_class": "AAPL",
                "multiplier": "100",
                "strategy": "closest_match",
                "delta": -0.30,
                "reason": "closest_match_put",
                "spot_price": 185.0,
                "snapshot_date": date(2024, 1, 15),
            },
            {
                "underlying": "MSFT",
                "expiry": date(2024, 2, 16),
                "strike": 370.0,
                "right": "C",
                "conid": 12348,
                "local_symbol": "MSFT  240216C00370000",
                "exchange": "SMART",
                "trading_class": "MSFT",
                "multiplier": "100",
                "strategy": "black_scholes",
                "delta": 0.50,
                "reason": "black_scholes_call",
                "spot_price": 370.0,
                "snapshot_date": date(2024, 1, 15),
            },
            # Add contracts for different snapshot date
            {
                "underlying": "AAPL",
                "expiry": date(2024, 3, 15),
                "strike": 188.0,
                "right": "C",
                "conid": 12349,
                "local_symbol": "AAPL  240315C00188000",
                "exchange": "SMART",
                "trading_class": "AAPL",
                "multiplier": "100",
                "strategy": "closest_match",
                "delta": 0.50,
                "reason": "closest_match_call",
                "spot_price": 188.0,
                "snapshot_date": date(2024, 2, 1),
            },
        ]

        # Write data using DLT (with Parquet format)
        pipeline = dlt.pipeline(
            pipeline_name="test_selected_contracts",
            destination=dlt.destinations.filesystem(bucket_url=str(data_dir)),
            dataset_name="selected_contracts",
        )

        @dlt.resource(
            name="selected_option_contracts",
            write_disposition="replace",
            primary_key=["underlying", "expiry", "strike", "right", "strategy"],
            columns={
                "snapshot_date": {"partition": True},
                "underlying": {"partition": True},
            }
        )
        def contracts():
            yield from contracts_data

        pipeline.run(contracts(), loader_file_format="parquet")

        # Debug: print directory structure
        print(f"\n=== Data directory: {data_dir} ===")
        for root, dirs, files in os.walk(data_dir):
            level = root.replace(str(data_dir), '').count(os.sep)
            indent = ' ' * 2 * level
            print(f'{indent}{os.path.basename(root)}/')
            subindent = ' ' * 2 * (level + 1)
            for file in files:
                print(f'{subindent}{file}')

        yield str(data_dir)


class TestSelectedContractsReader:
    """Unit tests for SelectedContractsReader."""

    def test_get_all_contracts(self, test_parquet_dir):
        """Test getting all contracts without filtering."""
        reader = SelectedContractsReader(test_parquet_dir, "selected_contracts")
        df = reader.get_all_contracts()

        assert not df.empty
        assert len(df) == 5
        assert set(df["underlying"].unique()) == {"AAPL", "MSFT"}

    def test_get_all_contracts_filtered_by_date(self, test_parquet_dir):
        """Test filtering contracts by snapshot date."""
        reader = SelectedContractsReader(test_parquet_dir, "selected_contracts")
        df = reader.get_all_contracts(snapshot_date=date(2024, 1, 15))

        assert not df.empty
        assert len(df) == 4  # 4 contracts on 2024-01-15
        assert all(pd.to_datetime(df["snapshot_date"]).dt.date == date(2024, 1, 15))

    def test_get_contracts_for_symbol(self, test_parquet_dir):
        """Test getting contracts for specific symbol."""
        reader = SelectedContractsReader(test_parquet_dir, "selected_contracts")
        df = reader.get_contracts_for_symbol("AAPL")

        assert not df.empty
        assert len(df) == 4  # 4 AAPL contracts across both dates
        assert all(df["underlying"] == "AAPL")

    def test_get_contracts_for_symbol_with_date(self, test_parquet_dir):
        """Test getting contracts for symbol filtered by date."""
        reader = SelectedContractsReader(test_parquet_dir, "selected_contracts")
        df = reader.get_contracts_for_symbol("AAPL", snapshot_date=date(2024, 1, 15))

        assert not df.empty
        assert len(df) == 3  # 3 AAPL contracts on 2024-01-15
        assert all(df["underlying"] == "AAPL")
        assert all(pd.to_datetime(df["snapshot_date"]).dt.date == date(2024, 1, 15))

    def test_get_contracts_for_symbol_with_strategy(self, test_parquet_dir):
        """Test filtering contracts by strategy."""
        reader = SelectedContractsReader(test_parquet_dir, "selected_contracts")
        df = reader.get_contracts_for_symbol("AAPL", strategy="closest_match")

        assert not df.empty
        assert len(df) == 3  # 3 AAPL contracts with closest_match
        assert all(df["underlying"] == "AAPL")
        assert all(df["strategy"] == "closest_match")

    def test_get_contracts_by_strategy(self, test_parquet_dir):
        """Test getting contracts by strategy only."""
        reader = SelectedContractsReader(test_parquet_dir, "selected_contracts")
        df = reader.get_contracts_by_strategy("black_scholes")

        assert not df.empty
        assert len(df) == 2  # 2 contracts with black_scholes
        assert all(df["strategy"] == "black_scholes")

    def test_get_contracts_for_expiry(self, test_parquet_dir):
        """Test getting contracts for specific expiration."""
        reader = SelectedContractsReader(test_parquet_dir, "selected_contracts")
        df = reader.get_contracts_for_expiry("AAPL", expiry=date(2024, 2, 16))

        assert not df.empty
        assert len(df) == 3  # 3 AAPL contracts expiring 2024-02-16
        assert all(df["underlying"] == "AAPL")
        assert all(pd.to_datetime(df["expiry"]).dt.date == date(2024, 2, 16))

    def test_get_available_symbols(self, test_parquet_dir):
        """Test getting list of available symbols."""
        reader = SelectedContractsReader(test_parquet_dir, "selected_contracts")
        symbols = reader.get_available_symbols()

        assert len(symbols) == 2
        assert set(symbols) == {"AAPL", "MSFT"}

    def test_get_available_symbols_filtered_by_date(self, test_parquet_dir):
        """Test getting symbols filtered by snapshot date."""
        reader = SelectedContractsReader(test_parquet_dir, "selected_contracts")
        symbols = reader.get_available_symbols(snapshot_date=date(2024, 2, 1))

        assert len(symbols) == 1
        assert symbols == ["AAPL"]

    def test_get_contract_count_by_strategy(self, test_parquet_dir):
        """Test aggregate statistics by strategy."""
        reader = SelectedContractsReader(test_parquet_dir, "selected_contracts")
        df = reader.get_contract_count_by_strategy()

        assert not df.empty
        assert len(df) == 2  # 2 strategies
        assert set(df["strategy"].values) == {"closest_match", "black_scholes"}

        # Check counts
        closest_match_count = df[df["strategy"] == "closest_match"]["count"].values[0]
        black_scholes_count = df[df["strategy"] == "black_scholes"]["count"].values[0]

        assert closest_match_count == 3
        assert black_scholes_count == 2

    def test_empty_results(self, test_parquet_dir):
        """Test querying non-existent data returns empty DataFrame."""
        reader = SelectedContractsReader(test_parquet_dir, "selected_contracts")

        # Query non-existent symbol
        df = reader.get_contracts_for_symbol("TSLA")
        assert df.empty

        # Query non-existent strategy
        df = reader.get_contracts_by_strategy("ib_greeks")
        assert df.empty

        # Query future date
        df = reader.get_all_contracts(snapshot_date=date(2025, 1, 1))
        assert df.empty
