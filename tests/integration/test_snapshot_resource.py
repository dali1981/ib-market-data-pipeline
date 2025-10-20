"""
Integration tests for option chain snapshot DLT resource.

Tests the snapshot_option_chain resource with mocked IB API,
verifying end-to-end pipeline execution and data persistence.
"""

import pytest
import duckdb
import tempfile
from pathlib import Path
from datetime import date, datetime
from typing import Iterator
from unittest.mock import Mock, patch, MagicMock

import dlt
from ib_async import Contract, Option

from dlt_ibapi.backfill.resources import snapshot_option_chain
from dlt_ibapi.config import IBConnectionConfig


class TestSnapshotResource:
    """Integration tests for snapshot_option_chain resource."""

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
    def sample_option_chain(self):
        """Create sample option chain data."""
        # Sample option contracts
        options = [
            # Calls
            Option("SPY", "20240115", 450.0, "C", "SMART"),
            Option("SPY", "20240115", 460.0, "C", "SMART"),
            Option("SPY", "20240115", 470.0, "C", "SMART"),
            # Puts
            Option("SPY", "20240115", 450.0, "P", "SMART"),
            Option("SPY", "20240115", 460.0, "P", "SMART"),
            Option("SPY", "20240115", 470.0, "P", "SMART"),
        ]
        return options

    @patch("dlt_ibapi.backfill.resources.IBRuntime")
    def test_snapshot_basic_execution(
        self,
        mock_runtime_class,
        temp_data_dir,
        temp_cache,
        mock_connection_config,
        sample_option_chain,
    ):
        """Test basic snapshot execution with mocked IB API."""
        # Setup mock
        mock_runtime = MagicMock()
        mock_runtime_class.return_value.__enter__.return_value = mock_runtime
        mock_runtime.get_option_chain.return_value = sample_option_chain

        # Run pipeline
        pipeline = dlt.pipeline(
            pipeline_name="test_snapshot",
            destination=dlt.destinations.filesystem(bucket_url=temp_data_dir),
            dataset_name="options",
        )

        resource = snapshot_option_chain(
            symbol="SPY",
            database_path=temp_data_dir,
            dataset_name="options",
            cache_path=temp_cache,
            connection_config=mock_connection_config,
        )

        info = pipeline.run(resource, loader_file_format="parquet")
        assert info.has_failed is False

        # Verify data written to Parquet files
        conn = duckdb.connect(":memory:")
        parquet_path = Path(temp_data_dir) / "options" / "option_chain_snapshot"
        result = conn.execute(
            f"SELECT COUNT(*) FROM parquet_scan('{parquet_path}/**/*.parquet', hive_partitioning=true)"
        ).fetchone()
        assert result[0] == 6  # 6 option contracts

    @patch("dlt_ibapi.backfill.resources.IBRuntime")
    def test_snapshot_data_structure(
        self,
        mock_runtime_class,
        temp_data_dir,
        temp_cache,
        mock_connection_config,
        sample_option_chain,
    ):
        """Test that snapshot data has correct structure."""
        # Setup mock
        mock_runtime = MagicMock()
        mock_runtime_class.return_value.__enter__.return_value = mock_runtime
        mock_runtime.get_option_chain.return_value = sample_option_chain

        # Run pipeline
        pipeline = dlt.pipeline(
            pipeline_name="test_snapshot_structure",
            destination=dlt.destinations.filesystem(bucket_url=temp_data_dir),
            dataset_name="options",
        )

        resource = snapshot_option_chain(
            symbol="SPY",
            database_path=temp_data_dir,
            dataset_name="options",
            cache_path=temp_cache,
            connection_config=mock_connection_config,
        )

        pipeline.run(resource, loader_file_format="parquet")

        # Verify data structure
        conn = duckdb.connect(":memory:")
        parquet_path = Path(temp_data_dir) / "options" / "option_chain_snapshot"
        result = conn.execute(
            f"""
            SELECT
                symbol,
                expiration,
                strike,
                right,
                exchange,
                snapshot_date
            FROM parquet_scan('{parquet_path}/**/*.parquet', hive_partitioning=true)
            WHERE strike = 450.0 AND right = 'C'
            """
        ).fetchone()

        assert result[0] == "SPY"  # symbol
        assert result[1] == "20240115"  # expiration
        assert result[2] == 450.0  # strike
        assert result[3] == "C"  # right
        assert result[4] == "SMART"  # exchange
        assert isinstance(result[5], date)  # snapshot_date

    @patch("dlt_ibapi.backfill.resources.IBRuntime")
    def test_snapshot_idempotency(
        self,
        mock_runtime_class,
        temp_data_dir,
        temp_cache,
        mock_connection_config,
        sample_option_chain,
    ):
        """Test that running snapshot twice doesn't duplicate data."""
        # Setup mock
        mock_runtime = MagicMock()
        mock_runtime_class.return_value.__enter__.return_value = mock_runtime
        mock_runtime.get_option_chain.return_value = sample_option_chain

        pipeline = dlt.pipeline(
            pipeline_name="test_snapshot_idempotent",
            destination=dlt.destinations.filesystem(bucket_url=temp_data_dir),
            dataset_name="options",
        )

        resource = snapshot_option_chain(
            symbol="SPY",
            database_path=temp_data_dir,
            dataset_name="options",
            cache_path=temp_cache,
            connection_config=mock_connection_config,
        )

        # Run twice
        pipeline.run(resource, loader_file_format="parquet")
        pipeline.run(resource, loader_file_format="parquet")

        # Should still have only 6 records (no duplicates)
        conn = duckdb.connect(":memory:")
        parquet_path = Path(temp_data_dir) / "options" / "option_chain_snapshot"
        result = conn.execute(
            f"SELECT COUNT(*) FROM parquet_scan('{parquet_path}/**/*.parquet', hive_partitioning=true)"
        ).fetchone()
        assert result[0] == 6

    @patch("dlt_ibapi.backfill.resources.IBRuntime")
    def test_snapshot_multiple_symbols(
        self,
        mock_runtime_class,
        temp_data_dir,
        temp_cache,
        mock_connection_config,
    ):
        """Test snapshots for multiple symbols."""
        # Setup mock
        mock_runtime = MagicMock()
        mock_runtime_class.return_value.__enter__.return_value = mock_runtime

        # Different chains for different symbols
        def get_chain_for_symbol(symbol, *args, **kwargs):
            if symbol == "SPY":
                return [
                    Option("SPY", "20240115", 450.0, "C", "SMART"),
                    Option("SPY", "20240115", 450.0, "P", "SMART"),
                ]
            elif symbol == "QQQ":
                return [
                    Option("QQQ", "20240115", 380.0, "C", "SMART"),
                    Option("QQQ", "20240115", 380.0, "P", "SMART"),
                ]
            return []

        mock_runtime.get_option_chain.side_effect = get_chain_for_symbol

        pipeline = dlt.pipeline(
            pipeline_name="test_snapshot_multi",
            destination=dlt.destinations.filesystem(bucket_url=temp_data_dir),
            dataset_name="options",
        )

        # Run for SPY
        resource_spy = snapshot_option_chain(
            symbol="SPY",
            database_path=temp_data_dir,
            dataset_name="options",
            cache_path=temp_cache,
            connection_config=mock_connection_config,
        )
        pipeline.run(resource_spy)

        # Run for QQQ
        resource_qqq = snapshot_option_chain(
            symbol="QQQ",
            database_path=temp_data_dir,
            dataset_name="options",
            cache_path=temp_cache,
            connection_config=mock_connection_config,
        )
        pipeline.run(resource_qqq)

        # Verify both symbols present
        conn = duckdb.connect(":memory:")
        parquet_path = Path(temp_data_dir) / "options" / "option_chain_snapshot"
        spy_count = conn.execute(
            "SELECT COUNT(*) FROM parquet_scan('{parquet_path}/**/*.parquet', hive_partitioning=true) WHERE symbol = 'SPY'"
        ).fetchone()[0]
        qqq_count = conn.execute(
            "SELECT COUNT(*) FROM parquet_scan('{parquet_path}/**/*.parquet', hive_partitioning=true) WHERE symbol = 'QQQ'"
        ).fetchone()[0]

        assert spy_count == 2
        assert qqq_count == 2

    @patch("dlt_ibapi.backfill.resources.IBRuntime")
    def test_snapshot_with_ib_error(
        self,
        mock_runtime_class,
        temp_data_dir,
        temp_cache,
        mock_connection_config,
    ):
        """Test handling of IB API errors."""
        # Setup mock to raise error
        mock_runtime = MagicMock()
        mock_runtime_class.return_value.__enter__.return_value = mock_runtime
        mock_runtime.get_option_chain.side_effect = Exception("IB API Error")

        pipeline = dlt.pipeline(
            pipeline_name="test_snapshot_error",
            destination=dlt.destinations.filesystem(bucket_url=temp_data_dir),
            dataset_name="options",
        )

        resource = snapshot_option_chain(
            symbol="SPY",
            database_path=temp_data_dir,
            dataset_name="options",
            cache_path=temp_cache,
            connection_config=mock_connection_config,
        )

        # Pipeline should handle error gracefully
        with pytest.raises(Exception):
            pipeline.run(resource, loader_file_format="parquet")

    @patch("dlt_ibapi.backfill.resources.IBRuntime")
    def test_snapshot_empty_chain(
        self,
        mock_runtime_class,
        temp_data_dir,
        temp_cache,
        mock_connection_config,
    ):
        """Test handling of empty option chain."""
        # Setup mock to return empty chain
        mock_runtime = MagicMock()
        mock_runtime_class.return_value.__enter__.return_value = mock_runtime
        mock_runtime.get_option_chain.return_value = []

        pipeline = dlt.pipeline(
            pipeline_name="test_snapshot_empty",
            destination=dlt.destinations.filesystem(bucket_url=temp_data_dir),
            dataset_name="options",
        )

        resource = snapshot_option_chain(
            symbol="SPY",
            database_path=temp_data_dir,
            dataset_name="options",
            cache_path=temp_cache,
            connection_config=mock_connection_config,
        )

        info = pipeline.run(resource, loader_file_format="parquet")
        assert info.has_failed is False

        # Should have zero records
        conn = duckdb.connect(":memory:")
        parquet_path = Path(temp_data_dir) / "options" / "option_chain_snapshot"
        result = conn.execute(
            "SELECT COUNT(*) FROM parquet_scan('{parquet_path}/**/*.parquet', hive_partitioning=true)"
        ).fetchone()
        assert result[0] == 0


class TestSnapshotWithContractCache:
    """Test snapshot interaction with contract cache."""

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

    @patch("dlt_ibapi.backfill.resources.IBRuntime")
    def test_snapshot_populates_cache(
        self,
        mock_runtime_class,
        temp_data_dir,
        temp_cache,
        mock_connection_config,
    ):
        """Test that snapshot populates contract cache."""
        # Setup mock
        mock_runtime = MagicMock()
        mock_runtime_class.return_value.__enter__.return_value = mock_runtime

        sample_options = [
            Option("SPY", "20240115", 450.0, "C", "SMART"),
            Option("SPY", "20240115", 450.0, "P", "SMART"),
        ]
        mock_runtime.get_option_chain.return_value = sample_options

        pipeline = dlt.pipeline(
            pipeline_name="test_snapshot_cache",
            destination=dlt.destinations.filesystem(bucket_url=temp_data_dir),
            dataset_name="options",
        )

        resource = snapshot_option_chain(
            symbol="SPY",
            database_path=temp_data_dir,
            dataset_name="options",
            cache_path=temp_cache,
            connection_config=mock_connection_config,
        )

        pipeline.run(resource, loader_file_format="parquet")

        # Verify cache file exists
        cache_path = Path(temp_cache)
        cache_files = list(cache_path.glob("*.json"))
        assert len(cache_files) > 0

    @patch("dlt_ibapi.backfill.resources.IBRuntime")
    def test_snapshot_with_custom_cache_path(
        self,
        mock_runtime_class,
        temp_data_dir,
        mock_connection_config,
    ):
        """Test snapshot with custom cache path."""
        with tempfile.TemporaryDirectory() as custom_cache:
            # Setup mock
            mock_runtime = MagicMock()
            mock_runtime_class.return_value.__enter__.return_value = mock_runtime

            sample_options = [
                Option("SPY", "20240115", 450.0, "C", "SMART"),
            ]
            mock_runtime.get_option_chain.return_value = sample_options

            pipeline = dlt.pipeline(
                pipeline_name="test_snapshot_custom_cache",
                destination=dlt.destinations.filesystem(bucket_url=temp_data_dir),
                dataset_name="options",
            )

            resource = snapshot_option_chain(
                symbol="SPY",
                database_path=temp_data_dir,
                dataset_name="options",
                cache_path=custom_cache,
                connection_config=mock_connection_config,
            )

            pipeline.run(resource, loader_file_format="parquet")

            # Verify cache in custom location
            cache_path = Path(custom_cache)
            cache_files = list(cache_path.glob("*.json"))
            assert len(cache_files) > 0
