"""Logging utilities for dlt-ibapi.

Provides structured logging with support for:
- Console and file output
- Verbose/quiet modes
- JSON structured logs
- File rotation

Usage:
    setup_logging(level="INFO", verbose=True, log_file=Path("app.log"))
    logger = get_logger(__name__)
    logger.info("message", key1="value1", key2="value2")
"""

import logging
import sys
from pathlib import Path
from typing import Optional
from logging.handlers import RotatingFileHandler
import json
from datetime import datetime


class JSONFormatter(logging.Formatter):
    """Format log records as JSON for structured logging."""

    def format(self, record: logging.LogRecord) -> str:
        """Format log record as JSON string."""
        log_data = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        # Add extra fields from record
        for key, value in record.__dict__.items():
            if key not in [
                "name",
                "msg",
                "args",
                "created",
                "filename",
                "funcName",
                "levelname",
                "levelno",
                "lineno",
                "module",
                "msecs",
                "message",
                "pathname",
                "process",
                "processName",
                "relativeCreated",
                "thread",
                "threadName",
                "exc_info",
                "exc_text",
                "stack_info",
            ]:
                log_data[key] = value

        # Add exception info if present
        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)

        return json.dumps(log_data)


def setup_logging(
    level: str = "INFO",
    log_file: Optional[Path] = None,
    verbose: bool = False,
    quiet: bool = False,
    json_logs: bool = False,
    max_bytes: int = 10 * 1024 * 1024,  # 10MB
    backup_count: int = 5,
) -> None:
    """Setup logging configuration.

    Args:
        level: Base logging level (DEBUG, INFO, WARNING, ERROR)
        log_file: Optional path to log file (enables file logging with rotation)
        verbose: Enable verbose (DEBUG) logging (overrides level)
        quiet: Suppress INFO logs, only show WARNING and above
        json_logs: Output logs as JSON (structured logging)
        max_bytes: Maximum size of log file before rotation (default: 10MB)
        backup_count: Number of backup log files to keep (default: 5)

    Example:
        >>> setup_logging(level="INFO", verbose=True, log_file=Path("app.log"))
        >>> logger = get_logger(__name__)
        >>> logger.info("application_started", version="1.0.0")
    """
    # Determine logging level
    if verbose:
        log_level = logging.DEBUG
    elif quiet:
        log_level = logging.WARNING
    else:
        log_level = getattr(logging, level.upper(), logging.INFO)

    # Root logger configuration
    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)
    root_logger.handlers.clear()  # Remove existing handlers

    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(log_level)

    if json_logs:
        # JSON formatter for structured logs
        console_formatter = JSONFormatter()
    else:
        # Human-readable formatter
        if verbose:
            # Verbose format includes more details
            console_format = "%(asctime)s | %(levelname)-8s | %(name)s:%(lineno)d | %(message)s"
        else:
            # Concise format for normal use
            console_format = "%(levelname)-8s | %(message)s"

        console_formatter = logging.Formatter(
            console_format, datefmt="%Y-%m-%d %H:%M:%S"
        )

    console_handler.setFormatter(console_formatter)
    root_logger.addHandler(console_handler)

    # File handler with rotation (if log_file specified)
    if log_file:
        log_file = Path(log_file)
        log_file.parent.mkdir(parents=True, exist_ok=True)

        file_handler = RotatingFileHandler(
            log_file,
            maxBytes=max_bytes,
            backupCount=backup_count,
            encoding="utf-8",
        )
        file_handler.setLevel(logging.DEBUG)  # Always DEBUG to file

        if json_logs:
            file_formatter = JSONFormatter()
        else:
            # Detailed format for file logs
            file_format = (
                "%(asctime)s | %(levelname)-8s | %(name)s:%(lineno)d | %(message)s"
            )
            file_formatter = logging.Formatter(file_format, datefmt="%Y-%m-%d %H:%M:%S")

        file_handler.setFormatter(file_formatter)
        root_logger.addHandler(file_handler)

    # Suppress noisy third-party loggers
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("requests").setLevel(logging.WARNING)
    logging.getLogger("ibapi").setLevel(logging.WARNING)
    logging.getLogger("dlt").setLevel(logging.INFO)


def get_logger(name: str) -> logging.Logger:
    """Get a logger instance for a module.

    Args:
        name: Logger name (usually __name__)

    Returns:
        Logger instance configured with structured logging

    Example:
        >>> logger = get_logger(__name__)
        >>> logger.info("user_login", user_id=123, ip="192.168.1.1")
    """
    logger = logging.getLogger(name)

    # Add convenience method for structured logging
    def structured_log(level: int, message: str, **kwargs):
        """Log with structured key-value pairs."""
        if logger.isEnabledFor(level):
            extra_msg = " | ".join(f"{k}={v}" for k, v in kwargs.items())
            full_message = f"{message} | {extra_msg}" if extra_msg else message
            logger.log(level, full_message, extra=kwargs)

    # Add convenience methods
    logger.debug_struct = lambda msg, **kw: structured_log(logging.DEBUG, msg, **kw)
    logger.info_struct = lambda msg, **kw: structured_log(logging.INFO, msg, **kw)
    logger.warning_struct = lambda msg, **kw: structured_log(logging.WARNING, msg, **kw)
    logger.error_struct = lambda msg, **kw: structured_log(logging.ERROR, msg, **kw)

    return logger
