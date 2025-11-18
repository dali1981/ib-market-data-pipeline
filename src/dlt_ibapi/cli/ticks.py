"""Business logic for tick backfill CLI commands."""

import time
import dlt
from pathlib import Path
from datetime import datetime
from typing import Optional
from structlog import get_logger

from .models import BackfillTicksParams, BackfillTicksResult
from ..config_loader import get_connection_config
from ..backfill.tick_resources import backfill_option_ticks_bid_ask
from ..strategies import EarningsTimingCalculator

logger = get_logger(__name__)


def execute_backfill_ticks(
    params: BackfillTicksParams,
    connection_config: Optional[any] = None,
) -> BackfillTicksResult:
    """
    Execute tick backfill operation.

    Supports two modes:
    1. Explicit windows: Use start_time and end_time from params
    2. Earnings mode: Auto-calculate windows based on earnings_date, earnings_time, and window_type

    Args:
        params: Backfill parameters
        connection_config: Optional IB connection config (for testing)

    Returns:
        BackfillTicksResult with operation details
    """
    start_time = time.time()

    try:
        # Determine the actual start/end times
        if params.start_time and params.end_time:
            # Mode 1: Explicit windows
            actual_start = params.start_time
            actual_end = params.end_time
            logger.info(
                "tick_backfill_explicit_mode",
                symbol=params.symbol,
                strike=params.strike,
                expiry=params.expiry,
                start=actual_start,
                end=actual_end,
            )
        else:
            # Mode 2: Earnings mode - calculate windows
            calculator = EarningsTimingCalculator()
            windows = calculator.calculate_windows(
                earnings_date=params.earnings_date,
                earnings_time=params.earnings_time,
            )

            if params.window_type == 'entry':
                actual_start = windows.entry.start
                actual_end = windows.entry.end
            else:  # exit
                actual_start = windows.exit.start
                actual_end = windows.exit.end

            logger.info(
                "tick_backfill_earnings_mode",
                symbol=params.symbol,
                strike=params.strike,
                expiry=params.expiry,
                earnings_date=params.earnings_date,
                earnings_time=params.earnings_time,
                window_type=params.window_type,
                calculated_start=actual_start,
                calculated_end=actual_end,
            )

        # Load config if not provided
        if connection_config is None:
            connection_config = get_connection_config()

        # Override client_id if provided
        if params.client_id is not None:
            connection_config.client_id = params.client_id

        # Create DLT pipeline
        pipeline = dlt.pipeline(
            pipeline_name=params.pipeline_name,
            destination=dlt.destinations.filesystem(bucket_url=str(params.database_path)),
            dataset_name=params.dataset_name,
        )

        # Use bid/ask ticks resource (most complete data)
        resource = backfill_option_ticks_bid_ask(
            underlying=params.symbol,
            expiry=params.expiry,
            strike=params.strike,
            right=params.right.upper(),
            start_datetime=actual_start,
            end_datetime=actual_end,
            connection_config=connection_config,
        )

        # Run pipeline
        logger.info("running_tick_pipeline", pipeline_name=params.pipeline_name)
        info = pipeline.run(resource, loader_file_format="parquet")

        duration = time.time() - start_time
        total_ticks = info.metrics.get('rows', 0)

        output_path = Path(params.database_path) / params.dataset_name

        logger.info(
            "tick_backfill_success",
            symbol=params.symbol,
            total_ticks=total_ticks,
            duration=duration,
        )

        return BackfillTicksResult(
            success=True,
            symbol=params.symbol,
            expiry=params.expiry,
            strike=params.strike,
            right=params.right.upper(),
            start_time=actual_start,
            end_time=actual_end,
            total_ticks=total_ticks,
            pipeline_name=params.pipeline_name,
            output_path=output_path,
            duration_seconds=duration,
        )

    except Exception as e:
        duration = time.time() - start_time
        logger.error(
            "tick_backfill_failed",
            symbol=params.symbol,
            error=str(e),
            duration=duration,
        )

        # Use actual times if calculated, otherwise use params
        if params.start_time and params.end_time:
            actual_start = params.start_time
            actual_end = params.end_time
        else:
            # Best effort - use current time if calculation failed
            actual_start = datetime.now()
            actual_end = datetime.now()

        return BackfillTicksResult(
            success=False,
            symbol=params.symbol,
            expiry=params.expiry,
            strike=params.strike,
            right=params.right.upper(),
            start_time=actual_start,
            end_time=actual_end,
            total_ticks=0,
            pipeline_name=params.pipeline_name,
            output_path=Path(params.database_path) / params.dataset_name,
            duration_seconds=duration,
            error=str(e),
        )
