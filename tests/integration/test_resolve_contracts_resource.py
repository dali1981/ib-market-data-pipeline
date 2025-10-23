"""
Integration tests for resolve_contracts_resource.

Tests the DLT resource for resolving ticker symbols to IB contracts with mocked IB API.
"""

import pytest
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock
import dlt
import duckdb

from dlt_ibapi.backfill.resources import resolve_contracts_resource
from dlt_ibapi.config import IBConnectionConfig


class TestResolveContractsResource:
    """Integration tests for resolve_contracts_resource."""

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
            port=4002,
            client_id=999,
            ready_timeout=5.0,
        )

    @pytest.fixture
    def mock_runtime(self):
        """Mock IBRuntime."""
        with patch("dlt_ibapi.backfill.resources.IBRuntime") as mock_runtime_class:
            runtime_instance = MagicMock()
            mock_runtime_class.return_value = runtime_instance
            yield runtime_instance

    @pytest.fixture
    def mock_contract_resolver(self):
        """Mock ContractResolver with sample contract data."""
        with patch("dlt_ibapi.backfill.resources.ContractResolver") as mock_resolver_class:
            resolver_instance = MagicMock()

            # Mock resolve_symbol to return test data
            def mock_resolve(symbol, **kwargs):
                if symbol == "AAPL":
                    return {
                        "conid": 265598,
                        "local_symbol": "AAPL",
                        "sec_type": "STK",
                        "exchange": "NASDAQ",
                        "primary_exchange": "NASDAQ",
                        "currency": "USD",
                        "trading_class": "NMS",
                        "long_name": "APPLE INC",
                        "industry": "Technology",
                        "category": "Computers",
                        "subcategory": "Computers",
                    }
                elif symbol == "MSFT":
                    return {
                        "conid": 272093,
                        "local_symbol": "MSFT",
                        "sec_type": "STK",
                        "exchange": "NASDAQ",
                        "primary_exchange": "NASDAQ",
                        "currency": "USD",
                        "trading_class": "NMS",
                        "long_name": "MICROSOFT CORP",
                        "industry": "Technology",
                        "category": "Software",
                        "subcategory": "Application Software",
                    }
                elif symbol == "INVALID":
                    return None
                else:
                    return None

            resolver_instance.resolve_symbol = Mock(side_effect=mock_resolve)
            mock_resolver_class.return_value = resolver_instance
            yield resolver_instance

    def test_resolve_single_ticker(
        self,
        temp_data_dir,
        temp_cache,
        mock_connection_config,
        mock_runtime,
        mock_contract_resolver,
    ):
        """Test resolving a single ticker successfully."""
        # Create DLT pipeline
        pipeline = dlt.pipeline(
            pipeline_name="test_resolve_single",
            destination=dlt.destinations.filesystem(bucket_url=temp_data_dir),
            dataset_name="contracts",
        )

        # Run resource
        resource = resolve_contracts_resource(
            tickers=["AAPL"],
            cache_path=temp_cache,
            connection_config=mock_connection_config,
        )

        load_info = pipeline.run(resource, loader_file_format="parquet")

        # Verify runtime was started and stopped
        mock_runtime.start.assert_called_once()
        mock_runtime.stop.assert_called_once()

        # Verify resolver was called
        mock_contract_resolver.resolve_symbol.assert_called_with(
            symbol="AAPL",
            exchange="SMART",
            currency="USD",
            sec_type="STK",
            use_cache=True,
            save_to_cache=True,
        )

        # Verify data was written to Parquet
        conn = duckdb.connect()
        parquet_path = Path(temp_data_dir) / "contracts" / "contract_descriptions"
        df = conn.execute(f"SELECT * FROM '{parquet_path}/*.parquet'").df()

        assert not df.empty
        assert len(df) == 1
        assert df.iloc[0]["symbol"] == "AAPL"
        assert df.iloc[0]["conid"] == 265598
        assert df.iloc[0]["long_name"] == "APPLE INC"

    def test_resolve_multiple_tickers(
        self,
        temp_data_dir,
        temp_cache,
        mock_connection_config,
        mock_runtime,
        mock_contract_resolver,
    ):
        """Test resolving multiple tickers in batch."""
        pipeline = dlt.pipeline(
            pipeline_name="test_resolve_multiple",
            destination=dlt.destinations.filesystem(bucket_url=temp_data_dir),
            dataset_name="contracts",
        )

        resource = resolve_contracts_resource(
            tickers=["AAPL", "MSFT"],
            cache_path=temp_cache,
            connection_config=mock_connection_config,
        )

        load_info = pipeline.run(resource, loader_file_format="parquet")

        # Verify both tickers were resolved
        assert mock_contract_resolver.resolve_symbol.call_count == 2

        # Check Parquet data
        conn = duckdb.connect()
        parquet_path = Path(temp_data_dir) / "contracts" / "contract_descriptions"
        df = conn.execute(f"SELECT * FROM '{parquet_path}/*.parquet' ORDER BY symbol").df()

        assert len(df) == 2
        assert list(df["symbol"]) == ["AAPL", "MSFT"]
        assert list(df["conid"]) == [265598, 272093]

    def test_resolve_with_failed_ticker(
        self,
        temp_data_dir,
        temp_cache,
        mock_connection_config,
        mock_runtime,
        mock_contract_resolver,
    ):
        """Test that resolution continues even if one ticker fails."""
        pipeline = dlt.pipeline(
            pipeline_name="test_resolve_with_failure",
            destination=dlt.destinations.filesystem(bucket_url=temp_data_dir),
            dataset_name="contracts",
        )

        resource = resolve_contracts_resource(
            tickers=["AAPL", "INVALID", "MSFT"],
            cache_path=temp_cache,
            connection_config=mock_connection_config,
        )

        load_info = pipeline.run(resource, loader_file_format="parquet")

        # Verify all tickers were attempted
        assert mock_contract_resolver.resolve_symbol.call_count == 3

        # Check that only successful tickers are in Parquet
        conn = duckdb.connect()
        parquet_path = Path(temp_data_dir) / "contracts" / "contract_descriptions"
        df = conn.execute(f"SELECT * FROM '{parquet_path}/*.parquet' ORDER BY symbol").df()

        assert len(df) == 2
        assert list(df["symbol"]) == ["AAPL", "MSFT"]

    def test_resource_writes_to_parquet(
        self,
        temp_data_dir,
        temp_cache,
        mock_connection_config,
        mock_runtime,
        mock_contract_resolver,
    ):
        """Verify DLT writes data to Parquet correctly."""
        pipeline = dlt.pipeline(
            pipeline_name="test_parquet_write",
            destination=dlt.destinations.filesystem(bucket_url=temp_data_dir),
            dataset_name="contracts",
        )

        resource = resolve_contracts_resource(
            tickers=["AAPL"],
            cache_path=temp_cache,
            connection_config=mock_connection_config,
        )

        load_info = pipeline.run(resource, loader_file_format="parquet")

        # Check that Parquet file exists
        parquet_path = Path(temp_data_dir) / "contracts" / "contract_descriptions"
        assert parquet_path.exists()

        parquet_files = list(parquet_path.glob("*.parquet"))
        assert len(parquet_files) > 0

    def test_resource_schema(
        self,
        temp_data_dir,
        temp_cache,
        mock_connection_config,
        mock_runtime,
        mock_contract_resolver,
    ):
        """Verify Parquet schema matches expected structure."""
        pipeline = dlt.pipeline(
            pipeline_name="test_schema",
            destination=dlt.destinations.filesystem(bucket_url=temp_data_dir),
            dataset_name="contracts",
        )

        resource = resolve_contracts_resource(
            tickers=["AAPL"],
            cache_path=temp_cache,
            connection_config=mock_connection_config,
        )

        load_info = pipeline.run(resource, loader_file_format="parquet")

        # Check schema
        conn = duckdb.connect()
        parquet_path = Path(temp_data_dir) / "contracts" / "contract_descriptions"
        df = conn.execute(f"SELECT * FROM '{parquet_path}/*.parquet'").df()

        expected_columns = {
            "symbol",
            "conid",
            "local_symbol",
            "sec_type",
            "exchange",
            "primary_exchange",
            "currency",
            "trading_class",
            "long_name",
            "industry",
            "category",
            "subcategory",
        }

        assert set(df.columns) >= expected_columns

    def test_runtime_lifecycle(
        self,
        temp_data_dir,
        temp_cache,
        mock_connection_config,
        mock_runtime,
        mock_contract_resolver,
    ):
        """Verify IBRuntime is properly started and stopped."""
        pipeline = dlt.pipeline(
            pipeline_name="test_runtime_lifecycle",
            destination=dlt.destinations.filesystem(bucket_url=temp_data_dir),
            dataset_name="contracts",
        )

        resource = resolve_contracts_resource(
            tickers=["AAPL"],
            cache_path=temp_cache,
            connection_config=mock_connection_config,
        )

        load_info = pipeline.run(resource, loader_file_format="parquet")

        # Verify start was called before stop
        assert mock_runtime.start.called
        assert mock_runtime.stop.called

        # Verify start was called before stop (check call order)
        call_order = [call[0] for call in mock_runtime.method_calls]
        start_index = call_order.index("start")
        stop_index = call_order.index("stop")
        assert start_index < stop_index
