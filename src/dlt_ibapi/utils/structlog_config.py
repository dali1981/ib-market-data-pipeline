"""
Structlog configuration for dlt-ibapi.

This module provides centralized structlog configuration with support for:
- Human-readable console output (default)
- JSON output (with --json-logs flag)
- File logging with rotation (with --log-file flag)
- Context binding for operation metadata
- Third-party logger suppression
"""

import logging
import sys
from pathlib import Path
from typing import Optional

import structlog
from structlog.types import Processor


def configure_structlog(
    verbose: bool = False,
    quiet: bool = False,
    json_logs: bool = False,
    log_file: Optional[str] = None,
) -> None:
    """
    Configure structlog for the application.

    Args:
        verbose: Enable DEBUG level logging
        quiet: Only show WARNING and ERROR logs
        json_logs: Use JSON output format instead of console
        log_file: Path to log file (enables file logging with rotation)
    """
    # Determine log level
    if verbose:
        log_level = logging.DEBUG
    elif quiet:
        log_level = logging.WARNING
    else:
        log_level = logging.INFO

    # Configure standard library logging
    logging.basicConfig(
        format="%(message)s",
        level=log_level,
        stream=sys.stderr,
    )

    # Suppress noisy third-party loggers
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("requests").setLevel(logging.WARNING)
    logging.getLogger("ibapi").setLevel(logging.WARNING)
    logging.getLogger("dlt").setLevel(logging.WARNING)

    # Build processor chain
    processors: list[Processor] = [
        # Add context from contextvars
        structlog.contextvars.merge_contextvars,
        # Add log level to event dict
        structlog.stdlib.add_log_level,
        # Add logger name to event dict
        structlog.stdlib.add_logger_name,
        # Add timestamp
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        # Format stack info if available
        structlog.processors.StackInfoRenderer(),
        # Format exception info
        structlog.processors.format_exc_info,
    ]

    # Choose renderer based on output format
    if json_logs:
        # JSON output for production/logging systems
        processors.append(structlog.processors.JSONRenderer())
    else:
        # Human-readable console output with colors
        processors.append(
            structlog.dev.ConsoleRenderer(
                colors=sys.stderr.isatty(),  # Only use colors if outputting to terminal
            )
        )

    # Configure structlog
    structlog.configure(
        processors=processors,
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    # Configure file logging if requested
    if log_file:
        _configure_file_logging(log_file, log_level, json_logs)


def _configure_file_logging(
    log_file: str,
    log_level: int,
    json_format: bool,
) -> None:
    """
    Configure file logging with rotation.

    Args:
        log_file: Path to log file
        log_level: Logging level
        json_format: Whether to use JSON format for file logs
    """
    from logging.handlers import RotatingFileHandler

    # Create log directory if needed
    log_path = Path(log_file)
    log_path.parent.mkdir(parents=True, exist_ok=True)

    # Create rotating file handler
    file_handler = RotatingFileHandler(
        log_file,
        maxBytes=10 * 1024 * 1024,  # 10 MB
        backupCount=5,
    )
    file_handler.setLevel(log_level)

    # Configure formatter
    if json_format:
        # Use structlog's JSONRenderer for file logs
        formatter = structlog.stdlib.ProcessorFormatter(
            processor=structlog.processors.JSONRenderer(),
        )
    else:
        # Use standard formatter for file logs
        formatter = logging.Formatter(
            "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )

    file_handler.setFormatter(formatter)

    # Add handler to root logger
    root_logger = logging.getLogger()
    root_logger.addHandler(file_handler)
