"""Business logic for tick backfill CLI commands."""

import time
import dlt
from pathlib import Path
from typing import Optional

from .models import BackfillTicksParams, BackfillTicksResult
from ..config_loader import get_connection_config
from ..backfill.tick_resources import backfill_option_ticks_bid_ask, backfill_option_ticks_trades


def execute_backfill_ticks(
    params: BackfillTicksParams,
    connection_config: Optional[any] = None,
) -> BackfillTicksResult:
    """
    Execute tick backfill operation.

    Args:
        params: Backfill parameters
        connection_config: Optional IB connection config (for testing)

    Returns:
        BackfillTicksResult with operation details
    """
    start_time = time.time()

    try:
        # Load config if not provided
        if connection_config is None:
            connection_config = get_connection_config()

        # Create DLT pipeline
        pipeline = dlt.pipeline(
            pipeline_name=params.pipeline_name,
            destination=dlt.destinations.filesystem(bucket_url=str(params.database_path)),
            dataset_name=params.dataset_name,
        )

        # Select resource based on tick type
        if params.tick_type == 'bid_ask':
            resource = backfill_option_ticks_bid_ask(
                underlying=params.symbol,
                expiry=params.expiry,
                strike=params.strike,
                right=params.right.upper(),
                start_datetime=params.start_datetime,
                end_datetime=params.end_datetime,
                exchange=params.exchange,
                currency=params.currency,
                connection_config=connection_config,
                use_rth=params.use_rth,
                timezone=params.timezone,
            )
        else:  # trades
            resource = backfill_option_ticks_trades(
                underlying=params.symbol,
                expiry=params.expiry,
                strike=params.strike,
                right=params.right.upper(),
                start_datetime=params.start_datetime,
                end_datetime=params.end_datetime,
                exchange=params.exchange,
                currency=params.currency,
                connection_config=connection_config,
                use_rth=params.use_rth,
                timezone=params.timezone,
            )

        # Run pipeline
        info = pipeline.run(resource, loader_file_format="parquet")

        duration = time.time() - start_time
        ticks_loaded = info.metrics.get('rows', 0)

        time_range = f"{params.start_datetime.isoformat()} to {params.end_datetime.isoformat()}"

        return BackfillTicksResult(
            success=True,
            symbol=params.symbol,
            expiry=params.expiry.isoformat(),
            strike=params.strike,
            right=params.right.upper(),
            tick_type=params.tick_type,
            ticks_loaded=ticks_loaded,
            time_range=time_range,
            duration_seconds=duration,
        )

    except Exception as e:
        duration = time.time() - start_time
        return BackfillTicksResult(
            success=False,
            symbol=params.symbol,
            expiry=params.expiry.isoformat(),
            strike=params.strike,
            right=params.right.upper(),
            tick_type=params.tick_type,
            ticks_loaded=0,
            time_range=f"{params.start_datetime.isoformat()} to {params.end_datetime.isoformat()}",
            duration_seconds=duration,
            error=str(e),
        )
