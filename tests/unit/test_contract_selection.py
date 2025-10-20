"""
Unit tests for contract selection algorithms.

Tests the various strategies for selecting which option contracts
to backfill: K_AROUND_ATM, MONEYNESS, DELTA, and ALL.
"""

import pytest
from datetime import date
import pandas as pd
from dlt_ibapi.backfill.contract_selection import (
    select_k_around_atm,
    select_by_moneyness,
    black_scholes_call_delta,
    black_scholes_put_delta,
    select_by_delta,
    filter_contracts_by_selection_mode,
)


class TestSelectKAroundATM:
    """Tests for K_AROUND_ATM selection mode."""

    def test_odd_number_of_strikes(self):
        """Test with odd number of strikes."""
        strikes = [140.0, 145.0, 150.0, 155.0, 160.0]
        spot = 150.0
        k = 1

        selected = select_k_around_atm(strikes, spot, k)

        # Should select: 145 (1 below), 150 (ATM), 155 (1 above)
        assert selected == [145.0, 150.0, 155.0]

    def test_even_number_of_strikes(self):
        """Test with even number of strikes."""
        strikes = [140.0, 145.0, 150.0, 155.0]
        spot = 147.5
        k = 1

        selected = select_k_around_atm(strikes, spot, k)

        # ATM is 145 (closest to 147.5)
        # Should select: 140 (1 below), 145 (ATM), 150 (1 above)
        assert selected == [140.0, 145.0, 150.0]

    def test_k_larger_than_available(self):
        """Test when k is larger than available strikes."""
        strikes = [145.0, 150.0, 155.0]
        spot = 150.0
        k = 5

        selected = select_k_around_atm(strikes, spot, k)

        # Should return all available strikes
        assert selected == [145.0, 150.0, 155.0]

    def test_k_zero(self):
        """Test with k=0 (only ATM)."""
        strikes = [140.0, 145.0, 150.0, 155.0, 160.0]
        spot = 150.0
        k = 0

        selected = select_k_around_atm(strikes, spot, k)

        # Should return only ATM
        assert selected == [150.0]

    def test_spot_below_all_strikes(self):
        """Test when spot is below all strikes."""
        strikes = [150.0, 155.0, 160.0, 165.0, 170.0]
        spot = 140.0
        k = 2

        selected = select_k_around_atm(strikes, spot, k)

        # ATM = 150 (closest)
        # Should select starting from lowest available
        assert 150.0 in selected
        assert 155.0 in selected

    def test_spot_above_all_strikes(self):
        """Test when spot is above all strikes."""
        strikes = [130.0, 135.0, 140.0, 145.0, 150.0]
        spot = 160.0
        k = 2

        selected = select_k_around_atm(strikes, spot, k)

        # ATM = 150 (closest)
        # Should select ending at highest available
        assert 150.0 in selected
        assert 145.0 in selected

    def test_symmetric_selection(self):
        """Test that selection is symmetric around ATM."""
        strikes = [100.0, 110.0, 120.0, 130.0, 140.0, 150.0, 160.0, 170.0, 180.0]
        spot = 140.0
        k = 3

        selected = select_k_around_atm(strikes, spot, k)

        # Should select: 110, 120, 130, 140 (ATM), 150, 160, 170
        assert len(selected) == 7
        assert selected == [110.0, 120.0, 130.0, 140.0, 150.0, 160.0, 170.0]


class TestSelectByMoneyness:
    """Tests for MONEYNESS selection mode."""

    def test_exact_matches(self):
        """Test when strikes exactly match target moneyness."""
        strikes = [90.0, 95.0, 100.0, 105.0, 110.0]
        spot = 100.0
        targets = [0.90, 0.95, 1.0, 1.05, 1.10]

        selected = select_by_moneyness(strikes, spot, targets, tolerance=0.01)

        # All strikes should be selected (exact matches)
        assert selected == [90.0, 95.0, 100.0, 105.0, 110.0]

    def test_approximate_matches(self):
        """Test with strikes that approximately match targets."""
        strikes = [89.0, 94.0, 100.0, 106.0, 111.0]
        spot = 100.0
        targets = [0.90, 0.95, 1.0, 1.05, 1.10]

        selected = select_by_moneyness(strikes, spot, targets, tolerance=0.02)

        # Should find closest strikes within tolerance
        assert 89.0 in selected   # 0.89 moneyness (close to 0.90)
        assert 94.0 in selected   # 0.94 moneyness (close to 0.95)
        assert 100.0 in selected  # 1.0 moneyness (exact ATM)
        assert 106.0 in selected  # 1.06 moneyness (close to 1.05)
        assert 111.0 in selected  # 1.11 moneyness (close to 1.10)

    def test_no_matches_within_tolerance(self):
        """Test when no strikes are within tolerance."""
        strikes = [80.0, 120.0]
        spot = 100.0
        targets = [0.95, 1.0, 1.05]

        selected = select_by_moneyness(strikes, spot, targets, tolerance=0.01)

        # No strikes within 1% of targets
        assert selected == []

    def test_single_target(self):
        """Test with single target moneyness."""
        strikes = [95.0, 100.0, 105.0, 110.0]
        spot = 100.0
        targets = [1.0]

        selected = select_by_moneyness(strikes, spot, targets, tolerance=0.05)

        # Should select ATM
        assert selected == [100.0]

    def test_deduplication(self):
        """Test that duplicate strikes are removed."""
        strikes = [95.0, 96.0, 100.0, 104.0, 105.0]
        spot = 100.0
        targets = [0.95, 0.96, 1.04, 1.05]  # Two pairs close together

        selected = select_by_moneyness(strikes, spot, targets, tolerance=0.02)

        # Should have unique strikes only
        assert len(selected) == len(set(selected))

    def test_otm_calls_and_puts(self):
        """Test typical OTM call and put selection."""
        strikes = [85.0, 90.0, 95.0, 100.0, 105.0, 110.0, 115.0]
        spot = 100.0
        # OTM puts: < 1.0, OTM calls: > 1.0
        targets = [0.85, 0.90, 0.95, 1.05, 1.10, 1.15]

        selected = select_by_moneyness(strikes, spot, targets, tolerance=0.02)

        assert len(selected) == 6
        assert 85.0 in selected
        assert 115.0 in selected


class TestBlackScholesDelta:
    """Tests for Black-Scholes delta calculations."""

    def test_call_delta_atm(self):
        """Test call delta at-the-money."""
        spot = 100.0
        strike = 100.0
        time_to_expiry = 0.25  # 3 months
        risk_free_rate = 0.05
        volatility = 0.20

        delta = black_scholes_call_delta(
            spot, strike, time_to_expiry, risk_free_rate, volatility
        )

        # ATM call delta should be around 0.50-0.53
        assert 0.48 <= delta <= 0.55

    def test_call_delta_itm(self):
        """Test call delta in-the-money."""
        spot = 110.0
        strike = 100.0
        time_to_expiry = 0.25
        risk_free_rate = 0.05
        volatility = 0.20

        delta = black_scholes_call_delta(
            spot, strike, time_to_expiry, risk_free_rate, volatility
        )

        # ITM call delta should be high (> 0.70)
        assert delta > 0.70

    def test_call_delta_otm(self):
        """Test call delta out-of-the-money."""
        spot = 90.0
        strike = 100.0
        time_to_expiry = 0.25
        risk_free_rate = 0.05
        volatility = 0.20

        delta = black_scholes_call_delta(
            spot, strike, time_to_expiry, risk_free_rate, volatility
        )

        # OTM call delta should be low (< 0.40)
        assert delta < 0.40

    def test_put_delta_relationship(self):
        """Test put-call delta relationship: put_delta = call_delta - 1."""
        spot = 100.0
        strike = 100.0
        time_to_expiry = 0.25
        risk_free_rate = 0.05
        volatility = 0.20

        call_delta = black_scholes_call_delta(
            spot, strike, time_to_expiry, risk_free_rate, volatility
        )
        put_delta = black_scholes_put_delta(
            spot, strike, time_to_expiry, risk_free_rate, volatility
        )

        # Put delta = Call delta - 1
        assert abs(put_delta - (call_delta - 1.0)) < 0.0001

    def test_put_delta_atm(self):
        """Test put delta at-the-money."""
        spot = 100.0
        strike = 100.0
        time_to_expiry = 0.25
        risk_free_rate = 0.05
        volatility = 0.20

        delta = black_scholes_put_delta(
            spot, strike, time_to_expiry, risk_free_rate, volatility
        )

        # ATM put delta should be around -0.50
        assert -0.55 <= delta <= -0.45

    def test_zero_time_to_expiry(self):
        """Test behavior at expiration."""
        spot = 100.0
        strike = 95.0  # ITM call
        time_to_expiry = 0.0001  # Nearly expired
        risk_free_rate = 0.05
        volatility = 0.20

        delta = black_scholes_call_delta(
            spot, strike, time_to_expiry, risk_free_rate, volatility
        )

        # ITM call at expiry should have delta near 1.0
        assert delta > 0.95


class TestSelectByDelta:
    """Tests for DELTA selection mode."""

    def test_call_delta_selection(self):
        """Test selecting calls by delta."""
        strikes = [90.0, 95.0, 100.0, 105.0, 110.0]
        spot = 100.0
        expiry = date(2024, 6, 21)  # 3 months out
        as_of = date(2024, 3, 21)
        target_deltas = [0.25, 0.50, 0.75]

        selected = select_by_delta(
            strikes, spot, expiry, as_of, target_deltas,
            option_type="call",
            risk_free_rate=0.05,
            volatility=0.20,
            tolerance=0.15
        )

        # Should find strikes with deltas close to targets
        assert len(selected) > 0
        assert len(selected) <= len(target_deltas)

    def test_put_delta_selection(self):
        """Test selecting puts by delta."""
        strikes = [90.0, 95.0, 100.0, 105.0, 110.0]
        spot = 100.0
        expiry = date(2024, 6, 21)
        as_of = date(2024, 3, 21)
        target_deltas = [-0.25, -0.50, -0.75]  # Negative for puts

        selected = select_by_delta(
            strikes, spot, expiry, as_of, target_deltas,
            option_type="put",
            risk_free_rate=0.05,
            volatility=0.20,
            tolerance=0.15
        )

        assert len(selected) > 0

    def test_short_time_to_expiry(self):
        """Test selection with short time to expiry."""
        strikes = [95.0, 100.0, 105.0]
        spot = 100.0
        expiry = date(2024, 3, 28)  # 1 week
        as_of = date(2024, 3, 21)
        target_deltas = [0.50]

        selected = select_by_delta(
            strikes, spot, expiry, as_of, target_deltas,
            option_type="call",
            tolerance=0.15
        )

        # Should still find ATM
        assert 100.0 in selected

    def test_no_matches_strict_tolerance(self):
        """Test with very strict tolerance."""
        strikes = [80.0, 120.0]  # Far from spot
        spot = 100.0
        expiry = date(2024, 6, 21)
        as_of = date(2024, 3, 21)
        target_deltas = [0.50]

        selected = select_by_delta(
            strikes, spot, expiry, as_of, target_deltas,
            option_type="call",
            tolerance=0.01  # Very strict
        )

        # Unlikely to find exact 0.50 delta with these strikes
        assert len(selected) == 0


class TestFilterContractsBySelectionMode:
    """Tests for the unified contract selection interface."""

    @pytest.fixture
    def sample_chain_snapshot(self):
        """Create sample chain snapshot DataFrame."""
        return pd.DataFrame([
            {
                "underlying": "AAPL",
                "exchange": "SMART",
                "trading_class": "AAPL",
                "expirations": ["20240621", "20240719"],  # 2 expirations
                "strikes": [90.0, 95.0, 100.0, 105.0, 110.0],
                "as_of": date(2024, 3, 21),
            }
        ])

    def test_k_around_atm_mode(self, sample_chain_snapshot):
        """Test K_AROUND_ATM mode."""
        contracts = filter_contracts_by_selection_mode(
            chain_snapshot=sample_chain_snapshot,
            spot_price=100.0,
            as_of=date(2024, 3, 21),
            selection_mode="K_AROUND_ATM",
            k_strikes=2,
            include_calls=True,
            include_puts=True,
        )

        # Should have contracts for 2 expirations
        # Each expiry: 5 strikes (ATM ± 2) × 2 option types = 10 per expiry
        # Total: 20 contracts
        assert len(contracts) == 20

        # Check format: (expiry, strike, right)
        expiry, strike, right = contracts[0]
        assert isinstance(expiry, date)
        assert isinstance(strike, float)
        assert right in ["C", "P"]

    def test_moneyness_mode(self, sample_chain_snapshot):
        """Test MONEYNESS mode."""
        contracts = filter_contracts_by_selection_mode(
            chain_snapshot=sample_chain_snapshot,
            spot_price=100.0,
            as_of=date(2024, 3, 21),
            selection_mode="MONEYNESS",
            moneyness_levels=[0.95, 1.0, 1.05],
            include_calls=True,
            include_puts=False,  # Only calls
        )

        # 2 expirations × 3 moneyness levels × 1 option type (calls)
        assert len(contracts) == 6

        # All should be calls
        assert all(right == "C" for _, _, right in contracts)

    def test_all_mode(self, sample_chain_snapshot):
        """Test ALL mode."""
        contracts = filter_contracts_by_selection_mode(
            chain_snapshot=sample_chain_snapshot,
            spot_price=100.0,
            as_of=date(2024, 3, 21),
            selection_mode="ALL",
            include_calls=True,
            include_puts=True,
        )

        # 2 expirations × 5 strikes × 2 option types = 20
        assert len(contracts) == 20

    def test_calls_only(self, sample_chain_snapshot):
        """Test with calls only."""
        contracts = filter_contracts_by_selection_mode(
            chain_snapshot=sample_chain_snapshot,
            spot_price=100.0,
            as_of=date(2024, 3, 21),
            selection_mode="K_AROUND_ATM",
            k_strikes=1,
            include_calls=True,
            include_puts=False,
        )

        # Should have only calls
        assert all(right == "C" for _, _, right in contracts)

    def test_puts_only(self, sample_chain_snapshot):
        """Test with puts only."""
        contracts = filter_contracts_by_selection_mode(
            chain_snapshot=sample_chain_snapshot,
            spot_price=100.0,
            as_of=date(2024, 3, 21),
            selection_mode="K_AROUND_ATM",
            k_strikes=1,
            include_calls=False,
            include_puts=True,
        )

        # Should have only puts
        assert all(right == "P" for _, _, right in contracts)

    def test_invalid_mode_raises(self, sample_chain_snapshot):
        """Test that invalid mode raises ValueError."""
        with pytest.raises(ValueError, match="Invalid selection_mode"):
            filter_contracts_by_selection_mode(
                chain_snapshot=sample_chain_snapshot,
                spot_price=100.0,
                as_of=date(2024, 3, 21),
                selection_mode="INVALID_MODE",
            )

    def test_empty_chain_snapshot(self):
        """Test with empty chain snapshot."""
        empty_df = pd.DataFrame()

        contracts = filter_contracts_by_selection_mode(
            chain_snapshot=empty_df,
            spot_price=100.0,
            as_of=date(2024, 3, 21),
            selection_mode="K_AROUND_ATM",
            k_strikes=2,
        )

        assert contracts == []


class TestEdgeCases:
    """Test edge cases and boundary conditions."""

    def test_single_strike(self):
        """Test with only one strike available."""
        strikes = [100.0]
        spot = 100.0

        selected = select_k_around_atm(strikes, spot, k=5)
        assert selected == [100.0]

    def test_zero_spot_price(self):
        """Test behavior with zero spot price."""
        strikes = [90.0, 100.0, 110.0]
        spot = 0.0001  # Nearly zero

        # Should not crash
        selected = select_k_around_atm(strikes, spot, k=1)
        assert len(selected) > 0

    def test_very_high_volatility(self):
        """Test delta calculation with extreme volatility."""
        delta = black_scholes_call_delta(
            spot=100.0,
            strike=100.0,
            time_to_expiry=0.25,
            risk_free_rate=0.05,
            volatility=2.0,  # 200% vol
        )

        # Should still return valid delta
        assert 0.0 <= delta <= 1.0

    def test_moneyness_with_fractional_spot(self):
        """Test moneyness calculation with fractional spot price."""
        strikes = [147.5, 150.0, 152.5]
        spot = 149.99
        targets = [1.0]

        selected = select_by_moneyness(strikes, spot, targets, tolerance=0.05)

        # Should find strike closest to 150.0
        assert 150.0 in selected
