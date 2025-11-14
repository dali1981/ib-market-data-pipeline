"""Logging utilities for dlt-ibapi.

Provides structured logging with support for:
- Console and file output
- Verbose/quiet modes
- JSON structured logs
- File rotation
- Context binding

This module wraps structlog for backward compatibility with existing code.

Usage:
    from dlt_ibapi.utils.logging import get_logger

    logger = get_logger(__name__)
    logger.info("message", key1="value1", key2="value2")

    # With context binding
    log = logger.bind(symbol="AAPL", operation="backfill")
    log.info("starting_operation")  # Automatically includes symbol and operation
"""

import structlog
from structlog.stdlib import BoundLogger


def get_logger(name: str) -> BoundLogger:
    """Get a structlog logger instance for a module.

    Args:
        name: Logger name (usually __name__)

    Returns:
        BoundLogger instance configured with structlog

    Example:
        >>> logger = get_logger(__name__)
        >>> logger.info("user_login", user_id=123, ip="192.168.1.1")

        >>> # With context binding
        >>> log = logger.bind(symbol="AAPL", date="2025-01-01")
        >>> log.info("starting_backfill")  # Automatically includes symbol and date
    """
    return structlog.get_logger(name)
