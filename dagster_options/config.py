"""Configuration dataclasses for the options pipeline."""

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import List, Optional
from pathlib import Path


@dataclass
class TickerSourceConfig:
    """Configuration for ticker list source."""

    # Source type: "file" or "database"
    source_type: str = "file"

    # For file source
    file_path: Optional[str] = "dagster_options/example_tickers.txt"

    # For database source (future enhancement)
    db_connection_string: Optional[str] = None
    db_query: Optional[str] = None


@dataclass
class StockDataConfig:
    """Configuration for stock historical data fetching."""

    # Lookback period for historical data
    lookback_days: int = 30

    # Bar size
    bar_size: str = "1 day"

    # What to show
    what_to_show: str = "TRADES"

    # Use regular trading hours only
    use_rth: bool = True

    # Exchange
    exchange: str = "SMART"

    # Currency
    currency: str = "USD"


@dataclass
class OptionChainConfig:
    """Configuration for option chain snapshots."""

    # Minimum days to expiration
    min_dte: int = 7

    # Maximum days to expiration
    max_dte: int = 365

    # Use today's date for snapshot (None = use today)
    snapshot_date: Optional[date] = None


@dataclass
class DeltaSelectionConfig:
    """Configuration for delta-based option selection."""

    # Target delta values for selection
    # For calls: [0.25, 0.50, 0.75] means 25Δ, 50Δ (ATM), 75Δ
    # For puts: will use negative values [-0.25, -0.50, -0.75]
    target_deltas: List[float] = field(default_factory=lambda: [0.25, 0.50, 0.75])

    # Tolerance for delta matching
    delta_tolerance: float = 0.05

    # Risk-free rate for Black-Scholes (annualized)
    risk_free_rate: float = 0.05

    # Implied volatility estimate for Black-Scholes (annualized)
    implied_volatility: float = 0.30

    # Include calls
    include_calls: bool = True

    # Include puts
    include_puts: bool = True


@dataclass
class OptionDataConfig:
    """Configuration for option historical data fetching."""

    # Lookback period for option bars
    lookback_days: int = 7

    # Bar size
    bar_size: str = "1 hour"

    # What to show
    what_to_show: str = "TRADES"

    # Use regular trading hours only
    use_rth: bool = True


@dataclass
class OptionsPipelineConfig:
    """Master configuration for the entire options pipeline."""

    # Ticker source configuration
    ticker_source: TickerSourceConfig = field(default_factory=TickerSourceConfig)

    # Stock data configuration
    stock_config: StockDataConfig = field(default_factory=StockDataConfig)

    # Option chain configuration
    chain_config: OptionChainConfig = field(default_factory=OptionChainConfig)

    # Delta selection configuration
    delta_config: DeltaSelectionConfig = field(default_factory=DeltaSelectionConfig)

    # Option data configuration
    option_config: OptionDataConfig = field(default_factory=OptionDataConfig)

    # Database path for DLT destination
    database_path: str = ".dlt-ibapi/data"

    # Contract cache path
    cache_path: str = ".dlt-ibapi/cache"

    # Dataset name for stocks
    stock_dataset: str = "stocks"

    # Dataset name for options
    option_dataset: str = "options"

    # Dataset name for option chain snapshots
    chain_dataset: str = "option_chains"

    # Enable all three selection strategies
    enable_closest_match: bool = True
    enable_calculated_delta: bool = True
    enable_ib_greeks: bool = True

    def get_stock_start_date(self) -> date:
        """Calculate stock data start date."""
        return date.today() - timedelta(days=self.stock_config.lookback_days)

    def get_stock_end_date(self) -> date:
        """Get stock data end date (today)."""
        return date.today()

    def get_option_start_date(self) -> date:
        """Calculate option data start date."""
        return date.today() - timedelta(days=self.option_config.lookback_days)

    def get_option_end_date(self) -> date:
        """Get option data end date (today)."""
        return date.today()

    def get_snapshot_date(self) -> date:
        """Get option chain snapshot date."""
        return self.chain_config.snapshot_date or date.today()


def get_default_config() -> OptionsPipelineConfig:
    """Get default pipeline configuration."""
    return OptionsPipelineConfig()


def load_config_from_file(config_path: str) -> OptionsPipelineConfig:
    """
    Load pipeline configuration from YAML file.

    Args:
        config_path: Path to YAML configuration file

    Returns:
        OptionsPipelineConfig instance

    Note:
        This is a placeholder for future YAML-based configuration.
        Currently returns default config.
    """
    # Future: implement YAML loading
    # For now, return default config
    return get_default_config()
