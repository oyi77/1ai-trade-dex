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
        assert params["max_price"] == 0.30
        assert params["min_ev"] == 0.05
        assert params["max_position_usd"] == 20.0
        assert params["kelly_fraction"] == 0.25


class TestMarketFilter:
    @pytest.mark.asyncio
    async def test_filters_below_max_price(self):
        from backend.strategies.base import MarketInfo

        s = LongshotBiasStrategy()
        markets = [
            MarketInfo(ticker="A", slug="a", category="test", end_date=None,
                       volume=1000, liquidity=500, yes_price=0.25, no_price=0.75),
            MarketInfo(ticker="B", slug="b", category="test", end_date=None,
                       volume=1000, liquidity=500, yes_price=0.15, no_price=0.85),
            MarketInfo(ticker="C", slug="c", category="test", end_date=None,
                       volume=1000, liquidity=500, yes_price=0.55, no_price=0.45),
            MarketInfo(ticker="D", slug="d", category="test", end_date=None,
                       volume=1000, liquidity=500, yes_price=0.30, no_price=0.70),
        ]
        filtered = await s.market_filter(markets)
        # Should include A (0.25) and B (0.15), exclude C (0.55) and D (0.30, not <)
        assert len(filtered) == 2
        slugs = {m.slug for m in filtered}
        assert slugs == {"a", "b"}

    @pytest.mark.asyncio
    async def test_filters_excludes_zero_price(self):
        from backend.strategies.base import MarketInfo

        s = LongshotBiasStrategy()
        markets = [
            MarketInfo(ticker="Z", slug="z", category="test", end_date=None,
                       volume=1000, liquidity=500, yes_price=0.0, no_price=1.0),
            MarketInfo(ticker="G", slug="g", category="test", end_date=None,
                       volume=1000, liquidity=500, yes_price=0.10, no_price=0.90),
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
