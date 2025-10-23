"""Ticker list input loaders."""

from typing import List
from pathlib import Path
import logging

from dagster_options.config import TickerSourceConfig

logger = logging.getLogger(__name__)


def load_tickers_from_file(file_path: str) -> List[str]:
    """
    Load ticker list from a text file.

    File format:
    - One ticker per line
    - Lines starting with # are comments
    - Empty lines are ignored
    - Whitespace is stripped

    Args:
        file_path: Path to ticker list file

    Returns:
        List of ticker symbols (uppercase)

    Raises:
        FileNotFoundError: If file doesn't exist
        ValueError: If file is empty or contains no valid tickers
    """
    path = Path(file_path)

    if not path.exists():
        raise FileNotFoundError(f"Ticker file not found: {file_path}")

    tickers = []

    with open(path, "r") as f:
        for line_num, line in enumerate(f, 1):
            # Strip whitespace
            line = line.strip()

            # Skip empty lines and comments
            if not line or line.startswith("#"):
                continue

            # Extract ticker (split on whitespace, take first token)
            ticker = line.split()[0].upper()

            # Basic validation
            if not ticker.isalpha():
                logger.warning(f"Line {line_num}: Skipping invalid ticker '{ticker}'")
                continue

            tickers.append(ticker)

    if not tickers:
        raise ValueError(f"No valid tickers found in {file_path}")

    logger.info(f"Loaded {len(tickers)} tickers from {file_path}")

    return tickers


def load_tickers_from_database(connection_string: str, query: str) -> List[str]:
    """
    Load ticker list from database query.

    Args:
        connection_string: Database connection string
        query: SQL query that returns ticker symbols

    Returns:
        List of ticker symbols (uppercase)

    Note:
        This is a placeholder for future database integration.
        Currently raises NotImplementedError.
    """
    raise NotImplementedError("Database ticker loading not yet implemented")


def load_tickers(config: TickerSourceConfig) -> List[str]:
    """
    Load tickers based on configuration.

    Args:
        config: Ticker source configuration

    Returns:
        List of ticker symbols

    Raises:
        ValueError: If source_type is unknown or configuration is invalid
    """
    if config.source_type == "file":
        if not config.file_path:
            raise ValueError("file_path must be specified for file source")
        return load_tickers_from_file(config.file_path)

    elif config.source_type == "database":
        if not config.db_connection_string or not config.db_query:
            raise ValueError(
                "db_connection_string and db_query must be specified for database source"
            )
        return load_tickers_from_database(
            config.db_connection_string, config.db_query
        )

    else:
        raise ValueError(f"Unknown source_type: {config.source_type}")


def validate_ticker(ticker: str) -> bool:
    """
    Basic ticker validation.

    Args:
        ticker: Ticker symbol to validate

    Returns:
        True if ticker appears valid, False otherwise
    """
    if not ticker:
        return False

    # Must be 1-5 characters
    if not (1 <= len(ticker) <= 5):
        return False

    # Must be alphabetic
    if not ticker.isalpha():
        return False

    return True


def deduplicate_tickers(tickers: List[str]) -> List[str]:
    """
    Remove duplicate tickers while preserving order.

    Args:
        tickers: List of tickers (may contain duplicates)

    Returns:
        List of unique tickers in original order
    """
    seen = set()
    unique = []

    for ticker in tickers:
        ticker_upper = ticker.upper()
        if ticker_upper not in seen:
            seen.add(ticker_upper)
            unique.append(ticker_upper)

    if len(unique) < len(tickers):
        logger.info(f"Removed {len(tickers) - len(unique)} duplicate tickers")

    return unique
