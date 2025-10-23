"""
Configuration loader for dlt-ibapi.

Implements a hierarchical config loading system:
1. User project config (.dlt-ibapi/ib_gateway.yaml in project root)
2. Environment variables (IB_HOST, IB_PORT, IB_CLIENT_ID, etc.)
3. Default config (shipped with package)

Usage:
    from dlt_ibapi.config_loader import load_config, get_connection_config

    # Load full config
    config = load_config()

    # Get connection config as Pydantic model
    conn_config = get_connection_config()
"""

import os
from pathlib import Path
from typing import Optional, Dict, Any

from omegaconf import OmegaConf, DictConfig
from .config import (
    IBConnectionConfig,
    IBHistoricalConfig,
    IBMarketDataConfig,
    IBOptionChainConfig,
)


def get_package_config_path() -> Path:
    """Get path to default config shipped with package."""
    return Path(__file__).parent / "config_files" / "ib_gateway.yaml"


def get_user_config_path() -> Optional[Path]:
    """
    Get path to user config file in their project.

    Searches for .dlt-ibapi/config/ib_gateway.yaml starting from current directory
    and walking up to find project root.

    Returns:
        Path to user config if found, None otherwise
    """
    current = Path.cwd()

    # Search current directory and parents
    for parent in [current] + list(current.parents):
        config_path = parent / ".dlt-ibapi" / "config" / "ib_gateway.yaml"
        if config_path.exists():
            return config_path

    return None


def load_config(user_config_path: Optional[Path] = None) -> DictConfig:
    """
    Load configuration with hierarchy:
    1. User project config (.dlt-ibapi/config/ib_gateway.yaml)
    2. Environment variables
    3. Default package config

    Args:
        user_config_path: Optional explicit path to user config file.
                         If not provided, will search project directory tree.

    Returns:
        OmegaConf DictConfig with merged configuration
    """
    # Load default config from package
    default_config_path = get_package_config_path()
    default_config = OmegaConf.load(default_config_path)

    # Try to find/load user config
    if user_config_path is None:
        user_config_path = get_user_config_path()

    user_config = None
    if user_config_path and user_config_path.exists():
        user_config = OmegaConf.load(user_config_path)

    # Load environment variables
    env_config = OmegaConf.create({
        "connection": {
            "host": os.getenv("IB_HOST"),
            "port": int(os.getenv("IB_PORT")) if os.getenv("IB_PORT") else None,
            "client_id": int(os.getenv("IB_CLIENT_ID")) if os.getenv("IB_CLIENT_ID") else None,
            "ready_timeout": float(os.getenv("IB_READY_TIMEOUT")) if os.getenv("IB_READY_TIMEOUT") else None,
        },
        "historical": {
            "duration": os.getenv("IB_HIST_DURATION"),
            "bar_size": os.getenv("IB_HIST_BAR_SIZE"),
            "what_to_show": os.getenv("IB_HIST_WHAT_TO_SHOW"),
            "use_rth": os.getenv("IB_HIST_USE_RTH", "").lower() == "true" if os.getenv("IB_HIST_USE_RTH") else None,
            "timeout": float(os.getenv("IB_HIST_TIMEOUT")) if os.getenv("IB_HIST_TIMEOUT") else None,
        },
        "market_data": {
            "generic_ticks": os.getenv("IB_MARKET_GENERIC_TICKS"),
            "snapshot": os.getenv("IB_MARKET_SNAPSHOT", "").lower() == "true" if os.getenv("IB_MARKET_SNAPSHOT") else None,
            "timeout": float(os.getenv("IB_MARKET_TIMEOUT")) if os.getenv("IB_MARKET_TIMEOUT") else None,
        },
        "option_chain": {
            "exchange": os.getenv("IB_OPTION_EXCHANGE"),
            "timeout": float(os.getenv("IB_OPTION_TIMEOUT")) if os.getenv("IB_OPTION_TIMEOUT") else None,
        },
    })

    # Merge configs with priority: env > user > default
    configs = [default_config]
    if user_config:
        configs.append(user_config)

    # Only add env_config if it has non-None values
    env_config_cleaned = _remove_none_values(OmegaConf.to_container(env_config))
    if env_config_cleaned:
        configs.append(OmegaConf.create(env_config_cleaned))

    merged_config = OmegaConf.merge(*configs)

    return merged_config


def _remove_none_values(d: Dict[str, Any]) -> Dict[str, Any]:
    """Recursively remove keys with None values."""
    if not isinstance(d, dict):
        return d

    return {
        k: _remove_none_values(v) if isinstance(v, dict) else v
        for k, v in d.items()
        if v is not None
    }


def get_connection_config(
    user_config_path: Optional[Path] = None,
    override: Optional[IBConnectionConfig] = None,
) -> IBConnectionConfig:
    """
    Get IB connection configuration.

    Args:
        user_config_path: Optional path to user config file
        override: Optional IBConnectionConfig to use instead of loading from files

    Returns:
        IBConnectionConfig instance
    """
    if override:
        return override

    config = load_config(user_config_path)
    return IBConnectionConfig(**config.connection)


def get_historical_config(
    user_config_path: Optional[Path] = None,
    override: Optional[IBHistoricalConfig] = None,
) -> IBHistoricalConfig:
    """
    Get historical data configuration.

    Args:
        user_config_path: Optional path to user config file
        override: Optional IBHistoricalConfig to use instead of loading from files

    Returns:
        IBHistoricalConfig instance
    """
    if override:
        return override

    config = load_config(user_config_path)
    return IBHistoricalConfig(**config.historical)


def get_market_data_config(
    user_config_path: Optional[Path] = None,
    override: Optional[IBMarketDataConfig] = None,
) -> IBMarketDataConfig:
    """
    Get market data configuration.

    Args:
        user_config_path: Optional path to user config file
        override: Optional IBMarketDataConfig to use instead of loading from files

    Returns:
        IBMarketDataConfig instance
    """
    if override:
        return override

    config = load_config(user_config_path)
    return IBMarketDataConfig(**config.market_data)


def get_option_chain_config(
    user_config_path: Optional[Path] = None,
    override: Optional[IBOptionChainConfig] = None,
) -> IBOptionChainConfig:
    """
    Get option chain configuration.

    Args:
        user_config_path: Optional path to user config file
        override: Optional IBOptionChainConfig to use instead of loading from files

    Returns:
        IBOptionChainConfig instance
    """
    if override:
        return override

    config = load_config(user_config_path)
    return IBOptionChainConfig(**config.option_chain)


def create_user_config_template(target_dir: Optional[Path] = None) -> Path:
    """
    Create a user config template in the specified directory.

    Args:
        target_dir: Directory to create .dlt-ibapi/config/ in. Defaults to current directory.

    Returns:
        Path to created config file
    """
    if target_dir is None:
        target_dir = Path.cwd()

    config_dir = target_dir / ".dlt-ibapi" / "config"
    config_dir.mkdir(parents=True, exist_ok=True)

    config_file = config_dir / "ib_gateway.yaml"

    # Copy default config as template
    default_config_path = get_package_config_path()
    config_file.write_text(default_config_path.read_text())

    return config_file
