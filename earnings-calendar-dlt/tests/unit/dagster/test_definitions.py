"""Tests for Dagster definitions."""

import pytest
from dagster import Definitions

from dagster_earnings import defs


def test_definitions_structure():
    """Test that definitions contain all expected components."""
    assert isinstance(defs, Definitions)

    # Check assets are defined
    assert len(defs.assets) == 2  # nasdaq_earnings_assets + custom_asset

    # Check jobs are defined
    assert len(defs.jobs) == 3  # Three job definitions

    # Check schedules are defined
    assert len(defs.schedules) == 3  # Three schedule definitions

    # Check resources are defined
    assert "dlt" in defs.resources


def test_asset_names():
    """Test that assets have expected names."""
    asset_keys = {asset.key.to_user_string() for asset in defs.assets}

    # Should contain both asset types
    assert "earnings_calendar_custom" in asset_keys


def test_job_names():
    """Test that jobs have expected names."""
    job_names = {job.name for job in defs.jobs}

    expected_jobs = {
        "nasdaq_earnings_job",
        "earnings_calendar_custom_job",
        "weekday_earnings_calendar_job",
    }

    assert expected_jobs == job_names


def test_schedule_names():
    """Test that schedules have expected names."""
    schedule_names = {schedule.name for schedule in defs.schedules}

    expected_schedules = {
        "daily_earnings_calendar_schedule",
        "daily_earnings_calendar_custom_schedule",
        "weekday_earnings_calendar_schedule",
    }

    assert expected_schedules == schedule_names
