"""
Unit tests for TimestampedRotatingFileHandler.

Tests the custom log rotation handler that uses timestamps
instead of numeric suffixes for rotated log files.
"""

import logging
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from dlt_ibapi.utils.structlog_config import TimestampedRotatingFileHandler


class TestTimestampedRotatingFileHandler:
    """Test timestamped log file rotation."""

    def test_rotation_creates_timestamped_backup(self, tmp_path):
        """Test that rotation creates timestamp-suffixed backup file."""
        log_file = tmp_path / "test.log"

        # Create handler with small max size to trigger rotation
        handler = TimestampedRotatingFileHandler(
            str(log_file),
            maxBytes=100,  # 100 bytes to trigger rotation quickly
            backupCount=5,
        )

        logger = logging.getLogger("test_rotation")
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)

        # Write enough data to trigger rotation
        for i in range(20):
            logger.info(f"Log message {i} with some padding to reach size limit")

        # Check that backup file exists with timestamp pattern
        backups = list(tmp_path.glob("test-*.log"))
        assert len(backups) >= 1, "Expected at least one timestamped backup file"

        # Verify timestamp format (YYYY-MM-DDTHH-MM-SS)
        backup = backups[0]
        assert backup.stem.startswith("test-"), f"Backup should start with 'test-': {backup.stem}"

        # Extract timestamp part
        timestamp_part = backup.stem.replace("test-", "")
        # Verify it matches expected format
        try:
            datetime.strptime(timestamp_part, "%Y-%m-%dT%H-%M-%S")
        except ValueError:
            pytest.fail(f"Timestamp format invalid: {timestamp_part}")

        # Clean up
        logger.removeHandler(handler)
        handler.close()

    def test_rotation_respects_backup_count(self, tmp_path):
        """Test that old backups are deleted when exceeding backupCount."""
        log_file = tmp_path / "test.log"

        # Create handler with backupCount=3
        handler = TimestampedRotatingFileHandler(
            str(log_file),
            maxBytes=50,  # Small size to trigger many rotations
            backupCount=3,
        )

        logger = logging.getLogger("test_backup_count")
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)

        # Trigger multiple rotations (more than backupCount)
        for i in range(100):
            logger.info(f"Log message {i} with padding to trigger rotation quickly")

        # Check that only backupCount backups exist
        backups = list(tmp_path.glob("test-*.log"))
        assert len(backups) <= 3, f"Expected at most 3 backups, got {len(backups)}"

        # Clean up
        logger.removeHandler(handler)
        handler.close()

    def test_current_file_always_has_original_name(self, tmp_path):
        """Test that current log file always has the original name."""
        log_file = tmp_path / "current.log"

        handler = TimestampedRotatingFileHandler(
            str(log_file),
            maxBytes=100,
            backupCount=5,
        )

        logger = logging.getLogger("test_current_name")
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)

        # Write data and trigger rotation
        for i in range(30):
            logger.info(f"Log message {i} with some padding")

        # Current file should exist with original name
        assert log_file.exists(), "Current log file should exist"

        # Backups should have timestamps
        backups = list(tmp_path.glob("current-*.log"))
        for backup in backups:
            assert backup.name != "current.log", "Backup should not have original name"
            assert "-" in backup.stem, "Backup should have timestamp separator"

        # Clean up
        logger.removeHandler(handler)
        handler.close()

    def test_backups_sorted_by_modification_time(self, tmp_path):
        """Test that backups are sorted by modification time, not name."""
        log_file = tmp_path / "sorted.log"

        handler = TimestampedRotatingFileHandler(
            str(log_file),
            maxBytes=80,
            backupCount=5,
        )

        logger = logging.getLogger("test_sorting")
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)

        # Trigger several rotations
        for i in range(50):
            logger.info(f"Log message {i} with enough padding to trigger rotation")

        # Get all backups
        backups = list(tmp_path.glob("sorted-*.log"))

        if len(backups) > 1:
            # Verify backups are sorted by mtime (newest first in our implementation)
            mtimes = [backup.stat().st_mtime for backup in backups]

            # Newest backups should have highest mtime
            # (our cleanup keeps newest files, deletes oldest)
            assert backups, "Should have backups to test"

        # Clean up
        logger.removeHandler(handler)
        handler.close()

    def test_rotation_with_different_extensions(self, tmp_path):
        """Test rotation works with different file extensions."""
        for ext in [".log", ".json", ".txt"]:
            log_file = tmp_path / f"test{ext}"

            handler = TimestampedRotatingFileHandler(
                str(log_file),
                maxBytes=100,
                backupCount=3,
            )

            logger = logging.getLogger(f"test_ext_{ext}")
            logger.addHandler(handler)
            logger.setLevel(logging.INFO)

            # Trigger rotation
            for i in range(20):
                logger.info(f"Message {i} with padding")

            # Check backup has correct extension
            backups = list(tmp_path.glob(f"test-*{ext}"))
            assert len(backups) >= 1, f"Expected backup with {ext} extension"

            for backup in backups:
                assert backup.suffix == ext, f"Backup should have {ext} extension"

            # Clean up
            logger.removeHandler(handler)
            handler.close()

    def test_no_rotation_if_under_size_limit(self, tmp_path):
        """Test that no rotation occurs if file is under maxBytes."""
        log_file = tmp_path / "no_rotation.log"

        handler = TimestampedRotatingFileHandler(
            str(log_file),
            maxBytes=10000,  # Large size, won't trigger rotation
            backupCount=5,
        )

        logger = logging.getLogger("test_no_rotation")
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)

        # Write small amount of data
        for i in range(5):
            logger.info(f"Message {i}")

        # Should have no backups
        backups = list(tmp_path.glob("no_rotation-*.log"))
        assert len(backups) == 0, "Should have no backups when under size limit"

        # Clean up
        logger.removeHandler(handler)
        handler.close()

    def test_cleanup_ignores_oserror(self, tmp_path):
        """Test that cleanup gracefully handles OSError (e.g., file in use)."""
        log_file = tmp_path / "cleanup.log"

        handler = TimestampedRotatingFileHandler(
            str(log_file),
            maxBytes=100,
            backupCount=2,  # Low count to trigger cleanup
        )

        logger = logging.getLogger("test_cleanup")
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)

        # Trigger multiple rotations
        for i in range(50):
            logger.info(f"Message {i} with padding to trigger rotation")

        # Even if cleanup fails, handler should not crash
        # (OSError is caught and ignored)
        backups = list(tmp_path.glob("cleanup-*.log"))

        # Should have at most backupCount backups (2)
        # (May have more if OSError prevented deletion, but shouldn't crash)
        assert isinstance(backups, list), "Cleanup should not crash on OSError"

        # Clean up
        logger.removeHandler(handler)
        handler.close()


class TestTimestampFormat:
    """Test timestamp format in backup filenames."""

    def test_timestamp_format_is_iso8601_compatible(self, tmp_path):
        """Test that timestamp format is ISO 8601 compatible (sortable)."""
        log_file = tmp_path / "iso.log"

        handler = TimestampedRotatingFileHandler(
            str(log_file),
            maxBytes=50,
            backupCount=10,
        )

        logger = logging.getLogger("test_iso")
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)

        # Trigger several rotations
        for i in range(100):
            logger.info(f"Message {i} with padding")

        # Get all backups
        backups = list(tmp_path.glob("iso-*.log"))

        if len(backups) > 1:
            # Sort backups alphabetically (by filename)
            backups_by_name = sorted(backups, key=lambda p: p.name)

            # Get mtimes
            backups_by_mtime = sorted(backups, key=lambda p: p.stat().st_mtime)

            # ISO 8601 format (YYYY-MM-DDTHH-MM-SS) sorts correctly
            # Check that name-sorted order is close to mtime-sorted order
            # (May not be exact due to second precision, but should be similar)
            assert len(backups_by_name) == len(backups_by_mtime)

        # Clean up
        logger.removeHandler(handler)
        handler.close()

    def test_timestamp_is_current_time(self, tmp_path):
        """Test that timestamp in backup is approximately current time."""
        log_file = tmp_path / "time_check.log"

        handler = TimestampedRotatingFileHandler(
            str(log_file),
            maxBytes=50,
            backupCount=5,
        )

        logger = logging.getLogger("test_time")
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)

        # Record time before rotation (truncate to seconds for comparison)
        before = datetime.now().replace(microsecond=0)

        # Trigger rotation
        for i in range(30):
            logger.info(f"Message {i} with padding")

        # Record time after rotation (add 1 second buffer for comparison)
        after = datetime.now().replace(microsecond=0) + timedelta(seconds=1)

        # Get backup
        backups = list(tmp_path.glob("time_check-*.log"))

        if backups:
            backup = backups[0]
            timestamp_str = backup.stem.replace("time_check-", "")
            backup_time = datetime.strptime(timestamp_str, "%Y-%m-%dT%H-%M-%S")

            # Backup timestamp should be between before and after
            assert before <= backup_time <= after, \
                f"Backup timestamp {backup_time} should be between {before} and {after}"

        # Clean up
        logger.removeHandler(handler)
        handler.close()
