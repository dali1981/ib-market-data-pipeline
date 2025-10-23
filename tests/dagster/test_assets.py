"""
Integration tests for refactored Dagster assets.

Tests that assets correctly use library DLT resources and handle data flow through Parquet.
"""

import pytest
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock, Mock
from datetime import date, datetime

from dagster import build_op_context, materialize_to_memory
from dagster_options.assets import (
    ticker_contracts,
    stock_historical_data,
    option_chain_snapshots,
    select_option_contracts,
    option_historical_data,
)


class TestTickerContractsAsset:
    """Tests for ticker_contracts asset."""

    @pytest.fixture
    def temp_config(self):
        """Mock configuration."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config = MagicMock()
            config.ticker_source = "inline"
            config.cache_path = tmpdir
            config.database_path = tmpdir
            yield config

    @patch("dagster_options.assets.get_default_config")
    @patch("dagster_options.assets.load_tickers")
    @patch("dagster_options.assets.get_connection_config")
    @patch("dagster_options.assets.dlt.pipeline")
    @patch("dlt_ibapi.backfill.resources.IBRuntime")
    @patch("dlt_ibapi.backfill.resources.ContractResolver")
    def test_ticker_contracts_uses_resolve_resource(
        self,
        mock_resolver,
        mock_runtime,
        mock_pipeline,
        mock_get_conn_config,
        mock_load_tickers,
        mock_get_config,
        temp_config,
    ):
        """Test that ticker_contracts asset uses resolve_contracts_resource."""
        # Setup mocks
        mock_get_config.return_value = temp_config
        mock_load_tickers.return_value = ["AAPL", "MSFT"]
        mock_get_conn_config.return_value = MagicMock()

        # Mock pipeline
        pipeline_instance = MagicMock()
        mock_pipeline.return_value = pipeline_instance
        pipeline_instance.run.return_value = MagicMock()

        # Mock resolver
        resolver_instance = MagicMock()
        mock_resolver.return_value = resolver_instance
        resolver_instance.resolve_symbol.return_value = {
            "conid": 265598,
            "symbol": "AAPL",
        }

        # Mock runtime
        runtime_instance = MagicMock()
        mock_runtime.return_value = runtime_instance

        # Execute asset
        context = build_op_context()
        result = ticker_contracts(context)

        # Verify tickers were loaded
        mock_load_tickers.assert_called_once()

        # Verify pipeline was created and run
        mock_pipeline.assert_called_once()
        pipeline_instance.run.assert_called_once()

        # Verify result structure
        assert "tickers_resolved" in result.value
        assert "num_tickers" in result.value
        assert result.value["num_tickers"] == 2


class TestStockHistoricalDataAsset:
    """Tests for stock_historical_data asset."""

    @pytest.fixture
    def upstream_contracts(self):
        """Mock upstream ticker_contracts output."""
        return {"tickers_resolved": ["AAPL", "MSFT"], "num_tickers": 2}

    @pytest.fixture
    def temp_config(self):
        """Mock configuration."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config = MagicMock()
            config.stock_dataset = "stocks"
            config.database_path = tmpdir
            config.cache_path = tmpdir
            config.get_stock_start_date.return_value = date(2024, 1, 1)
            config.get_stock_end_date.return_value = date(2024, 1, 15)
            config.stock_config = MagicMock(
                bar_size="1 day",
                what_to_show="TRADES",
                use_rth=True,
            )
            yield config

    @patch("dagster_options.assets.get_default_config")
    @patch("dagster_options.assets.get_connection_config")
    @patch("dagster_options.assets.dlt.pipeline")
    @patch("dlt_ibapi.backfill.resources.IBRuntime")
    @patch("dlt_ibapi.backfill.resources.ContractResolver")
    @patch("dlt_ibapi.backfill.resources.HistoricalService")
    def test_stock_historical_data_reads_upstream(
        self,
        mock_hist_service,
        mock_resolver,
        mock_runtime,
        mock_pipeline,
        mock_get_conn_config,
        mock_get_config,
        temp_config,
        upstream_contracts,
    ):
        """Test that stock_historical_data reads from upstream correctly."""
        # Setup mocks
        mock_get_config.return_value = temp_config
        mock_get_conn_config.return_value = MagicMock()

        # Mock pipeline
        pipeline_instance = MagicMock()
        mock_pipeline.return_value = pipeline_instance
        pipeline_instance.run.return_value = MagicMock()

        # Mock services
        mock_resolver.return_value = MagicMock()
        mock_runtime.return_value = MagicMock()
        mock_hist_service.return_value = MagicMock()

        # Execute asset
        context = build_op_context()
        result = stock_historical_data(context, upstream_contracts)

        # Verify it processed the tickers from upstream
        assert "symbols_processed" in result.value
        assert len(result.value["symbols_processed"]) == 2


class TestOptionChainSnapshotsAsset:
    """Tests for option_chain_snapshots asset."""

    @pytest.fixture
    def upstream_contracts(self):
        """Mock upstream ticker_contracts output."""
        return {"tickers_resolved": ["AAPL"], "num_tickers": 1}

    @pytest.fixture
    def temp_config(self):
        """Mock configuration."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config = MagicMock()
            config.chain_dataset = "option_chains"
            config.database_path = tmpdir
            config.cache_path = tmpdir
            config.get_snapshot_date.return_value = date(2024, 1, 15)
            config.chain_config = MagicMock(min_dte=7, max_dte=365)
            yield config

    @patch("dagster_options.assets.get_default_config")
    @patch("dagster_options.assets.get_connection_config")
    @patch("dagster_options.assets.dlt.pipeline")
    @patch("dlt_ibapi.backfill.resources.IBRuntime")
    @patch("dlt_ibapi.backfill.resources.SecDefService")
    def test_option_chain_snapshots_uses_resource(
        self,
        mock_secdef_service,
        mock_runtime,
        mock_pipeline,
        mock_get_conn_config,
        mock_get_config,
        temp_config,
        upstream_contracts,
    ):
        """Test that option_chain_snapshots uses snapshot_option_chain resource."""
        # Setup mocks
        mock_get_config.return_value = temp_config
        mock_get_conn_config.return_value = MagicMock()

        # Mock pipeline
        pipeline_instance = MagicMock()
        mock_pipeline.return_value = pipeline_instance
        pipeline_instance.run.return_value = MagicMock()

        # Mock services
        mock_runtime.return_value = MagicMock()
        mock_secdef_service.return_value = MagicMock()

        # Execute asset
        context = build_op_context()
        result = option_chain_snapshots(context, upstream_contracts)

        # Verify result
        assert "chains_captured" in result.value
        assert "snapshot_date" in result.value


class TestSelectOptionContractsAsset:
    """Tests for select_option_contracts asset."""

    @pytest.fixture
    def upstream_data(self):
        """Mock upstream asset outputs."""
        return {
            "ticker_contracts": {"tickers_resolved": ["AAPL"], "num_tickers": 1},
            "stock_historical_data": {"symbols_processed": ["AAPL"]},
            "option_chain_snapshots": {
                "chains_captured": ["AAPL"],
                "snapshot_date": date(2024, 1, 15),
            },
        }

    @pytest.fixture
    def temp_config(self):
        """Mock configuration."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config = MagicMock()
            config.stock_dataset = "stocks"
            config.chain_dataset = "option_chains"
            config.database_path = tmpdir
            config.cache_path = tmpdir
            config.get_snapshot_date.return_value = date(2024, 1, 15)
            config.enable_closest_match = True
            config.enable_calculated_delta = True
            config.delta_config = MagicMock(target_deltas=[0.30, 0.50, 0.70])
            yield config

    @patch("dagster_options.assets.get_default_config")
    @patch("dagster_options.assets.get_connection_config")
    @patch("dagster_options.assets.dlt.pipeline")
    @patch("dlt_ibapi.backfill.resources.EquityBarsReader")
    @patch("dlt_ibapi.backfill.resources.OptionChainSnapshotReader")
    @patch("dlt_ibapi.backfill.resources.IBRuntime")
    @patch("dlt_ibapi.backfill.resources.ContractDetailsService")
    def test_select_option_contracts_uses_resource(
        self,
        mock_details_service,
        mock_runtime,
        mock_chain_reader,
        mock_stock_reader,
        mock_pipeline,
        mock_get_conn_config,
        mock_get_config,
        temp_config,
        upstream_data,
    ):
        """Test that select_option_contracts uses select_option_contracts_resource."""
        # Setup mocks
        mock_get_config.return_value = temp_config
        mock_get_conn_config.return_value = MagicMock()

        # Mock pipeline
        pipeline_instance = MagicMock()
        mock_pipeline.return_value = pipeline_instance
        pipeline_instance.run.return_value = MagicMock()

        # Mock readers (return empty to skip actual selection)
        stock_reader_instance = MagicMock()
        stock_reader_instance.get_bars.return_value = MagicMock(empty=True)
        mock_stock_reader.return_value = stock_reader_instance

        chain_reader_instance = MagicMock()
        chain_reader_instance.get_chain_for_date.return_value = MagicMock(empty=True)
        mock_chain_reader.return_value = chain_reader_instance

        # Mock services
        mock_runtime.return_value = MagicMock()
        mock_details_service.return_value = MagicMock()

        # Execute asset
        context = build_op_context()
        result = select_option_contracts(
            context,
            upstream_data["ticker_contracts"],
            upstream_data["stock_historical_data"],
            upstream_data["option_chain_snapshots"],
        )

        # Verify result
        assert "contracts_selected" in result.value
        assert "symbols_processed" in result.value


class TestOptionHistoricalDataAsset:
    """Tests for option_historical_data asset."""

    @pytest.fixture
    def upstream_select_contracts(self):
        """Mock upstream select_option_contracts output."""
        return {
            "contracts_selected": True,
            "symbols_processed": ["AAPL"],
            "snapshot_date": date(2024, 1, 15),
        }

    @pytest.fixture
    def temp_config(self):
        """Mock configuration."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config = MagicMock()
            config.option_dataset = "options"
            config.stock_dataset = "stocks"
            config.database_path = tmpdir
            config.cache_path = tmpdir
            config.get_option_start_date.return_value = date(2024, 1, 1)
            config.get_option_end_date.return_value = date(2024, 1, 15)
            config.get_stock_end_date.return_value = date(2024, 1, 15)
            config.stock_config = MagicMock(bar_size="1 day")
            config.option_config = MagicMock(
                bar_size="1 day",
                what_to_show="TRADES",
                use_rth=True,
                lookback_days=7,
            )
            yield config

    @patch("dagster_options.assets.SelectedContractsReader")
    @patch("dagster_options.assets.EquityBarsReader")
    @patch("dagster_options.assets.get_default_config")
    @patch("dagster_options.assets.get_connection_config")
    @patch("dagster_options.assets.dlt.pipeline")
    @patch("dlt_ibapi.backfill.resources.IBRuntime")
    def test_option_historical_data_reads_from_parquet(
        self,
        mock_runtime,
        mock_pipeline,
        mock_get_conn_config,
        mock_get_config,
        mock_stock_reader,
        mock_contracts_reader,
        temp_config,
        upstream_select_contracts,
    ):
        """Test that option_historical_data reads from SelectedContractsReader."""
        # Setup mocks
        mock_get_config.return_value = temp_config
        mock_get_conn_config.return_value = MagicMock()

        # Mock contracts reader to return empty (skip processing)
        contracts_reader_instance = MagicMock()
        import pandas as pd

        contracts_reader_instance.get_all_contracts.return_value = pd.DataFrame()
        mock_contracts_reader.return_value = contracts_reader_instance

        # Mock pipeline
        pipeline_instance = MagicMock()
        mock_pipeline.return_value = pipeline_instance

        # Execute asset
        context = build_op_context()
        result = option_historical_data(context, upstream_select_contracts)

        # Verify SelectedContractsReader was instantiated and used
        mock_contracts_reader.assert_called_once()
        contracts_reader_instance.get_all_contracts.assert_called_once()

        # Verify result structure
        assert "contracts_processed" in result.value
