"""
Unit tests for reader repositories.

Tests the Parquet reader wrappers for EquityBarsReader, OptionBarsReader,
and OptionChainSnapshotReader using test Parquet files.
"""

import pytest
from datetime import date, datetime
from pathlib import Path
import duckdb
import pandas as pd
import tempfile
import dlt

from dlt_ibapi.repositories import (
    EquityBarsReader,
    OptionBarsReader,
    OptionChainSnapshotReader,
)


@pytest.fixture
def test_parquet_dir():
    """Create temporary Parquet files with sample data using DLT."""
    # Create temp directory for Parquet files
    with tempfile.TemporaryDirectory() as tmpdir:
        data_dir = Path(tmpdir) / "data"

        # Create sample equity bars data
        equity_data = [
            {"symbol": "AAPL", "bar_size": "1 day", "time": datetime(2024, 1, 2, 16, 0), "date": "2024-01-02",
             "open": 150.0, "high": 152.0, "low": 149.0, "close": 151.0, "volume": 1000000, "wap": 150.5, "bar_count": 100},
            {"symbol": "AAPL", "bar_size": "1 day", "time": datetime(2024, 1, 3, 16, 0), "date": "2024-01-03",
             "open": 151.0, "high": 153.0, "low": 150.0, "close": 152.0, "volume": 1100000, "wap": 151.5, "bar_count": 110},
            {"symbol": "AAPL", "bar_size": "1 day", "time": datetime(2024, 1, 4, 16, 0), "date": "2024-01-04",
             "open": 152.0, "high": 154.0, "low": 151.0, "close": 153.0, "volume": 1200000, "wap": 152.5, "bar_count": 120},
            {"symbol": "MSFT", "bar_size": "1 day", "time": datetime(2024, 1, 2, 16, 0), "date": "2024-01-02",
             "open": 370.0, "high": 372.0, "low": 369.0, "close": 371.0, "volume": 500000, "wap": 370.5, "bar_count": 50},
            {"symbol": "MSFT", "bar_size": "1 day", "time": datetime(2024, 1, 3, 16, 0), "date": "2024-01-03",
             "open": 371.0, "high": 373.0, "low": 370.0, "close": 372.0, "volume": 550000, "wap": 371.5, "bar_count": 55},
        ]

        # Write equity data using DLT
        equity_pipeline = dlt.pipeline(
            pipeline_name="test_equity",
            destination=dlt.destinations.filesystem(bucket_url=str(data_dir)),
            dataset_name="stocks",
        )

        @dlt.resource(
            name="historical_bars",
            write_disposition="append",
            primary_key=["symbol", "bar_size", "time"],
            columns={
                "date": {"partition": True},
                "symbol": {"partition": True},
            }
        )
        def equity_bars():
            yield equity_data

        equity_pipeline.run(equity_bars(), loader_file_format="parquet")

        # Create sample option bars data
        option_data = [
            {"underlying": "AAPL", "expiry": date(2024, 6, 21), "strike": 150.0, "right": "C",
             "bar_size": "1 day", "time": datetime(2024, 1, 2, 16, 0), "date": "2024-01-02",
             "open": 5.0, "high": 5.5, "low": 4.8, "close": 5.2, "volume": 100, "wap": 5.1, "bar_count": 10},
            {"underlying": "AAPL", "expiry": date(2024, 6, 21), "strike": 150.0, "right": "C",
             "bar_size": "1 day", "time": datetime(2024, 1, 3, 16, 0), "date": "2024-01-03",
             "open": 5.2, "high": 5.7, "low": 5.0, "close": 5.5, "volume": 110, "wap": 5.3, "bar_count": 11},
            {"underlying": "AAPL", "expiry": date(2024, 6, 21), "strike": 155.0, "right": "C",
             "bar_size": "1 day", "time": datetime(2024, 1, 2, 16, 0), "date": "2024-01-02",
             "open": 3.0, "high": 3.5, "low": 2.8, "close": 3.2, "volume": 80, "wap": 3.1, "bar_count": 8},
            {"underlying": "AAPL", "expiry": date(2024, 6, 21), "strike": 150.0, "right": "P",
             "bar_size": "1 day", "time": datetime(2024, 1, 2, 16, 0), "date": "2024-01-02",
             "open": 4.0, "high": 4.5, "low": 3.8, "close": 4.2, "volume": 90, "wap": 4.1, "bar_count": 9},
        ]

        # Write option data using DLT
        option_pipeline = dlt.pipeline(
            pipeline_name="test_option_bars",
            destination=dlt.destinations.filesystem(bucket_url=str(data_dir)),
            dataset_name="options",
        )

        @dlt.resource(
            name="option_bars_backfill",
            write_disposition="append",
            primary_key=["underlying", "expiry", "strike", "right", "bar_size", "time"],
            columns={
                "date": {"partition": True},
                "symbol": {"partition": True},
            }
        )
        def option_bars():
            yield option_data

        option_pipeline.run(option_bars(), loader_file_format="parquet")

        # Create sample option chain snapshot data
        snapshot_data = [
            {
                "underlying": "AAPL",
                "as_of": date(2024, 1, 2),
                "date": "2024-01-02",
                "exchange": "SMART",
                "trading_class": "AAPL",
                "multiplier": "100",
                "expirations": ["20240621", "20240719", "20240816"],
                "strikes": [140.0, 145.0, 150.0, 155.0, 160.0],
                "expiration_count": 3,
                "strike_count": 5,
                "captured_at": datetime(2024, 1, 2, 9, 30, 0),
            }
        ]

        # Write snapshot data using DLT
        snapshot_pipeline = dlt.pipeline(
            pipeline_name="test_snapshot",
            destination=dlt.destinations.filesystem(bucket_url=str(data_dir)),
            dataset_name="options",
        )

        @dlt.resource(
            name="option_chain_snapshot",
            write_disposition="replace",
            primary_key=["underlying", "as_of", "exchange", "trading_class"],
            columns={
                "date": {"partition": True},
                "underlying": {"partition": True},
            }
        )
        def snapshots():
            yield snapshot_data

        snapshot_pipeline.run(snapshots(), loader_file_format="parquet")

        yield data_dir


class TestEquityBarsReader:
    """Tests for EquityBarsReader."""

    def test_initialization(self, test_parquet_dir):
        """Test reader initialization."""
        reader = EquityBarsReader(str(test_parquet_dir), "stocks")
        assert reader.dataset_name == "stocks"
        assert reader.destination_type == "filesystem"

    def test_get_present_dates_for_symbol(self, test_parquet_dir):
        """Test getting present dates for a symbol."""
        reader = EquityBarsReader(str(test_parquet_dir), "stocks")

        present = reader.get_present_dates_for_symbol(
            symbol="AAPL",
            bar_size="1 day",
            start_date=date(2024, 1, 1),
            end_date=date(2024, 1, 10),
        )

        # Should have 3 dates for AAPL
        assert len(present) == 3
        assert date(2024, 1, 2) in present
        assert date(2024, 1, 3) in present
        assert date(2024, 1, 4) in present

    def test_get_bars(self, test_parquet_dir):
        """Test getting bars for a symbol."""
        reader = EquityBarsReader(str(test_parquet_dir), "stocks")

        bars = reader.get_bars(
            symbol="AAPL",
            bar_size="1 day",
            start_date=date(2024, 1, 2),
            end_date=date(2024, 1, 3),
        )

        assert len(bars) == 2
        assert bars.iloc[0]["symbol"] == "AAPL"
        assert bars.iloc[0]["close"] == 151.0
        assert bars.iloc[1]["close"] == 152.0

    def test_get_bars_with_limit(self, test_parquet_dir):
        """Test getting bars with limit."""
        reader = EquityBarsReader(str(test_parquet_dir), "stocks")

        bars = reader.get_bars(
            symbol="AAPL",
            bar_size="1 day",
            limit=1,
        )

        assert len(bars) == 1

    def test_get_date_range(self, test_parquet_dir):
        """Test getting date range."""
        reader = EquityBarsReader(str(test_parquet_dir), "stocks")

        min_date, max_date = reader.get_date_range("AAPL", "1 day")

        assert min_date == date(2024, 1, 2)
        assert max_date == date(2024, 1, 4)

    def test_get_date_range_no_data(self, test_parquet_dir):
        """Test getting date range for symbol with no data."""
        reader = EquityBarsReader(str(test_parquet_dir), "stocks")

        min_date, max_date = reader.get_date_range("GOOGL", "1 day")

        assert min_date is None
        assert max_date is None

    def test_get_available_symbols(self, test_parquet_dir):
        """Test getting available symbols."""
        reader = EquityBarsReader(str(test_parquet_dir), "stocks")

        symbols = reader.get_available_symbols(bar_size="1 day")

        assert len(symbols) == 2
        assert "AAPL" in symbols
        assert "MSFT" in symbols

    def test_get_symbols_summary(self, test_parquet_dir):
        """Test getting symbols summary."""
        reader = EquityBarsReader(str(test_parquet_dir), "stocks")

        summary = reader.get_symbols_summary(bar_size="1 day")

        assert len(summary) == 2

        # Check AAPL row
        aapl = summary[summary["symbol"] == "AAPL"].iloc[0]
        assert aapl["bar_count"] == 3
        assert aapl["bar_size"] == "1 day"

        # Check MSFT row
        msft = summary[summary["symbol"] == "MSFT"].iloc[0]
        assert msft["bar_count"] == 2

    def test_count(self, test_parquet_dir):
        """Test count method."""
        reader = EquityBarsReader(str(test_parquet_dir), "stocks")

        count = reader.count(symbol="AAPL", bar_size="1 day")
        assert count == 3

        count_all = reader.count()
        assert count_all == 5  # 3 AAPL + 2 MSFT

    def test_case_insensitive_symbol(self, test_parquet_dir):
        """Test that symbol queries are case-insensitive."""
        reader = EquityBarsReader(str(test_parquet_dir), "stocks")

        # Query with lowercase
        bars_lower = reader.get_bars("aapl", "1 day")
        # Query with uppercase
        bars_upper = reader.get_bars("AAPL", "1 day")

        assert len(bars_lower) == len(bars_upper)


class TestOptionBarsReader:
    """Tests for OptionBarsReader."""

    def test_initialization(self, test_parquet_dir):
        """Test reader initialization."""
        reader = OptionBarsReader(str(test_parquet_dir), "options")
        assert reader.dataset_name == "options"

    def test_get_present_dates_for_contract(self, test_parquet_dir):
        """Test getting present dates for specific contract."""
        reader = OptionBarsReader(str(test_parquet_dir), "options")

        present = reader.get_present_dates_for_contract(
            underlying="AAPL",
            expiry=date(2024, 6, 21),
            strike=150.0,
            right="C",
            bar_size="1 day",
            start_date=date(2024, 1, 1),
            end_date=date(2024, 1, 10),
        )

        # Should have 2 dates for AAPL 150C
        assert len(present) == 2
        assert date(2024, 1, 2) in present
        assert date(2024, 1, 3) in present

    def test_get_bars(self, test_parquet_dir):
        """Test getting bars for specific contract."""
        reader = OptionBarsReader(str(test_parquet_dir), "options")

        bars = reader.get_bars(
            underlying="AAPL",
            expiry=date(2024, 6, 21),
            strike=150.0,
            right="C",
            bar_size="1 day",
        )

        assert len(bars) == 2
        assert bars.iloc[0]["underlying"] == "AAPL"
        assert bars.iloc[0]["strike"] == 150.0
        assert bars.iloc[0]["right"] == "C"

    def test_get_contracts_for_underlying(self, test_parquet_dir):
        """Test getting all contracts for underlying."""
        reader = OptionBarsReader(str(test_parquet_dir), "options")

        contracts = reader.get_contracts_for_underlying(
            underlying="AAPL",
            bar_size="1 day",
        )

        # Should have 3 unique contracts (150C, 155C, 150P)
        assert len(contracts) == 3

        # Check metadata columns
        assert "expiry" in contracts.columns
        assert "strike" in contracts.columns
        assert "right" in contracts.columns
        assert "bar_count" in contracts.columns
        assert "first_bar" in contracts.columns
        assert "last_bar" in contracts.columns

    def test_get_available_expirations(self, test_parquet_dir):
        """Test getting available expirations."""
        reader = OptionBarsReader(str(test_parquet_dir), "options")

        expirations = reader.get_available_expirations(
            underlying="AAPL",
            bar_size="1 day",
        )

        assert len(expirations) == 1
        assert date(2024, 6, 21) in expirations

    def test_get_bars_with_date_filter(self, test_parquet_dir):
        """Test getting bars with date filtering."""
        reader = OptionBarsReader(str(test_parquet_dir), "options")

        bars = reader.get_bars(
            underlying="AAPL",
            expiry=date(2024, 6, 21),
            strike=150.0,
            right="C",
            bar_size="1 day",
            start_date=date(2024, 1, 3),
            end_date=date(2024, 1, 3),
        )

        assert len(bars) == 1
        assert bars.iloc[0]["close"] == 5.5


class TestOptionChainSnapshotReader:
    """Tests for OptionChainSnapshotReader."""

    def test_initialization(self, test_parquet_dir):
        """Test reader initialization."""
        reader = OptionChainSnapshotReader(str(test_parquet_dir), "options")
        assert reader.dataset_name == "options"

    def test_get_available_snapshots(self, test_parquet_dir):
        """Test getting available snapshot dates."""
        reader = OptionChainSnapshotReader(str(test_parquet_dir), "options")

        snapshots = reader.get_available_snapshots("AAPL")

        assert len(snapshots) == 1
        assert date(2024, 1, 2) in snapshots

    def test_get_chain_for_date(self, test_parquet_dir):
        """Test getting chain for specific date."""
        reader = OptionChainSnapshotReader(str(test_parquet_dir), "options")

        chain = reader.get_chain_for_date(
            underlying="AAPL",
            as_of=date(2024, 1, 2),
        )

        assert len(chain) == 1
        row = chain.iloc[0]
        assert row["underlying"] == "AAPL"
        assert row["exchange"] == "SMART"
        assert row["expiration_count"] == 3
        assert row["strike_count"] == 5

    def test_get_available_expirations(self, test_parquet_dir):
        """Test getting available expirations from snapshot."""
        reader = OptionChainSnapshotReader(str(test_parquet_dir), "options")

        expirations = reader.get_available_expirations(
            underlying="AAPL",
            as_of=date(2024, 1, 2),
        )

        assert len(expirations) == 3
        assert date(2024, 6, 21) in expirations
        assert date(2024, 7, 19) in expirations
        assert date(2024, 8, 16) in expirations

    def test_get_strikes_for_expiry(self, test_parquet_dir):
        """Test getting strikes for specific expiration."""
        reader = OptionChainSnapshotReader(str(test_parquet_dir), "options")

        strikes = reader.get_strikes_for_expiry(
            underlying="AAPL",
            as_of=date(2024, 1, 2),
            expiry=date(2024, 6, 21),
        )

        assert len(strikes) == 5
        assert 140.0 in strikes
        assert 150.0 in strikes
        assert 160.0 in strikes

    def test_get_available_expirations_with_dte_filter(self, test_parquet_dir):
        """Test getting expirations with DTE filtering."""
        reader = OptionChainSnapshotReader(str(test_parquet_dir), "options")

        # Filter for expirations 140-200 days out
        expirations = reader.get_available_expirations(
            underlying="AAPL",
            as_of=date(2024, 1, 2),
            min_dte=140,
            max_dte=200,
        )

        # Should filter to middle expiration (6/21 is ~170 days)
        assert len(expirations) == 1
        assert date(2024, 6, 21) in expirations

    def test_get_chain_for_date_no_data(self, test_parquet_dir):
        """Test getting chain for date with no snapshot."""
        reader = OptionChainSnapshotReader(str(test_parquet_dir), "options")

        chain = reader.get_chain_for_date(
            underlying="AAPL",
            as_of=date(2024, 12, 31),
        )

        assert chain.empty


class TestBaseReaderMethods:
    """Tests for base reader methods (using EquityBarsReader)."""

    def test_load_with_columns(self, test_parquet_dir):
        """Test load method with column selection."""
        reader = EquityBarsReader(str(test_parquet_dir), "stocks")

        df = reader.load(
            columns=["symbol", "close"],
            symbol="AAPL",
        )

        assert len(df.columns) == 2
        assert "symbol" in df.columns
        assert "close" in df.columns

    def test_load_all_columns(self, test_parquet_dir):
        """Test load method without column selection."""
        reader = EquityBarsReader(str(test_parquet_dir), "stocks")

        df = reader.load(symbol="AAPL")

        assert "symbol" in df.columns
        assert "time" in df.columns
        assert "open" in df.columns
        assert "close" in df.columns

    def test_query_custom_sql(self, test_parquet_dir):
        """Test custom SQL query."""
        reader = EquityBarsReader(str(test_parquet_dir), "stocks")

        df = reader.query("""
            SELECT symbol, AVG(close) as avg_close
            FROM stocks.historical_bars
            WHERE symbol = $symbol
            GROUP BY symbol
        """, params={"symbol": "AAPL"})

        assert len(df) == 1
        assert df.iloc[0]["symbol"] == "AAPL"
        assert df.iloc[0]["avg_close"] > 0


class TestEdgeCases:
    """Test edge cases and error handling."""

    def test_invalid_database_path(self):
        """Test with non-existent database."""
        reader = EquityBarsReader("/nonexistent/path.duckdb", "stocks")

        with pytest.raises(Exception):  # DuckDB will raise
            reader.get_available_symbols()

    def test_empty_result_set(self, test_parquet_dir):
        """Test queries that return empty results."""
        reader = EquityBarsReader(str(test_parquet_dir), "stocks")

        bars = reader.get_bars(
            symbol="NONEXISTENT",
            bar_size="1 day",
        )

        assert bars.empty

    def test_count_nonexistent_symbol(self, test_parquet_dir):
        """Test count for nonexistent symbol."""
        reader = EquityBarsReader(str(test_parquet_dir), "stocks")

        count = reader.count(symbol="NONEXISTENT")
        assert count == 0

    def test_get_present_dates_empty_range(self, test_parquet_dir):
        """Test get_present_dates with no data in range."""
        reader = EquityBarsReader(str(test_parquet_dir), "stocks")

        present = reader.get_present_dates_for_symbol(
            symbol="AAPL",
            bar_size="1 day",
            start_date=date(2025, 1, 1),
            end_date=date(2025, 12, 31),
        )

        assert len(present) == 0
