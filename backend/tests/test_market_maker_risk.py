"""Tests for market maker risk controls: adverse selection, exposure limits, spread threshold."""

from __future__ import annotations

import pytest

from backend.strategies.market_maker import MarketMakerStrategy


@pytest.fixture
def mm():
    m = MarketMakerStrategy()
    m._halted = False
    return m


class TestAdverseSelection:
    """Adverse fill detection and halt logic."""

    def test_buy_above_mid_is_adverse(self, mm: MarketMakerStrategy):
        mm.record_fill("m1", "BUY", 0.55, 10, 0.50)
        assert mm._adverse_streak == 1

    def test_sell_below_mid_is_adverse(self, mm: MarketMakerStrategy):
        mm.record_fill("m1", "SELL", 0.45, 10, 0.50)
        assert mm._adverse_streak == 1

    def test_buy_below_mid_is_not_adverse(self, mm: MarketMakerStrategy):
        mm.record_fill("m1", "BUY", 0.45, 10, 0.50)
        assert mm._adverse_streak == 0

    def test_sell_above_mid_is_not_adverse(self, mm: MarketMakerStrategy):
        mm.record_fill("m1", "SELL", 0.55, 10, 0.50)
        assert mm._adverse_streak == 0

    def test_good_fill_resets_streak(self, mm: MarketMakerStrategy):
        mm.record_fill("m1", "BUY", 0.55, 10, 0.50)  # adverse
        mm.record_fill("m1", "BUY", 0.55, 10, 0.50)  # adverse
        assert mm._adverse_streak == 2
        mm.record_fill("m1", "BUY", 0.45, 10, 0.50)  # good
        assert mm._adverse_streak == 0

    def test_halt_after_max_streak(self, mm: MarketMakerStrategy):
        for _ in range(3):
            mm.record_fill("m1", "BUY", 0.55, 10, 0.50)
        assert mm._adverse_streak == 3
        assert mm._halted is True

    def test_no_halt_before_max_streak(self, mm: MarketMakerStrategy):
        for _ in range(2):
            mm.record_fill("m1", "BUY", 0.55, 10, 0.50)
        assert mm._adverse_streak == 2
        assert mm._halted is False


class TestExposureLimit:
    """USD exposure limit checks."""

    def test_under_limit(self, mm: MarketMakerStrategy):
        mm._total_exposure_usd = 50.0
        assert mm._check_exposure_limit() is True

    def test_at_limit(self, mm: MarketMakerStrategy):
        mm._total_exposure_usd = 100.0
        assert mm._check_exposure_limit() is False

    def test_over_limit(self, mm: MarketMakerStrategy):
        mm._total_exposure_usd = 150.0
        assert mm._check_exposure_limit() is False

    def test_exposure_accumulates(self, mm: MarketMakerStrategy):
        mm.record_fill("m1", "BUY", 0.50, 10, 0.50)  # $5
        mm.record_fill("m1", "SELL", 0.60, 10, 0.50)  # $6
        assert mm._total_exposure_usd == 11.0


class TestRiskParams:
    """Verify production risk parameters are set correctly."""

    def test_max_inventory_50(self, mm: MarketMakerStrategy):
        assert mm.default_params["max_inventory"] == 50.0

    def test_max_exposure_100(self, mm: MarketMakerStrategy):
        assert mm.default_params["max_total_exposure_usd"] == 100.0

    def test_max_adverse_streak_3(self, mm: MarketMakerStrategy):
        assert mm.default_params["max_adverse_streak"] == 3

    def test_min_spread_3pct(self, mm: MarketMakerStrategy):
        assert mm.default_params["min_spread"] == 0.03

    def test_quote_timeout_30s(self, mm: MarketMakerStrategy):
        assert mm.default_params["quote_max_age_seconds"] == 30.0
