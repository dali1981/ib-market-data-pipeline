"""Dagster schedules for earnings calendar pipeline."""

from dagster import (
    schedule,
    RunRequest,
    ScheduleDefinition,
    DefaultScheduleStatus,
)

from .assets import nasdaq_earnings_assets, earnings_calendar_custom_asset


@schedule(
    cron_schedule="0 6 * * *",  # Daily at 6 AM
    job_name="nasdaq_earnings_job",
    default_status=DefaultScheduleStatus.RUNNING,
)
def daily_earnings_calendar_schedule():
    """
    Daily schedule for earnings calendar data refresh.

    Runs every day at 6 AM to capture the latest earnings announcements
    and estimate updates.
    """
    return RunRequest()


# Alternative: Schedule with dynamic configuration
@schedule(
    cron_schedule="0 6 * * *",
    job_name="earnings_calendar_custom_job",
    default_status=DefaultScheduleStatus.STOPPED,  # Starts paused
)
def daily_earnings_calendar_custom_schedule(context):
    """
    Daily schedule with custom configuration.

    This schedule starts paused and can be configured with run config.
    """
    # You can add dynamic configuration here
    run_config = {
        "ops": {
            "earnings_calendar_custom_asset": {
                "config": {
                    # Add any runtime configuration here
                }
            }
        }
    }

    return RunRequest(
        run_key=f"earnings_calendar_{context.scheduled_execution_time.strftime('%Y%m%d')}",
        run_config=run_config,
        tags={"source": "nasdaq", "frequency": "daily"},
    )


# Weekend-aware schedule (skip weekends)
from datetime import datetime


@schedule(
    cron_schedule="0 6 * * 1-5",  # Monday-Friday at 6 AM
    job_name="weekday_earnings_calendar_job",
    default_status=DefaultScheduleStatus.STOPPED,
)
def weekday_earnings_calendar_schedule():
    """
    Weekday-only schedule for earnings calendar data.

    Runs Monday through Friday at 6 AM, skipping weekends since
    markets are closed.
    """
    return RunRequest(
        tags={"day": datetime.now().strftime("%A"), "market_hours": "true"}
    )
