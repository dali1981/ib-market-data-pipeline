"""
Integration tests for backfill DLT resources.

Tests both option and equity backfill resources with mocked IB API,
verifying gap detection, contract selection, and data persistence.
"""

import pytest
import duckdb
import tempfile
from pathlib import Path
from datetime import date, datetime, timedelta
from typing import Iterator, List
from unittest.mock import Mock, patch, MagicMock

import dlt
from ib_async import Contract, Option, BarData

from dlt_ibapi.backfill.resources import (
    backfill_option_bars,
    backfill_equity_bars,
)
from dlt_ibapi.backfill.config import (
    OptionBackfillConfig,
    ContractSelectionMode,
)
from dlt_ibapi.config import IBConnectionConfig


class TestEquityBackfillResource:
    """Integration tests for equity bars backfill resource."""

    @pytest.fixture
    def temp_data_dir(self):
        """Create temporary data directory for Parquet files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            data_dir = Path(tmpdir) / "data"
            yield str(data_dir)

    @pytest.fixture
    def temp_cache(self):
        """Create temporary cache directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield tmpdir

    @pytest.fixture
    def mock_connection_config(self):
        """Mock IB connection configuration."""
        return IBConnectionConfig(
            host="127.0.0.1",
            port=7497,
            client_id=1,
            timeout=60,
            readonly=False,
        )

    @pytest.fixture
    def sample_bar_data(self):
        """Create sample bar data."""
        bars = []
        base_date = datetime(2024, 1, 1, 9, 30)  # Market open

        for i in range(5):  # 5 days of data
            bar_time = base_date + timedelta(days=i)
            bars.append(
                BarData(
                    date=bar_time,
                    open=450.0 + i,
                    high=455.0 + i,
                    low=449.0 + i,
                    close=452.0 + i,
                    volume=1000000 + i * 10000,
                    average=451.0 + i,
                    barCount=100 + i,
                )
            )
        return bars

    @patch("dlt_ibapi.backfill.resources.IBRuntime")
    def test_equity_backfill_basic(
        self,
        mock_runtime_class,
        temp_data_dir,
        temp_cache,
        mock_connection_config,
        sample_bar_data,
    ):
        """Test basic equity backfill execution."""
        # Setup mock
        mock_runtime = MagicMock()
        mock_runtime_class.return_value.__enter__.return_value = mock_runtime
        mock_runtime.get_historical_bars.return_value = sample_bar_data

        # Run pipeline
        pipeline = dlt.pipeline(
            pipeline_name="test_equity_backfill",
            destination=dlt.destinations.filesystem(bucket_url=temp_data_dir),
            dataset_name="stocks",
        )

        resource = backfill_equity_bars(
            symbol="SPY",
            database_path=temp_data_dir,
            dataset_name="stocks",
            cache_path=temp_cache,
            connection_config=mock_connection_config,
            start_date=date(2024, 1, 1),
            end_date=date(2024, 1, 5),
            bar_size="1 day",
        )

        info = pipeline.run(resource, loader_file_format="parquet")
        assert info.has_failed is False

        # Verify data written to database
        conn = duckdb.connect(":memory:")
        result = conn.execute(
            "SELECT COUNT(*) FROM parquet_scan('{Path(temp_data_dir) / "stocks" / "historical_bars"}/**/*.parquet', hive_partitioning=true) WHERE symbol = 'SPY'"
        ).fetchone()
        assert result[0] == 5  # 5 days of bars

    @patch("dlt_ibapi.backfill.resources.IBRuntime")
    def test_equity_backfill_data_structure(
        self,
        mock_runtime_class,
        temp_data_dir,
        temp_cache,
        mock_connection_config,
        sample_bar_data,
    ):
        """Test that equity backfill data has correct structure."""
        # Setup mock
        mock_runtime = MagicMock()
        mock_runtime_class.return_value.__enter__.return_value = mock_runtime
        mock_runtime.get_historical_bars.return_value = sample_bar_data

        pipeline = dlt.pipeline(
            pipeline_name="test_equity_structure",
            destination=dlt.destinations.filesystem(bucket_url=temp_data_dir),
            dataset_name="stocks",
        )

        resource = backfill_equity_bars(
            symbol="SPY",
            database_path=temp_data_dir,
            dataset_name="stocks",
            cache_path=temp_cache,
            connection_config=mock_connection_config,
            start_date=date(2024, 1, 1),
            end_date=date(2024, 1, 5),
            bar_size="1 day",
        )

        pipeline.run(resource, loader_file_format="parquet")

        # Verify data structure
        conn = duckdb.connect(":memory:")
        result = conn.execute(
            """
            SELECT
                symbol,
                bar_size,
                time,
                open,
                high,
                low,
                close,
                volume,
                average,
                bar_count
            FROM parquet_scan('{Path(temp_data_dir) / "stocks" / "historical_bars"}/**/*.parquet', hive_partitioning=true)
            WHERE symbol = 'SPY'
            ORDER BY time
            LIMIT 1
            """
        ).fetchone()

        assert result[0] == "SPY"  # symbol
        assert result[1] == "1 day"  # bar_size
        assert isinstance(result[2], datetime)  # time
        assert isinstance(result[3], float)  # open
        assert isinstance(result[4], float)  # high
        assert isinstance(result[5], float)  # low
        assert isinstance(result[6], float)  # close
        assert isinstance(result[7], int)  # volume
        assert isinstance(result[8], float)  # average
        assert isinstance(result[9], int)  # bar_count

    @patch("dlt_ibapi.backfill.resources.IBRuntime")
    def test_equity_backfill_gap_detection(
        self,
        mock_runtime_class,
        temp_data_dir,
        temp_cache,
        mock_connection_config,
    ):
        """Test that backfill only fetches missing data."""
        # Setup mock
        mock_runtime = MagicMock()
        mock_runtime_class.return_value.__enter__.return_value = mock_runtime

        # First run: populate database with some data
        initial_bars = [
            BarData(
                date=datetime(2024, 1, 1, 9, 30),
                open=450.0,
                high=455.0,
                low=449.0,
                close=452.0,
                volume=1000000,
                average=451.0,
                barCount=100,
            ),
            BarData(
                date=datetime(2024, 1, 2, 9, 30),
                open=452.0,
                high=456.0,
                low=451.0,
                close=454.0,
                volume=1100000,
                average=453.0,
                barCount=110,
            ),
            # Missing: 2024-01-03
            BarData(
                date=datetime(2024, 1, 4, 9, 30),
                open=454.0,
                high=458.0,
                low=453.0,
                close=456.0,
                volume=1200000,
                average=455.0,
                barCount=120,
            ),
            # Missing: 2024-01-05
        ]
        mock_runtime.get_historical_bars.return_value = initial_bars

        pipeline = dlt.pipeline(
            pipeline_name="test_equity_gap",
            destination=dlt.destinations.filesystem(bucket_url=temp_data_dir),
            dataset_name="stocks",
        )

        resource = backfill_equity_bars(
            symbol="SPY",
            database_path=temp_data_dir,
            dataset_name="stocks",
            cache_path=temp_cache,
            connection_config=mock_connection_config,
            start_date=date(2024, 1, 1),
            end_date=date(2024, 1, 5),
            bar_size="1 day",
        )

        pipeline.run(resource, loader_file_format="parquet")

        # Verify initial data
        conn = duckdb.connect(":memory:")
        initial_count = conn.execute(
            "SELECT COUNT(*) FROM parquet_scan('{Path(temp_data_dir) / "stocks" / "historical_bars"}/**/*.parquet', hive_partitioning=true) WHERE symbol = 'SPY'"
        ).fetchone()[0]
        assert initial_count == 3  # Only 3 bars initially

        # Second run: fill gaps
        gap_bars = [
            BarData(
                date=datetime(2024, 1, 3, 9, 30),
                open=454.0,
                high=457.0,
                low=452.0,
                close=455.0,
                volume=1150000,
                average=454.0,
                barCount=115,
            ),
            BarData(
                date=datetime(2024, 1, 5, 9, 30),
                open=456.0,
                high=460.0,
                low=455.0,
                close=458.0,
                volume=1250000,
                average=457.0,
                barCount=125,
            ),
        ]
        mock_runtime.get_historical_bars.return_value = gap_bars

        resource2 = backfill_equity_bars(
            symbol="SPY",
            database_path=temp_data_dir,
            dataset_name="stocks",
            cache_path=temp_cache,
            connection_config=mock_connection_config,
            start_date=date(2024, 1, 1),
            end_date=date(2024, 1, 5),
            bar_size="1 day",
        )

        pipeline.run(resource2)

        # Verify gaps filled
        final_count = conn.execute(
            "SELECT COUNT(*) FROM parquet_scan('{Path(temp_data_dir) / "stocks" / "historical_bars"}/**/*.parquet', hive_partitioning=true) WHERE symbol = 'SPY'"
        ).fetchone()[0]
        assert final_count == 5  # All 5 bars now present

    @patch("dlt_ibapi.backfill.resources.IBRuntime")
    def test_equity_backfill_multiple_symbols(
        self,
        mock_runtime_class,
        temp_data_dir,
        temp_cache,
        mock_connection_config,
    ):
        """Test backfill for multiple symbols."""
        # Setup mock
        mock_runtime = MagicMock()
        mock_runtime_class.return_value.__enter__.return_value = mock_runtime

        def get_bars_for_symbol(symbol, *args, **kwargs):
            if symbol == "SPY":
                return [
                    BarData(
                        date=datetime(2024, 1, 1, 9, 30),
                        open=450.0,
                        high=455.0,
                        low=449.0,
                        close=452.0,
                        volume=1000000,
                        average=451.0,
                        barCount=100,
                    )
                ]
            elif symbol == "QQQ":
                return [
                    BarData(
                        date=datetime(2024, 1, 1, 9, 30),
                        open=380.0,
                        high=385.0,
                        low=379.0,
                        close=382.0,
                        volume=900000,
                        average=381.0,
                        barCount=90,
                    )
                ]
            return []

        mock_runtime.get_historical_bars.side_effect = get_bars_for_symbol

        pipeline = dlt.pipeline(
            pipeline_name="test_equity_multi",
            destination=dlt.destinations.filesystem(bucket_url=temp_data_dir),
            dataset_name="stocks",
        )

        # Backfill SPY
        resource_spy = backfill_equity_bars(
            symbol="SPY",
            database_path=temp_data_dir,
            dataset_name="stocks",
            cache_path=temp_cache,
            connection_config=mock_connection_config,
            start_date=date(2024, 1, 1),
            end_date=date(2024, 1, 1),
            bar_size="1 day",
        )
        pipeline.run(resource_spy)

        # Backfill QQQ
        resource_qqq = backfill_equity_bars(
            symbol="QQQ",
            database_path=temp_data_dir,
            dataset_name="stocks",
            cache_path=temp_cache,
            connection_config=mock_connection_config,
            start_date=date(2024, 1, 1),
            end_date=date(2024, 1, 1),
            bar_size="1 day",
        )
        pipeline.run(resource_qqq)

        # Verify both symbols present
        conn = duckdb.connect(":memory:")
        spy_count = conn.execute(
            "SELECT COUNT(*) FROM parquet_scan('{Path(temp_data_dir) / "stocks" / "historical_bars"}/**/*.parquet', hive_partitioning=true) WHERE symbol = 'SPY'"
        ).fetchone()[0]
        qqq_count = conn.execute(
            "SELECT COUNT(*) FROM parquet_scan('{Path(temp_data_dir) / "stocks" / "historical_bars"}/**/*.parquet', hive_partitioning=true) WHERE symbol = 'QQQ'"
        ).fetchone()[0]

        assert spy_count == 1
        assert qqq_count == 1


class TestOptionBackfillResource:
    """Integration tests for option bars backfill resource."""

    @pytest.fixture
    def temp_db(self):
        """Create temporary database for testing."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.duckdb"

            # Pre-populate with snapshot data
            conn = duckdb.connect(str(db_path))
            conn.execute("CREATE SCHEMA IF NOT EXISTS options")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS options.option_chain_snapshot (
                    symbol VARCHAR,
                    expiration VARCHAR,
                    strike DOUBLE,
                    right VARCHAR,
                    exchange VARCHAR,
                    snapshot_date DATE,
                    PRIMARY KEY (symbol, expiration, strike, right, snapshot_date)
                )
                """
            )
            # Insert sample snapshot data
            conn.execute(
                """
                INSERT INTO options.option_chain_snapshot VALUES
                ('SPY', '20240115', 450.0, 'C', 'SMART', '2024-01-01'),
                ('SPY', '20240115', 460.0, 'C', 'SMART', '2024-01-01'),
                ('SPY', '20240115', 470.0, 'C', 'SMART', '2024-01-01'),
                ('SPY', '20240115', 450.0, 'P', 'SMART', '2024-01-01'),
                ('SPY', '20240115', 460.0, 'P', 'SMART', '2024-01-01'),
                ('SPY', '20240115', 470.0, 'P', 'SMART', '2024-01-01')
                """
            )
            conn.close()

            yield str(db_path)

    @pytest.fixture
    def temp_cache(self):
        """Create temporary cache directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield tmpdir

    @pytest.fixture
    def mock_connection_config(self):
        """Mock IB connection configuration."""
        return IBConnectionConfig(
            host="127.0.0.1",
            port=7497,
            client_id=1,
            timeout=60,
            readonly=False,
        )

    @pytest.fixture
    def sample_option_bars(self):
        """Create sample option bar data."""
        bars = []
        base_date = datetime(2024, 1, 1, 9, 30)

        for i in range(3):  # 3 days of data
            bar_time = base_date + timedelta(days=i)
            bars.append(
                BarData(
                    date=bar_time,
                    open=5.0 + i * 0.5,
                    high=5.5 + i * 0.5,
                    low=4.8 + i * 0.5,
                    close=5.2 + i * 0.5,
                    volume=1000 + i * 100,
                    average=5.1 + i * 0.5,
                    barCount=50 + i * 5,
                )
            )
        return bars

    @patch("dlt_ibapi.backfill.resources.IBRuntime")
    def test_option_backfill_atm_mode(
        self,
        mock_runtime_class,
        temp_data_dir,
        temp_cache,
        mock_connection_config,
        sample_option_bars,
    ):
        """Test option backfill with ATM selection mode."""
        # Setup mock
        mock_runtime = MagicMock()
        mock_runtime_class.return_value.__enter__.return_value = mock_runtime
        mock_runtime.get_historical_bars.return_value = sample_option_bars

        # Mock spot price for ATM calculation
        mock_runtime.get_spot_price.return_value = 460.0

        # Create config
        config = OptionBackfillConfig(
            symbol="SPY",
            expiration="20240115",
            selection_mode=ContractSelectionMode.K_AROUND_ATM,
            k_around_atm=1,
        )

        pipeline = dlt.pipeline(
            pipeline_name="test_option_backfill_atm",
            destination=dlt.destinations.filesystem(bucket_url=temp_data_dir),
            dataset_name="options",
        )

        resource = backfill_option_bars(
            config=config,
            database_path=temp_data_dir,
            dataset_name="options",
            cache_path=temp_cache,
            connection_config=mock_connection_config,
            start_date=date(2024, 1, 1),
            end_date=date(2024, 1, 3),
            bar_size="1 day",
        )

        info = pipeline.run(resource, loader_file_format="parquet")
        assert info.has_failed is False

        # Verify data written
        conn = duckdb.connect(":memory:")
        result = conn.execute(
            """
            SELECT COUNT(DISTINCT strike)
            FROM parquet_scan('{Path(temp_data_dir) / "options" / "option_bars_backfill"}/**/*.parquet', hive_partitioning=true)
            WHERE symbol = 'SPY' AND expiration = '20240115'
            """
        ).fetchone()
        # Should have selected strikes around 460 (ATM)
        assert result[0] > 0

    @patch("dlt_ibapi.backfill.resources.IBRuntime")
    def test_option_backfill_moneyness_mode(
        self,
        mock_runtime_class,
        temp_data_dir,
        temp_cache,
        mock_connection_config,
        sample_option_bars,
    ):
        """Test option backfill with moneyness selection mode."""
        # Setup mock
        mock_runtime = MagicMock()
        mock_runtime_class.return_value.__enter__.return_value = mock_runtime
        mock_runtime.get_historical_bars.return_value = sample_option_bars
        mock_runtime.get_spot_price.return_value = 460.0

        # Create config
        config = OptionBackfillConfig(
            symbol="SPY",
            expiration="20240115",
            selection_mode=ContractSelectionMode.MONEYNESS,
            moneyness_min=0.95,
            moneyness_max=1.05,
        )

        pipeline = dlt.pipeline(
            pipeline_name="test_option_backfill_moneyness",
            destination=dlt.destinations.filesystem(bucket_url=temp_data_dir),
            dataset_name="options",
        )

        resource = backfill_option_bars(
            config=config,
            database_path=temp_data_dir,
            dataset_name="options",
            cache_path=temp_cache,
            connection_config=mock_connection_config,
            start_date=date(2024, 1, 1),
            end_date=date(2024, 1, 3),
            bar_size="1 day",
        )

        info = pipeline.run(resource, loader_file_format="parquet")
        assert info.has_failed is False

        # Verify strikes within moneyness range
        conn = duckdb.connect(":memory:")
        result = conn.execute(
            """
            SELECT MIN(strike), MAX(strike)
            FROM parquet_scan('{Path(temp_data_dir) / "options" / "option_bars_backfill"}/**/*.parquet', hive_partitioning=true)
            WHERE symbol = 'SPY' AND expiration = '20240115'
            """
        ).fetchone()

        min_strike, max_strike = result
        spot = 460.0
        if min_strike and max_strike:
            assert min_strike >= spot * 0.95
            assert max_strike <= spot * 1.05

    @patch("dlt_ibapi.backfill.resources.IBRuntime")
    def test_option_backfill_all_mode(
        self,
        mock_runtime_class,
        temp_data_dir,
        temp_cache,
        mock_connection_config,
        sample_option_bars,
    ):
        """Test option backfill with ALL selection mode."""
        # Setup mock
        mock_runtime = MagicMock()
        mock_runtime_class.return_value.__enter__.return_value = mock_runtime
        mock_runtime.get_historical_bars.return_value = sample_option_bars

        # Create config
        config = OptionBackfillConfig(
            symbol="SPY",
            expiration="20240115",
            selection_mode=ContractSelectionMode.ALL,
        )

        pipeline = dlt.pipeline(
            pipeline_name="test_option_backfill_all",
            destination=dlt.destinations.filesystem(bucket_url=temp_data_dir),
            dataset_name="options",
        )

        resource = backfill_option_bars(
            config=config,
            database_path=temp_data_dir,
            dataset_name="options",
            cache_path=temp_cache,
            connection_config=mock_connection_config,
            start_date=date(2024, 1, 1),
            end_date=date(2024, 1, 3),
            bar_size="1 day",
        )

        info = pipeline.run(resource, loader_file_format="parquet")
        assert info.has_failed is False

        # Verify all strikes from snapshot were backfilled
        conn = duckdb.connect(":memory:")
        result = conn.execute(
            """
            SELECT COUNT(DISTINCT strike)
            FROM parquet_scan('{Path(temp_data_dir) / "options" / "option_bars_backfill"}/**/*.parquet', hive_partitioning=true)
            WHERE symbol = 'SPY' AND expiration = '20240115'
            """
        ).fetchone()
        # Should have all 3 strikes (450, 460, 470)
        assert result[0] == 3

    @patch("dlt_ibapi.backfill.resources.IBRuntime")
    def test_option_backfill_gap_detection(
        self,
        mock_runtime_class,
        temp_data_dir,
        temp_cache,
        mock_connection_config,
        sample_option_bars,
    ):
        """Test that option backfill detects and fills gaps."""
        # Setup mock
        mock_runtime = MagicMock()
        mock_runtime_class.return_value.__enter__.return_value = mock_runtime
        mock_runtime.get_historical_bars.return_value = sample_option_bars

        config = OptionBackfillConfig(
            symbol="SPY",
            expiration="20240115",
            selection_mode=ContractSelectionMode.ALL,
        )

        pipeline = dlt.pipeline(
            pipeline_name="test_option_gap",
            destination=dlt.destinations.filesystem(bucket_url=temp_data_dir),
            dataset_name="options",
        )

        # First run
        resource1 = backfill_option_bars(
            config=config,
            database_path=temp_data_dir,
            dataset_name="options",
            cache_path=temp_cache,
            connection_config=mock_connection_config,
            start_date=date(2024, 1, 1),
            end_date=date(2024, 1, 3),
            bar_size="1 day",
        )

        pipeline.run(resource1)

        # Verify initial data
        conn = duckdb.connect(":memory:")
        initial_count = conn.execute(
            "SELECT COUNT(*) FROM parquet_scan('{Path(temp_data_dir) / "options" / "option_bars_backfill"}/**/*.parquet', hive_partitioning=true)"
        ).fetchone()[0]

        # Second run (should be idempotent)
        resource2 = backfill_option_bars(
            config=config,
            database_path=temp_data_dir,
            dataset_name="options",
            cache_path=temp_cache,
            connection_config=mock_connection_config,
            start_date=date(2024, 1, 1),
            end_date=date(2024, 1, 3),
            bar_size="1 day",
        )

        pipeline.run(resource2)

        # Should have same count (idempotent)
        final_count = conn.execute(
            "SELECT COUNT(*) FROM parquet_scan('{Path(temp_data_dir) / "options" / "option_bars_backfill"}/**/*.parquet', hive_partitioning=true)"
        ).fetchone()[0]
        assert final_count == initial_count


class TestBackfillErrorHandling:
    """Test error handling in backfill resources."""

    @pytest.fixture
    def temp_db(self):
        """Create temporary database."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.duckdb"
            yield str(db_path)

    @pytest.fixture
    def temp_cache(self):
        """Create temporary cache directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield tmpdir

    @pytest.fixture
    def mock_connection_config(self):
        """Mock IB connection configuration."""
        return IBConnectionConfig(
            host="127.0.0.1",
            port=7497,
            client_id=1,
            timeout=60,
            readonly=False,
        )

    @patch("dlt_ibapi.backfill.resources.IBRuntime")
    def test_equity_backfill_with_ib_error(
        self,
        mock_runtime_class,
        temp_data_dir,
        temp_cache,
        mock_connection_config,
    ):
        """Test handling of IB API errors in equity backfill."""
        # Setup mock to raise error
        mock_runtime = MagicMock()
        mock_runtime_class.return_value.__enter__.return_value = mock_runtime
        mock_runtime.get_historical_bars.side_effect = Exception("IB API Error")

        pipeline = dlt.pipeline(
            pipeline_name="test_equity_error",
            destination=dlt.destinations.filesystem(bucket_url=temp_data_dir),
            dataset_name="stocks",
        )

        resource = backfill_equity_bars(
            symbol="SPY",
            database_path=temp_data_dir,
            dataset_name="stocks",
            cache_path=temp_cache,
            connection_config=mock_connection_config,
            start_date=date(2024, 1, 1),
            end_date=date(2024, 1, 5),
            bar_size="1 day",
        )

        # Pipeline should handle error gracefully
        with pytest.raises(Exception):
            pipeline.run(resource, loader_file_format="parquet")

    @patch("dlt_ibapi.backfill.resources.IBRuntime")
    def test_equity_backfill_empty_bars(
        self,
        mock_runtime_class,
        temp_data_dir,
        temp_cache,
        mock_connection_config,
    ):
        """Test handling of empty bar data."""
        # Setup mock to return empty list
        mock_runtime = MagicMock()
        mock_runtime_class.return_value.__enter__.return_value = mock_runtime
        mock_runtime.get_historical_bars.return_value = []

        pipeline = dlt.pipeline(
            pipeline_name="test_equity_empty",
            destination=dlt.destinations.filesystem(bucket_url=temp_data_dir),
            dataset_name="stocks",
        )

        resource = backfill_equity_bars(
            symbol="SPY",
            database_path=temp_data_dir,
            dataset_name="stocks",
            cache_path=temp_cache,
            connection_config=mock_connection_config,
            start_date=date(2024, 1, 1),
            end_date=date(2024, 1, 5),
            bar_size="1 day",
        )

        info = pipeline.run(resource, loader_file_format="parquet")
        assert info.has_failed is False

        # Should have zero records
        conn = duckdb.connect(":memory:")
        result = conn.execute(
            "SELECT COUNT(*) FROM parquet_scan('{Path(temp_data_dir) / "stocks" / "historical_bars"}/**/*.parquet', hive_partitioning=true)"
        ).fetchone()
        assert result[0] == 0

    def test_invalid_date_range(self, temp_data_dir, temp_cache, mock_connection_config):
        """Test that invalid date range raises error."""
        with pytest.raises(ValueError):
            resource = backfill_equity_bars(
                symbol="SPY",
                database_path=temp_data_dir,
                dataset_name="stocks",
                cache_path=temp_cache,
                connection_config=mock_connection_config,
                start_date=date(2024, 12, 31),  # End before start
                end_date=date(2024, 1, 1),
                bar_size="1 day",
            )
            # Consume the generator to trigger validation
            list(resource)
