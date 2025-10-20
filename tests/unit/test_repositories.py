"""
Unit tests for reader repositories.

Tests the SQL query wrappers for EquityBarsReader, OptionBarsReader,
and OptionChainSnapshotReader using a test DuckDB database.
"""

import pytest
from datetime import date, datetime
from pathlib import Path
import duckdb
import pandas as pd
import tempfile

from dlt_ibapi.repositories import (
    EquityBarsReader,
    OptionBarsReader,
    OptionChainSnapshotReader,
)


@pytest.fixture
def test_db():
    """Create temporary test database with sample data."""
    # Create temp directory for test database
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.duckdb"
        conn = duckdb.connect(str(db_path))

        # Create datasets (schemas)
        conn.execute("CREATE SCHEMA IF NOT EXISTS stocks")
        conn.execute("CREATE SCHEMA IF NOT EXISTS options")

        # Create equity_bars_backfill table
        conn.execute("""
            CREATE TABLE stocks.equity_bars_backfill (
                symbol VARCHAR,
                bar_size VARCHAR,
                time TIMESTAMP,
                open DOUBLE,
                high DOUBLE,
                low DOUBLE,
                close DOUBLE,
                volume DOUBLE,
                PRIMARY KEY (symbol, bar_size, time)
            )
        """)

        # Insert sample equity data
        equity_data = [
            ("AAPL", "1 day", datetime(2024, 1, 2, 16, 0), 150.0, 152.0, 149.0, 151.0, 1000000),
            ("AAPL", "1 day", datetime(2024, 1, 3, 16, 0), 151.0, 153.0, 150.0, 152.0, 1100000),
            ("AAPL", "1 day", datetime(2024, 1, 4, 16, 0), 152.0, 154.0, 151.0, 153.0, 1200000),
            ("MSFT", "1 day", datetime(2024, 1, 2, 16, 0), 370.0, 372.0, 369.0, 371.0, 500000),
            ("MSFT", "1 day", datetime(2024, 1, 3, 16, 0), 371.0, 373.0, 370.0, 372.0, 550000),
        ]

        for row in equity_data:
            conn.execute("""
                INSERT INTO stocks.equity_bars_backfill VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, row)

        # Create option_bars_backfill table
        conn.execute("""
            CREATE TABLE options.option_bars_backfill (
                underlying VARCHAR,
                expiry DATE,
                strike DOUBLE,
                right VARCHAR,
                bar_size VARCHAR,
                time TIMESTAMP,
                open DOUBLE,
                high DOUBLE,
                low DOUBLE,
                close DOUBLE,
                volume DOUBLE,
                PRIMARY KEY (underlying, expiry, strike, right, bar_size, time)
            )
        """)

        # Insert sample option data
        option_data = [
            ("AAPL", date(2024, 6, 21), 150.0, "C", "1 day", datetime(2024, 1, 2, 16, 0), 5.0, 5.5, 4.8, 5.2, 100),
            ("AAPL", date(2024, 6, 21), 150.0, "C", "1 day", datetime(2024, 1, 3, 16, 0), 5.2, 5.7, 5.0, 5.5, 110),
            ("AAPL", date(2024, 6, 21), 155.0, "C", "1 day", datetime(2024, 1, 2, 16, 0), 3.0, 3.5, 2.8, 3.2, 80),
            ("AAPL", date(2024, 6, 21), 150.0, "P", "1 day", datetime(2024, 1, 2, 16, 0), 4.0, 4.5, 3.8, 4.2, 90),
        ]

        for row in option_data:
            conn.execute("""
                INSERT INTO options.option_bars_backfill VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, row)

        # Create option_chain_snapshot table
        conn.execute("""
            CREATE TABLE options.option_chain_snapshot (
                underlying VARCHAR,
                as_of DATE,
                exchange VARCHAR,
                trading_class VARCHAR,
                multiplier VARCHAR,
                expirations VARCHAR[],
                strikes DOUBLE[],
                expiration_count INTEGER,
                strike_count INTEGER,
                captured_at TIMESTAMP,
                PRIMARY KEY (underlying, as_of, exchange, trading_class)
            )
        """)

        # Insert sample snapshot
        conn.execute("""
            INSERT INTO options.option_chain_snapshot VALUES (
                'AAPL',
                '2024-01-02',
                'SMART',
                'AAPL',
                '100',
                ['20240621', '20240719', '20240816'],
                [140.0, 145.0, 150.0, 155.0, 160.0],
                3,
                5,
                '2024-01-02 09:30:00'
            )
        """)

        conn.close()

        yield db_path


class TestEquityBarsReader:
    """Tests for EquityBarsReader."""

    def test_initialization(self, test_db):
        """Test reader initialization."""
        reader = EquityBarsReader(str(test_db), "stocks")
        assert reader.dataset_name == "stocks"
        assert reader.destination_type == "duckdb"

    def test_get_present_dates_for_symbol(self, test_db):
        """Test getting present dates for a symbol."""
        reader = EquityBarsReader(str(test_db), "stocks")

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

    def test_get_bars(self, test_db):
        """Test getting bars for a symbol."""
        reader = EquityBarsReader(str(test_db), "stocks")

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

    def test_get_bars_with_limit(self, test_db):
        """Test getting bars with limit."""
        reader = EquityBarsReader(str(test_db), "stocks")

        bars = reader.get_bars(
            symbol="AAPL",
            bar_size="1 day",
            limit=1,
        )

        assert len(bars) == 1

    def test_get_date_range(self, test_db):
        """Test getting date range."""
        reader = EquityBarsReader(str(test_db), "stocks")

        min_date, max_date = reader.get_date_range("AAPL", "1 day")

        assert min_date == date(2024, 1, 2)
        assert max_date == date(2024, 1, 4)

    def test_get_date_range_no_data(self, test_db):
        """Test getting date range for symbol with no data."""
        reader = EquityBarsReader(str(test_db), "stocks")

        min_date, max_date = reader.get_date_range("GOOGL", "1 day")

        assert min_date is None
        assert max_date is None

    def test_get_available_symbols(self, test_db):
        """Test getting available symbols."""
        reader = EquityBarsReader(str(test_db), "stocks")

        symbols = reader.get_available_symbols(bar_size="1 day")

        assert len(symbols) == 2
        assert "AAPL" in symbols
        assert "MSFT" in symbols

    def test_get_symbols_summary(self, test_db):
        """Test getting symbols summary."""
        reader = EquityBarsReader(str(test_db), "stocks")

        summary = reader.get_symbols_summary(bar_size="1 day")

        assert len(summary) == 2

        # Check AAPL row
        aapl = summary[summary["symbol"] == "AAPL"].iloc[0]
        assert aapl["bar_count"] == 3
        assert aapl["bar_size"] == "1 day"

        # Check MSFT row
        msft = summary[summary["symbol"] == "MSFT"].iloc[0]
        assert msft["bar_count"] == 2

    def test_count(self, test_db):
        """Test count method."""
        reader = EquityBarsReader(str(test_db), "stocks")

        count = reader.count(symbol="AAPL", bar_size="1 day")
        assert count == 3

        count_all = reader.count()
        assert count_all == 5  # 3 AAPL + 2 MSFT

    def test_case_insensitive_symbol(self, test_db):
        """Test that symbol queries are case-insensitive."""
        reader = EquityBarsReader(str(test_db), "stocks")

        # Query with lowercase
        bars_lower = reader.get_bars("aapl", "1 day")
        # Query with uppercase
        bars_upper = reader.get_bars("AAPL", "1 day")

        assert len(bars_lower) == len(bars_upper)


class TestOptionBarsReader:
    """Tests for OptionBarsReader."""

    def test_initialization(self, test_db):
        """Test reader initialization."""
        reader = OptionBarsReader(str(test_db), "options")
        assert reader.dataset_name == "options"

    def test_get_present_dates_for_contract(self, test_db):
        """Test getting present dates for specific contract."""
        reader = OptionBarsReader(str(test_db), "options")

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

    def test_get_bars(self, test_db):
        """Test getting bars for specific contract."""
        reader = OptionBarsReader(str(test_db), "options")

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

    def test_get_contracts_for_underlying(self, test_db):
        """Test getting all contracts for underlying."""
        reader = OptionBarsReader(str(test_db), "options")

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

    def test_get_available_expirations(self, test_db):
        """Test getting available expirations."""
        reader = OptionBarsReader(str(test_db), "options")

        expirations = reader.get_available_expirations(
            underlying="AAPL",
            bar_size="1 day",
        )

        assert len(expirations) == 1
        assert date(2024, 6, 21) in expirations

    def test_get_bars_with_date_filter(self, test_db):
        """Test getting bars with date filtering."""
        reader = OptionBarsReader(str(test_db), "options")

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

    def test_initialization(self, test_db):
        """Test reader initialization."""
        reader = OptionChainSnapshotReader(str(test_db), "options")
        assert reader.dataset_name == "options"

    def test_get_available_snapshots(self, test_db):
        """Test getting available snapshot dates."""
        reader = OptionChainSnapshotReader(str(test_db), "options")

        snapshots = reader.get_available_snapshots("AAPL")

        assert len(snapshots) == 1
        assert date(2024, 1, 2) in snapshots

    def test_get_chain_for_date(self, test_db):
        """Test getting chain for specific date."""
        reader = OptionChainSnapshotReader(str(test_db), "options")

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

    def test_get_available_expirations(self, test_db):
        """Test getting available expirations from snapshot."""
        reader = OptionChainSnapshotReader(str(test_db), "options")

        expirations = reader.get_available_expirations(
            underlying="AAPL",
            as_of=date(2024, 1, 2),
        )

        assert len(expirations) == 3
        assert date(2024, 6, 21) in expirations
        assert date(2024, 7, 19) in expirations
        assert date(2024, 8, 16) in expirations

    def test_get_strikes_for_expiry(self, test_db):
        """Test getting strikes for specific expiration."""
        reader = OptionChainSnapshotReader(str(test_db), "options")

        strikes = reader.get_strikes_for_expiry(
            underlying="AAPL",
            as_of=date(2024, 1, 2),
            expiry=date(2024, 6, 21),
        )

        assert len(strikes) == 5
        assert 140.0 in strikes
        assert 150.0 in strikes
        assert 160.0 in strikes

    def test_get_available_expirations_with_dte_filter(self, test_db):
        """Test getting expirations with DTE filtering."""
        reader = OptionChainSnapshotReader(str(test_db), "options")

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

    def test_get_chain_for_date_no_data(self, test_db):
        """Test getting chain for date with no snapshot."""
        reader = OptionChainSnapshotReader(str(test_db), "options")

        chain = reader.get_chain_for_date(
            underlying="AAPL",
            as_of=date(2024, 12, 31),
        )

        assert chain.empty


class TestBaseReaderMethods:
    """Tests for base reader methods (using EquityBarsReader)."""

    def test_load_with_columns(self, test_db):
        """Test load method with column selection."""
        reader = EquityBarsReader(str(test_db), "stocks")

        df = reader.load(
            columns=["symbol", "close"],
            symbol="AAPL",
        )

        assert len(df.columns) == 2
        assert "symbol" in df.columns
        assert "close" in df.columns

    def test_load_all_columns(self, test_db):
        """Test load method without column selection."""
        reader = EquityBarsReader(str(test_db), "stocks")

        df = reader.load(symbol="AAPL")

        assert "symbol" in df.columns
        assert "time" in df.columns
        assert "open" in df.columns
        assert "close" in df.columns

    def test_query_custom_sql(self, test_db):
        """Test custom SQL query."""
        reader = EquityBarsReader(str(test_db), "stocks")

        df = reader.query("""
            SELECT symbol, AVG(close) as avg_close
            FROM stocks.equity_bars_backfill
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

    def test_empty_result_set(self, test_db):
        """Test queries that return empty results."""
        reader = EquityBarsReader(str(test_db), "stocks")

        bars = reader.get_bars(
            symbol="NONEXISTENT",
            bar_size="1 day",
        )

        assert bars.empty

    def test_count_nonexistent_symbol(self, test_db):
        """Test count for nonexistent symbol."""
        reader = EquityBarsReader(str(test_db), "stocks")

        count = reader.count(symbol="NONEXISTENT")
        assert count == 0

    def test_get_present_dates_empty_range(self, test_db):
        """Test get_present_dates with no data in range."""
        reader = EquityBarsReader(str(test_db), "stocks")

        present = reader.get_present_dates_for_symbol(
            symbol="AAPL",
            bar_size="1 day",
            start_date=date(2025, 1, 1),
            end_date=date(2025, 12, 31),
        )

        assert len(present) == 0
