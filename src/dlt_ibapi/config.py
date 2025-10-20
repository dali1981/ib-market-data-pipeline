"""Configuration models for dlt-ibapi connector."""

from typing import Optional
from pydantic import BaseModel, Field


class IBConnectionConfig(BaseModel):
    """Configuration for IB Gateway/TWS connection."""

    host: str = Field(default="127.0.0.1", description="IB Gateway/TWS host")
    port: int = Field(default=7497, description="IB Gateway/TWS port")
    client_id: int = Field(default=1, description="Client ID for connection")
    ready_timeout: float = Field(default=10.0, description="Timeout for connection ready")


class IBHistoricalConfig(BaseModel):
    """Configuration for historical data requests."""

    duration: str = Field(default="1 D", description="Duration string (e.g., '1 D', '1 W')")
    bar_size: str = Field(default="1 min", description="Bar size (e.g., '1 min', '1 hour')")
    what_to_show: str = Field(default="TRADES", description="Data type to show")
    use_rth: bool = Field(default=True, description="Use regular trading hours only")
    timeout: float = Field(default=20.0, description="Request timeout in seconds")


class IBMarketDataConfig(BaseModel):
    """Configuration for market data snapshots."""

    generic_ticks: str = Field(default="", description="Generic tick types to request")
    snapshot: bool = Field(default=True, description="Request snapshot only")
    timeout: float = Field(default=10.0, description="Request timeout in seconds")


class IBOptionChainConfig(BaseModel):
    """Configuration for option chain requests."""

    exchange: str = Field(default="", description="Exchange for option params")
    timeout: float = Field(default=10.0, description="Request timeout in seconds")
