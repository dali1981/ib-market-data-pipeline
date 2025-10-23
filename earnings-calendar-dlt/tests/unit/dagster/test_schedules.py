"""Tests for Dagster schedules."""

import pytest
from dagster_earnings.schedules import (
    daily_earnings_calendar_schedule,
    weekday_earnings_calendar_schedule,
)


def test_daily_schedule_configuration():
    """Test daily schedule is properly configured."""
    assert daily_earnings_calendar_schedule.cron_schedule == "0 6 * * *"
    assert daily_earnings_calendar_schedule.job_name == "nasdaq_earnings_job"


def test_weekday_schedule_configuration():
    """Test weekday schedule is properly configured."""
    assert weekday_earnings_calendar_schedule.cron_schedule == "0 6 * * 1-5"
    assert weekday_earnings_calendar_schedule.job_name == "weekday_earnings_calendar_job"
