"""Tests for configuration."""

import pytest
import os
from earnings_calendar.config import (
    EarningsScraperConfig,
    EarningsDltConfig,
    EarningsCalendarConfig,
    get_default_config,
)


def test_scraper_config_defaults():
    """Test default scraper configuration."""
    config = EarningsScraperConfig()

    assert config.days_ahead == 30
    assert config.use_playwright_fallback is True
    assert config.timeout == 30


def test_scraper_config_custom():
    """Test custom scraper configuration."""
    config = EarningsScraperConfig(
        days_ahead=60,
        use_playwright_fallback=False,
        timeout=60,
    )

    assert config.days_ahead == 60
    assert config.use_playwright_fallback is False
    assert config.timeout == 60


def test_dlt_config_defaults():
    """Test default dlt configuration."""
    config = EarningsDltConfig()

    assert config.destination == "filesystem"
    assert config.dataset_name == "nasdaq_earnings"
    assert config.bucket_url is None
    assert config.write_disposition == "replace"


def test_calendar_config():
    """Test combined calendar configuration."""
    config = EarningsCalendarConfig()

    assert isinstance(config.scraper, EarningsScraperConfig)
    assert isinstance(config.dlt, EarningsDltConfig)


def test_config_from_env(monkeypatch):
    """Test loading configuration from environment variables."""
    # Set environment variables
    monkeypatch.setenv("EARNINGS_DAYS_AHEAD", "60")
    monkeypatch.setenv("EARNINGS_PLAYWRIGHT_FALLBACK", "false")
    monkeypatch.setenv("EARNINGS_TIMEOUT", "45")
    monkeypatch.setenv("EARNINGS_DESTINATION", "duckdb")
    monkeypatch.setenv("EARNINGS_DATASET_NAME", "test_earnings")

    config = EarningsCalendarConfig.from_env()

    assert config.scraper.days_ahead == 60
    assert config.scraper.use_playwright_fallback is False
    assert config.scraper.timeout == 45
    assert config.dlt.destination == "duckdb"
    assert config.dlt.dataset_name == "test_earnings"


def test_get_default_config():
    """Test getting default configuration."""
    config = get_default_config()

    assert isinstance(config, EarningsCalendarConfig)
    assert config.scraper.days_ahead >= 1
    assert config.dlt.destination in ["filesystem", "duckdb"]
