"""
Shared pytest fixtures for testing DLT IB API library.

This module provides reusable fixtures for creating test data, mocking IB API components,
and managing temporary directories for Parquet storage.
"""

import pytest
import tempfile
from pathlib import Path
from datetime import date, datetime, timezone
from unittest.mock import Mock, patch, MagicMock
import dlt
import pandas as pd

from dlt_ibapi.config import IBConnectionConfig


# ===========================
# Directory and Path Fixtures
# ===========================

@pytest.fixture
def temp_data_dir():
    """
    Provides a temporary directory for test Parquet data.

    Yields:
        str: Path to temporary data directory
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        yield str(Path(tmpdir))


@pytest.fixture
def temp_cache_dir():
    """
    Provides a temporary directory for IB API cache.

    Yields:
        str: Path to temporary cache directory
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        yield str(tmpdir)


# ===========================
# IB API Mock Fixtures
# ===========================

@pytest.fixture
def mock_connection_config():
    """
    Provides a mock IB connection configuration.

    Returns:
        IBConnectionConfig: Mock connection config for IB Gateway
    """
    return IBConnectionConfig(
        host="127.0.0.1",
        port=4002,
        client_id=999,
        ready_timeout=5.0,
    )


@pytest.fixture
def mock_runtime():
    """
    Mocks the IBRuntime class.

    Yields:
        MagicMock: Mocked IBRuntime instance
    """
    with patch("dlt_ibapi.backfill.resources.IBRuntime") as mock_runtime_class:
        runtime_instance = MagicMock()
        mock_runtime_class.return_value = runtime_instance
        yield runtime_instance


@pytest.fixture
def mock_contract_resolver():
    """
    Mocks the ContractResolver with sample contract data.

    Provides mock responses for AAPL and MSFT symbols.

    Yields:
        MagicMock: Mocked ContractResolver instance
    """
    with patch("dlt_ibapi.backfill.resources.ContractResolver") as mock_resolver_class:
        resolver_instance = MagicMock()

        def mock_resolve(symbol, **kwargs):
            """Mock resolve_symbol method."""
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
            else:
                return None

        resolver_instance.resolve_symbol = Mock(side_effect=mock_resolve)
        mock_resolver_class.return_value = resolver_instance
        yield resolver_instance


# ===========================
# Test Data Creation Helpers
# ===========================

def create_stock_parquet_data(
    data_dir: str,
    symbol: str = "AAPL",
    bar_date: date = date(2024, 1, 15),
    close_price: float = 185.0,
    dataset_name: str = "stocks",
) -> None:
    """
    Creates test stock price data in Parquet format.

    Args:
        data_dir: Directory to write Parquet files
        symbol: Stock symbol
        bar_date: Date of the price bar
        close_price: Closing price
        dataset_name: DLT dataset name
    """
    stock_data = [
        {
            "symbol": symbol,
            "bar_size": "1 day",
            "time": datetime(bar_date.year, bar_date.month, bar_date.day, 16, 0),
            "date": bar_date.isoformat(),
            "open": close_price - 1.0,
            "high": close_price + 1.0,
            "low": close_price - 2.0,
            "close": close_price,
            "volume": 1000000,
            "wap": close_price - 0.5,
            "bar_count": 100,
        },
    ]

    pipeline = dlt.pipeline(
        pipeline_name=f"test_stocks_{symbol}",
        destination=dlt.destinations.filesystem(bucket_url=data_dir),
        dataset_name=dataset_name,
    )

    @dlt.resource(
        name="historical_bars",
        write_disposition="append",
        primary_key=["symbol", "bar_size", "time"],
    )
    def stock_bars():
        yield from stock_data

    pipeline.run(stock_bars(), loader_file_format="parquet")


def create_selected_contracts_parquet_data(
    data_dir: str,
    contracts: list = None,
    dataset_name: str = "selected_contracts",
) -> None:
    """
    Creates test selected contracts data in Parquet format.

    Args:
        data_dir: Directory to write Parquet files
        contracts: List of contract dicts, or None for default AAPL contracts
        dataset_name: DLT dataset name
    """
    if contracts is None:
        # Default test data
        contracts = [
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
        ]

    pipeline = dlt.pipeline(
        pipeline_name="test_selected_contracts",
        destination=dlt.destinations.filesystem(bucket_url=data_dir),
        dataset_name=dataset_name,
    )

    @dlt.resource(
        name="selected_option_contracts",
        write_disposition="merge",
        primary_key=["underlying", "expiry", "strike", "right", "strategy"],
        columns={
            "snapshot_date": {"partition": True},
            "underlying": {"partition": True},
        }
    )
    def contracts_resource():
        yield from contracts

    pipeline.run(contracts_resource(), loader_file_format="parquet")


# ===========================
# Fixture Factories
# ===========================

@pytest.fixture
def create_stock_data():
    """
    Factory fixture for creating stock Parquet data in tests.

    Returns:
        Callable: Function that creates stock data
    """
    return create_stock_parquet_data


@pytest.fixture
def create_selected_contracts_data():
    """
    Factory fixture for creating selected contracts Parquet data in tests.

    Returns:
        Callable: Function that creates selected contracts data
    """
    return create_selected_contracts_parquet_data
