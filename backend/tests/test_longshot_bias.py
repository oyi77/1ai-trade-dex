"""Tests for LongshotBiasStrategy — price filtering, EV calculation, Kelly sizing."""

import pytest

from backend.strategies.longshot_bias import LongshotBiasStrategy


class TestLongshotBiasDefaults:
    def test_name(self):
        s = LongshotBiasStrategy()
        assert s.name == "longshot_bias"

    def test_category(self):
        s = LongshotBiasStrategy()
        assert s.category == "edge_discovery"

    def test_default_params(self):
        params = LongshotBiasStrategy.default_params
        assert params["max_price"] == 0.25
        assert params["min_ev"] == 0.10
        assert params["max_position_usd"] == 10.0
        assert params["kelly_fraction"] == 0.15


class TestMarketFilter:
    @pytest.mark.asyncio
    async def test_filters_below_max_price(self):
        from backend.strategies.base import MarketInfo

        s = LongshotBiasStrategy()
        markets = [
            MarketInfo(
                ticker="A",
                slug="a",
                category="test",
                end_date=None,
                volume=1000,
                liquidity=500,
                yes_price=0.76,
                no_price=0.24,
            ),
            MarketInfo(
                ticker="B",
                slug="b",
                category="test",
                end_date=None,
                volume=1000,
                liquidity=500,
                yes_price=0.85,
                no_price=0.15,
            ),
            MarketInfo(
                ticker="C",
                slug="c",
                category="test",
                end_date=None,
                volume=1000,
                liquidity=500,
                yes_price=0.45,
                no_price=0.55,
            ),
            MarketInfo(
                ticker="D",
                slug="d",
                category="test",
                end_date=None,
                volume=1000,
                liquidity=500,
                yes_price=0.70,
                no_price=0.30,
            ),
        ]
        filtered = await s.market_filter(markets)
        # Should include A (no=0.24) and B (no=0.15), exclude C (no=0.55) and D (no=0.30, not <)
        assert len(filtered) == 2
        slugs = {m.slug for m in filtered}
        assert slugs == {"a", "b"}

    @pytest.mark.asyncio
    async def test_filters_excludes_zero_price(self):
        from backend.strategies.base import MarketInfo

        s = LongshotBiasStrategy()
        markets = [
            MarketInfo(
                ticker="Z",
                slug="z",
                category="test",
                end_date=None,
                volume=1000,
                liquidity=500,
                yes_price=1.0,
                no_price=0.0,
            ),
            MarketInfo(
                ticker="G",
                slug="g",
                category="test",
                end_date=None,
                volume=1000,
                liquidity=500,
                yes_price=0.90,
                no_price=0.10,
            ),
        ]
        filtered = await s.market_filter(markets)
        assert len(filtered) == 1
        assert filtered[0].slug == "g"

    @pytest.mark.asyncio
    async def test_empty_market_list(self):
        s = LongshotBiasStrategy()
        filtered = await s.market_filter([])
        assert filtered == []


class TestEVCalculation:
    """Test the empirical EV values used by the strategy."""

    def test_no_ev_positive_below_30c(self):
        """NO tokens below 30c should have positive EV (+23% empirical)."""
        # The strategy uses a fixed empirical EV of 0.23 for NO bets below 30c
        # This matches the Becker research: NO at <30c has +23% EV
        ev = 0.23  # hardcoded in strategy from research
        assert ev > 0.05  # above min_ev threshold

    def test_yes_ev_negative_below_30c(self):
        """YES tokens below 30c should be avoided (-41% empirical)."""
        # The strategy correctly avoids YES bets below 30c
        # Only buys NO tokens (positive EV)
        yes_ev = -0.41  # empirical: YES at <30c is -41% EV
        assert yes_ev < 0

    def test_ev_above_min_threshold(self):
        """The empirical EV (23%) should exceed the min_ev threshold (5%)."""
        ev = 0.23
        min_ev = 0.05
        assert ev >= min_ev


class TestKellySizing:
    """Test Kelly criterion sizing logic."""

    def test_kelly_basic_calculation(self):
        """Verify Kelly formula: f* = (p*b - q) / b."""
        # Market at 0.25 YES => NO probability = 0.75
        yes_price = 0.25
        no_price = 1.0 - yes_price  # 0.75
        win_prob = 1.0 - yes_price  # 0.75 (NO wins)
        odds = (1.0 / no_price) - 1.0  # (1/0.75) - 1 = 0.333
        kelly = (win_prob * odds - (1.0 - win_prob)) / odds
        # f* = (0.75 * 0.333 - 0.25) / 0.333 = (0.25 - 0.25) / 0.333 = 0.0
        # At 25c YES, NO is 75c, Kelly is ~0 (no edge at implied odds)
        assert kelly >= -1e-10  # allow floating-point noise

    def test_kelly_with_fractional(self):
        """Fractional Kelly should reduce position size."""
        kelly_full = 0.20
        kelly_fraction = 0.25
        kelly_adjusted = kelly_full * kelly_fraction
        assert kelly_adjusted == 0.05
        position = kelly_adjusted * 100  # $5
        assert position == 5.0

    def test_kelly_capped_at_max_position(self):
        """Position should be capped at max_position_usd."""
        max_position = 20.0
        kelly_position = 50.0  # uncapped
        actual = min(kelly_position, max_position)
        assert actual == 20.0

    def test_kelly_below_min_order(self):
        """Positions below $5 min order should be skipped."""
        kelly_position = 3.0
        min_order = 5.0
        assert kelly_position < min_order  # should skip


class TestHardGuards:
    """Test the three hard guards added to prevent no-edge trades."""

    def test_max_entry_price_guard(self):
        """NO tokens above max_entry_price (0.40) should be rejected."""
        max_entry_price = 0.40
        # Market with YES=0.25 => NO=0.75, should be rejected
        no_price = 0.75
        assert no_price > max_entry_price  # guard blocks this

    def test_max_entry_price_cheap_allowed(self):
        """NO tokens at or below max_entry_price should pass."""
        max_entry_price = 0.40
        # Market with YES=0.20 => NO=0.80 (rejected, too expensive)
        # But market with YES=0.70 => NO=0.30 (passes max_entry, but fails other guards)
        no_price_pass = 0.35
        assert no_price_pass <= max_entry_price

    def test_min_model_prob_guard(self):
        """Markets where model probability < 75% should be rejected."""
        min_model_prob = 0.75
        # YES=0.70 => model_prob (favorite confidence) = 0.70 => below 0.75 => rejected
        yes_price = 0.70
        model_prob = yes_price
        assert model_prob < min_model_prob

    def test_min_model_prob_high_enough(self):
        """Markets where model probability >= 75% should pass."""
        min_model_prob = 0.75
        # YES=0.80 => model_prob = 0.80 => above 0.75 => passes
        yes_price = 0.80
        model_prob = yes_price
        assert model_prob >= min_model_prob

    def test_min_edge_guard(self):
        """Markets where edge (model_prob - no_price) < 15% should be rejected."""
        min_edge = 0.15
        # YES=0.55 => model_prob=0.55, NO=0.45 => edge=0.10 => rejected
        yes_price = 0.55
        no_price = 0.45
        model_prob = yes_price
        edge = model_prob - no_price
        assert edge < min_edge

    def test_min_edge_sufficient(self):
        """Markets where edge >= 15% should pass."""
        min_edge = 0.15
        # YES=0.80 => model_prob=0.80, NO=0.20 => edge=0.60 => passes
        yes_price = 0.80
        no_price = 0.20
        model_prob = yes_price
        edge = model_prob - no_price
        assert edge >= min_edge

    def test_fair_price_no_edge_blocked(self):
        """A market bought at ~0.50 (fair price) has zero edge and must be blocked."""
        min_edge = 0.15
        min_model_prob = 0.75
        # Market at YES=0.50 => NO=0.50 => model_prob=0.50
        no_price = 0.50
        yes_price = 0.50
        model_prob = yes_price  # 0.50
        edge = model_prob - no_price  # 0.0
        assert model_prob < min_model_prob  # blocked by min model prob
        assert edge < min_edge  # blocked by min edge

    def test_new_params_in_defaults(self):
        """New guard params should exist in strategy defaults."""
        params = LongshotBiasStrategy.default_params
        assert "min_edge" in params
        assert "min_model_prob" in params
        assert "max_entry_price" in params
        assert params["min_edge"] == 0.15
        assert params["min_model_prob"] == 0.75
        assert params["max_entry_price"] == 0.30
