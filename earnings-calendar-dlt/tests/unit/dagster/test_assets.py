"""Tests for Dagster assets."""

import pytest
from dagster import build_op_context
from dagster_dlt import DagsterDltResource

from dagster_earnings.assets import earnings_calendar_custom_asset


def test_custom_asset_structure():
    """Test that custom asset is properly defined."""
    # Get the asset key
    asset_keys = list(earnings_calendar_custom_asset.keys)
    assert len(asset_keys) == 1

    asset_key = asset_keys[0]
    assert asset_key.to_user_string() == "earnings_calendar_custom"

    # Check group name
    assert earnings_calendar_custom_asset.group_names_by_key[asset_key] == "earnings_calendar"

    # Check compute kind (stored in tags)
    # Note: In Dagster 1.9+, compute_kind is in the asset metadata/tags
    # We can verify the asset is properly created and has expected properties


# Note: Full asset execution tests would require:
# - Mock scraper responses
# - Mock filesystem destination
# - Dagster test environment
# These are more integration tests than unit tests
