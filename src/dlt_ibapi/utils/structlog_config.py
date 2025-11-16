"""
Structlog configuration for dlt-ibapi.

This module provides centralized structlog configuration with support for:
- Human-readable console output (default)
- JSON output (with --json-logs flag)
- File logging with timestamped rotation (with --log-file flag)
- Context binding for operation metadata
- Third-party logger suppression
"""

import logging
import logging.handlers
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

import structlog
from structlog.types import Processor


class TimestampedRotatingFileHandler(logging.handlers.RotatingFileHandler):
    """
    Rotating file handler that uses timestamps instead of numeric suffixes.

    When a log file reaches maxBytes, it is renamed with a timestamp suffix
    (e.g., backfill-2025-11-16T21-30-15.log) and a new file is created.

    This makes it easy to locate logs for specific time periods.

    Example:
        logs/backfill.log                      # Current
        logs/backfill-2025-11-16T21-30-15.log  # Rotated 30 mins ago
        logs/backfill-2025-11-16T20-45-03.log  # Rotated 1 hour ago
    """

    def doRollover(self):
        """
        Override rotation to use timestamp suffix instead of numeric.

        When the current log file reaches maxBytes:
        1. Close the current file
        2. Rename it with timestamp: <name>-<timestamp>.<ext>
        3. Clean up old backups (keep only backupCount most recent)
        4. Open a new file with the original name
        """
        if self.stream:
            self.stream.close()
            self.stream = None

        # Generate timestamp for backup filename
        timestamp = datetime.now().strftime("%Y-%m-%dT%H-%M-%S")
        log_path = Path(self.baseFilename)

        # Create backup filename: <stem>-<timestamp><suffix>
        # Example: backfill.log → backfill-2025-11-16T21-30-15.log
        backup_name = f"{log_path.stem}-{timestamp}{log_path.suffix}"
        backup_path = log_path.parent / backup_name

        # Rename current file to timestamped backup
        if os.path.exists(self.baseFilename):
            os.rename(self.baseFilename, str(backup_path))

        # Clean old backups (keep last N files by modification time)
        self._cleanup_old_backups(log_path)

        # Open new file
        self.stream = self._open()

    def _cleanup_old_backups(self, log_path: Path):
        """
        Keep only the most recent backupCount timestamped backup files.

        Args:
            log_path: Path to the main log file
        """
        # Find all timestamped backups matching pattern
        # Pattern: <stem>-*<suffix> (e.g., backfill-*.log)
        pattern = f"{log_path.stem}-*{log_path.suffix}"
        backups = list(log_path.parent.glob(pattern))

        # Sort by modification time (newest first)
        backups.sort(key=lambda p: p.stat().st_mtime, reverse=True)

        # Delete old backups beyond backupCount
        for old_backup in backups[self.backupCount:]:
            try:
                os.remove(old_backup)
            except OSError:
                # Ignore errors during cleanup (file may be in use)
                pass


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
    Configure file logging with timestamped rotation.

    Rotates log files when they reach 10MB, using timestamp suffixes
    instead of numeric suffixes for easier identification.

    Example rotation:
        logs/backfill.log                      # Current
        logs/backfill-2025-11-16T21-30-15.log  # Rotated 30 mins ago
        logs/backfill-2025-11-16T20-45-03.log  # Rotated 1 hour ago

    Args:
        log_file: Path to log file
        log_level: Logging level
        json_format: Whether to use JSON format for file logs
    """
    # Create log directory if needed
    log_path = Path(log_file)
    log_path.parent.mkdir(parents=True, exist_ok=True)

    # Create timestamped rotating file handler
    file_handler = TimestampedRotatingFileHandler(
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
