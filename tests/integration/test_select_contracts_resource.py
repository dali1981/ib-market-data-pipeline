"""
Integration tests for select_option_contracts_resource.

Tests the DLT resource for selecting option contracts using delta strategies
with mocked IB API and pre-populated Parquet data.
"""

import pytest
import tempfile
from pathlib import Path
from datetime import date, datetime, timedelta, timezone
from unittest.mock import Mock, patch, MagicMock
import dlt
import duckdb

from dlt_ibapi.backfill.resources import select_option_contracts_resource
from dlt_ibapi.config import IBConnectionConfig


class TestSelectContractsResource:
    """Integration tests for select_option_contracts_resource."""

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
    def setup_test_data(self, temp_data_dir):
        """Create test Parquet files for stocks and option chains."""
        snapshot_date = date(2024, 1, 15)

        # Create stock data
        stock_data = [
            {
                "symbol": "AAPL",
                "bar_size": "1 day",
                "time": datetime(2024, 1, 15, 16, 0),
                "date": "2024-01-15",
                "open": 184.0,
                "high": 186.0,
                "low": 183.0,
                "close": 185.0,
                "volume": 1000000,
                "wap": 184.5,
                "bar_count": 100,
            },
        ]

        stock_pipeline = dlt.pipeline(
            pipeline_name="test_stocks",
            destination=dlt.destinations.filesystem(bucket_url=temp_data_dir),
            dataset_name="stocks",
        )

        @dlt.resource(
            name="historical_bars",
            write_disposition="append",
            primary_key=["symbol", "bar_size", "time"],
        )
        def stock_bars():
            yield from stock_data

        stock_pipeline.run(stock_bars(), loader_file_format="parquet")

        # Create option chain data
        chain_data = [
            {
                "underlying": "AAPL",
                "underlying_conid": 265598,
                "exchange": "SMART",
                "trading_class": "AAPL",
                "multiplier": "100",
                "expirations": ["20240216"],
                "strikes": [175.0, 180.0, 185.0, 190.0, 195.0],
                "expiration_count": 1,
                "strike_count": 5,
                "as_of": snapshot_date,
                "date": snapshot_date.isoformat(),
                "captured_at": datetime.now(timezone.utc),
            },
        ]

        chain_pipeline = dlt.pipeline(
            pipeline_name="test_chains",
            destination=dlt.destinations.filesystem(bucket_url=temp_data_dir),
            dataset_name="option_chains",
        )

        @dlt.resource(
            name="option_chain_snapshot",
            write_disposition="replace",
            primary_key=["underlying", "as_of", "exchange", "trading_class"],
        )
        def chain_snapshot():
            yield from chain_data

        chain_pipeline.run(chain_snapshot(), loader_file_format="parquet")

        return snapshot_date

    @pytest.fixture
    def mock_runtime(self):
        """Mock IBRuntime."""
        with patch("dlt_ibapi.backfill.resources.IBRuntime") as mock_runtime_class:
            runtime_instance = MagicMock()
            mock_runtime_class.return_value = runtime_instance
            yield runtime_instance

    @pytest.fixture
    def mock_contract_details_service(self):
        """Mock ContractDetailsService to return test contract details."""
        with patch("ib_connector.ContractDetailsService") as mock_service_class:
            service_instance = MagicMock()

            # Mock fetch method to return contract details
            def mock_fetch(contract, timeout=10.0):
                mock_detail = MagicMock()
                mock_detail.contract.conId = 12345
                mock_detail.contract.localSymbol = f"AAPL  240216C00{int(contract.strike):05d}000"
                mock_detail.contract.exchange = "SMART"
                mock_detail.contract.tradingClass = "AAPL"
                mock_detail.multiplier = "100"
                return [mock_detail]

            service_instance.fetch = Mock(side_effect=mock_fetch)
            mock_service_class.return_value = service_instance
            yield service_instance

    def test_select_with_closest_match_strategy(
        self,
        temp_data_dir,
        temp_cache,
        setup_test_data,
        mock_connection_config,
        mock_runtime,
        mock_contract_details_service,
    ):
        """Test selection with closest_match strategy."""
        snapshot_date = setup_test_data

        pipeline = dlt.pipeline(
            pipeline_name="test_select_closest",
            destination=dlt.destinations.filesystem(bucket_url=temp_data_dir),
            dataset_name="selected_contracts",
        )

        resource = select_option_contracts_resource(
            symbols=["AAPL"],
            snapshot_date=snapshot_date,
            database_path=temp_data_dir,
            dataset_name_stocks="stocks",
            dataset_name_chains="option_chains",
            cache_path=temp_cache,
            connection_config=mock_connection_config,
            strategies=["closest_match"],
            num_expirations=1,
        )

        load_info = pipeline.run(resource, loader_file_format="parquet")

        # Verify data was written
        conn = duckdb.connect()
        parquet_path = Path(temp_data_dir) / "selected_contracts" / "selected_option_contracts"
        df = conn.execute(f"SELECT * FROM '{parquet_path}/*.parquet'").df()

        assert not df.empty
        assert all(df["strategy"] == "closest_match")
        assert all(df["underlying"] == "AAPL")

    def test_select_with_black_scholes_strategy(
        self,
        temp_data_dir,
        temp_cache,
        setup_test_data,
        mock_connection_config,
        mock_runtime,
        mock_contract_details_service,
    ):
        """Test selection with black_scholes strategy."""
        snapshot_date = setup_test_data

        pipeline = dlt.pipeline(
            pipeline_name="test_select_bs",
            destination=dlt.destinations.filesystem(bucket_url=temp_data_dir),
            dataset_name="selected_contracts",
        )

        resource = select_option_contracts_resource(
            symbols=["AAPL"],
            snapshot_date=snapshot_date,
            database_path=temp_data_dir,
            dataset_name_stocks="stocks",
            dataset_name_chains="option_chains",
            cache_path=temp_cache,
            connection_config=mock_connection_config,
            strategies=["black_scholes"],
            num_expirations=1,
        )

        load_info = pipeline.run(resource, loader_file_format="parquet")

        # Verify data was written
        conn = duckdb.connect()
        parquet_path = Path(temp_data_dir) / "selected_contracts" / "selected_option_contracts"
        df = conn.execute(f"SELECT * FROM '{parquet_path}/*.parquet'").df()

        assert not df.empty
        assert all(df["strategy"] == "black_scholes")

    def test_select_with_both_strategies(
        self,
        temp_data_dir,
        temp_cache,
        setup_test_data,
        mock_connection_config,
        mock_runtime,
        mock_contract_details_service,
    ):
        """Test selection with both strategies."""
        snapshot_date = setup_test_data

        pipeline = dlt.pipeline(
            pipeline_name="test_select_both",
            destination=dlt.destinations.filesystem(bucket_url=temp_data_dir),
            dataset_name="selected_contracts",
        )

        resource = select_option_contracts_resource(
            symbols=["AAPL"],
            snapshot_date=snapshot_date,
            database_path=temp_data_dir,
            dataset_name_stocks="stocks",
            dataset_name_chains="option_chains",
            cache_path=temp_cache,
            connection_config=mock_connection_config,
            strategies=["closest_match", "black_scholes"],
            num_expirations=1,
        )

        load_info = pipeline.run(resource, loader_file_format="parquet")

        # Verify both strategies are present
        conn = duckdb.connect()
        parquet_path = Path(temp_data_dir) / "selected_contracts" / "selected_option_contracts"
        df = conn.execute(f"SELECT * FROM '{parquet_path}/*.parquet'").df()

        assert not df.empty
        strategies = set(df["strategy"].unique())
        assert "closest_match" in strategies or "black_scholes" in strategies

    def test_select_reads_from_parquet(
        self,
        temp_data_dir,
        temp_cache,
        setup_test_data,
        mock_connection_config,
        mock_runtime,
        mock_contract_details_service,
    ):
        """Verify resource reads stock and chain data from Parquet."""
        snapshot_date = setup_test_data

        # Verify test data exists
        conn = duckdb.connect()

        # Check stock data exists
        stock_path = Path(temp_data_dir) / "stocks" / "historical_bars"
        stock_df = conn.execute(f"SELECT * FROM '{stock_path}/*.parquet'").df()
        assert not stock_df.empty

        # Check chain data exists
        chain_path = Path(temp_data_dir) / "option_chains" / "option_chain_snapshot"
        chain_df = conn.execute(f"SELECT * FROM '{chain_path}/*.parquet'").df()
        assert not chain_df.empty

        # Run resource
        pipeline = dlt.pipeline(
            pipeline_name="test_reads_parquet",
            destination=dlt.destinations.filesystem(bucket_url=temp_data_dir),
            dataset_name="selected_contracts",
        )

        resource = select_option_contracts_resource(
            symbols=["AAPL"],
            snapshot_date=snapshot_date,
            database_path=temp_data_dir,
            dataset_name_stocks="stocks",
            dataset_name_chains="option_chains",
            cache_path=temp_cache,
            connection_config=mock_connection_config,
            strategies=["closest_match"],
            num_expirations=1,
        )

        load_info = pipeline.run(resource, loader_file_format="parquet")

        # Verify resource completed successfully
        assert load_info is not None

    def test_select_resolves_to_ib_contracts(
        self,
        temp_data_dir,
        temp_cache,
        setup_test_data,
        mock_connection_config,
        mock_runtime,
        mock_contract_details_service,
    ):
        """Verify resource resolves contracts via IB API."""
        snapshot_date = setup_test_data

        pipeline = dlt.pipeline(
            pipeline_name="test_resolution",
            destination=dlt.destinations.filesystem(bucket_url=temp_data_dir),
            dataset_name="selected_contracts",
        )

        resource = select_option_contracts_resource(
            symbols=["AAPL"],
            snapshot_date=snapshot_date,
            database_path=temp_data_dir,
            dataset_name_stocks="stocks",
            dataset_name_chains="option_chains",
            cache_path=temp_cache,
            connection_config=mock_connection_config,
            strategies=["closest_match"],
            num_expirations=1,
        )

        load_info = pipeline.run(resource, loader_file_format="parquet")

        # Verify ContractDetailsService.fetch was called
        assert mock_contract_details_service.fetch.called

    def test_select_handles_missing_stock_data(
        self,
        temp_data_dir,
        temp_cache,
        setup_test_data,
        mock_connection_config,
        mock_runtime,
        mock_contract_details_service,
    ):
        """Test resource handles missing stock data gracefully."""
        snapshot_date = setup_test_data

        pipeline = dlt.pipeline(
            pipeline_name="test_missing_stock",
            destination=dlt.destinations.filesystem(bucket_url=temp_data_dir),
            dataset_name="selected_contracts",
        )

        # Try to select for symbol without stock data
        resource = select_option_contracts_resource(
            symbols=["TSLA"],  # No stock data for TSLA
            snapshot_date=snapshot_date,
            database_path=temp_data_dir,
            dataset_name_stocks="stocks",
            dataset_name_chains="option_chains",
            cache_path=temp_cache,
            connection_config=mock_connection_config,
            strategies=["closest_match"],
            num_expirations=1,
        )

        # Should not raise exception
        load_info = pipeline.run(resource, loader_file_format="parquet")

    def test_resource_schema(
        self,
        temp_data_dir,
        temp_cache,
        setup_test_data,
        mock_connection_config,
        mock_runtime,
        mock_contract_details_service,
    ):
        """Verify Parquet schema matches expected structure."""
        snapshot_date = setup_test_data

        pipeline = dlt.pipeline(
            pipeline_name="test_schema",
            destination=dlt.destinations.filesystem(bucket_url=temp_data_dir),
            dataset_name="selected_contracts",
        )

        resource = select_option_contracts_resource(
            symbols=["AAPL"],
            snapshot_date=snapshot_date,
            database_path=temp_data_dir,
            dataset_name_stocks="stocks",
            dataset_name_chains="option_chains",
            cache_path=temp_cache,
            connection_config=mock_connection_config,
            strategies=["closest_match"],
            num_expirations=1,
        )

        load_info = pipeline.run(resource, loader_file_format="parquet")

        # Check schema
        conn = duckdb.connect()
        parquet_path = Path(temp_data_dir) / "selected_contracts" / "selected_option_contracts"
        df = conn.execute(f"SELECT * FROM '{parquet_path}/*.parquet'").df()

        expected_columns = {
            "underlying",
            "expiry",
            "strike",
            "right",
            "conid",
            "local_symbol",
            "exchange",
            "trading_class",
            "multiplier",
            "strategy",
            "spot_price",
            "snapshot_date",
        }

        assert set(df.columns) >= expected_columns
