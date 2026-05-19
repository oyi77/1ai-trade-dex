"""Tests for backend.strategies.opportunity_detector.

Covers all five detector types and the composite scanner.
"""

import pytest

from backend.strategies.opportunity_detector import (
    resolve_market_odds,
    detect_price_discrepancy,
    detect_momentum,
    detect_liquidity_gap,
    detect_event_driven,
    detect_emotional_trading,
    scan_for_opportunities,
)


# ---------------------------------------------------------------------------
# resolve_market_odds
# ---------------------------------------------------------------------------

class TestResolveMarketOdds:
    def test_basic_resolution(self):
        odds = resolve_market_odds(yes_price=0.55, no_price=0.40)
        # mid = (0.55 + (1 - 0.40)) / 2 = (0.55 + 0.60) / 2 = 0.575
        assert odds.mid_price == pytest.approx(0.575, abs=1e-4)
        assert odds.best_bid == pytest.approx(0.55, abs=1e-4)
        assert odds.best_ask == pytest.approx(0.40, abs=1e-4)
        # spread = 0.55 + 0.40 - 1.0 = -0.05 (negative = underpriced)
        assert odds.spread == pytest.approx(-0.05, abs=1e-4)
        assert odds.fair_value == pytest.approx(0.575, abs=1e-4)

    def test_with_depth(self):
        odds = resolve_market_odds(0.60, 0.35, bid_depth=5000, ask_depth=3000)
        assert odds.depth_bid_usd == 5000
        assert odds.depth_ask_usd == 3000

    def test_fair_price_combined_equals_one(self):
        """When YES + NO = 1.0 the spread is zero and mid is YES price."""
        odds = resolve_market_odds(0.50, 0.50)
        assert odds.spread == pytest.approx(0.0, abs=1e-6)
        assert odds.mid_price == pytest.approx(0.50, abs=1e-4)


# ---------------------------------------------------------------------------
# Type 1 — Price discrepancy
# ---------------------------------------------------------------------------

class TestDetectPriceDiscrepancy:
    def test_discrepancy_detected(self):
        """YES=0.45 + NO=0.45 = 0.90 < 0.98 -> opportunity."""
        opp = detect_price_discrepancy(0.45, 0.45)
        assert opp is not None
        assert opp.type == "price_discrepancy"
        assert opp.expected_value == pytest.approx(0.10, abs=1e-4)
        assert opp.confidence > 0
        assert opp.details["combined"] == pytest.approx(0.90, abs=1e-4)

    def test_no_discrepancy(self):
        """YES=0.55 + NO=0.46 = 1.01 > 0.98 -> no opportunity."""
        opp = detect_price_discrepancy(0.55, 0.46)
        assert opp is None

    def test_edge_at_threshold(self):
        """Combined exactly 0.98 -> no opportunity (not strictly less)."""
        opp = detect_price_discrepancy(0.50, 0.48)
        assert opp is None

    def test_just_below_threshold(self):
        """Combined = 0.9799 -> opportunity."""
        opp = detect_price_discrepancy(0.50, 0.4799)
        assert opp is not None
        assert opp.type == "price_discrepancy"

    def test_large_edge_high_confidence(self):
        """10% edge should hit max confidence (1.0)."""
        opp = detect_price_discrepancy(0.40, 0.40)  # combined=0.80, edge=0.20
        assert opp is not None
        assert opp.confidence == 1.0

    def test_passes_market_info(self):
        opp = detect_price_discrepancy(0.45, 0.45, market_id="abc", market_title="Test")
        assert opp.market_id == "abc"
        assert opp.market_title == "Test"


# ---------------------------------------------------------------------------
# Type 2 — Momentum
# ---------------------------------------------------------------------------

class TestDetectMomentum:
    def test_momentum_detected(self):
        """Price moved 8% in 1h -> opportunity."""
        base_price = 0.50
        prices = [base_price, base_price * 1.03, base_price * 1.05, base_price * 1.08]
        t0 = 1000.0
        timestamps = [t0, t0 + 900, t0 + 1800, t0 + 2700]  # all within 1h
        opp = detect_momentum(prices, timestamps)
        assert opp is not None
        assert opp.type == "momentum"
        assert opp.details["change_pct"] == pytest.approx(8.0, abs=0.5)

    def test_no_momentum_small_move(self):
        """Price moved only 2% -> no opportunity."""
        base_price = 0.50
        prices = [base_price, base_price * 1.01, base_price * 1.02]
        t0 = 1000.0
        timestamps = [t0, t0 + 1800, t0 + 3600]
        opp = detect_momentum(prices, timestamps)
        assert opp is None

    def test_momentum_window_too_long(self):
        """Movement spread over >1h should not trigger."""
        base_price = 0.50
        prices = [base_price, base_price * 1.08]
        timestamps = [1000.0, 5000.0]  # 4000 sec > 3600
        opp = detect_momentum(prices, timestamps)
        assert opp is None

    def test_insufficient_data(self):
        assert detect_momentum([0.50], [1000.0]) is None
        assert detect_momentum([], []) is None

    def test_mismatched_lengths(self):
        assert detect_momentum([0.50, 0.55], [1000.0]) is None


# ---------------------------------------------------------------------------
# Type 3 — Liquidity gap
# ---------------------------------------------------------------------------

class TestDetectLiquidityGap:
    def test_gap_detected(self):
        """Spread=8c, volume=$5000 -> opportunity."""
        opp = detect_liquidity_gap(8.0, {"volume": 5000})
        assert opp is not None
        assert opp.type == "liquidity_gap"
        assert opp.details["spread_cents"] == 8.0

    def test_no_gap_tight_spread(self):
        """Spread=2c -> no opportunity even with high volume."""
        opp = detect_liquidity_gap(2.0, {"volume": 5000})
        assert opp is None

    def test_no_gap_low_volume(self):
        """Spread=8c but volume=$500 -> no opportunity."""
        opp = detect_liquidity_gap(8.0, {"volume": 500})
        assert opp is None

    def test_at_threshold(self):
        """Spread exactly 5c -> no opportunity (strictly greater required)."""
        opp = detect_liquidity_gap(5.0, {"volume": 5000})
        assert opp is None

    def test_just_above_threshold(self):
        opp = detect_liquidity_gap(5.01, {"volume": 1000})
        assert opp is not None


# ---------------------------------------------------------------------------
# Type 4 — Event-driven (placeholder)
# ---------------------------------------------------------------------------

class TestDetectEventDriven:
    def test_always_returns_none(self):
        assert detect_event_driven({}) is None
        assert detect_event_driven({"headline": "big news"}) is None


# ---------------------------------------------------------------------------
# Type 5 — Emotional trading
# ---------------------------------------------------------------------------

class TestDetectEmotionalTrading:
    def test_spike_then_revert(self):
        """Price spikes 12% then reverts 60% of that move."""
        base = 0.50
        spike = base * 1.12   # 0.56
        revert = spike - (spike - base) * 0.60  # 0.56 - 0.036 = 0.524
        prices = [base, spike, revert]
        timestamps = [1000.0, 1500.0, 2500.0]
        opp = detect_emotional_trading(prices, timestamps)
        assert opp is not None
        assert opp.type == "emotional_trading"
        assert opp.details["spike_pct"] == pytest.approx(12.0, abs=1.0)

    def test_no_spike(self):
        """Only 5% move -> no emotional opportunity."""
        base = 0.50
        prices = [base, base * 1.05, base * 1.02]
        timestamps = [1000.0, 1500.0, 2500.0]
        assert detect_emotional_trading(prices, timestamps) is None

    def test_spike_no_revert(self):
        """Spike 15% but no reversion -> no opportunity."""
        base = 0.50
        spike = base * 1.15
        prices = [base, spike, spike * 1.01]
        timestamps = [1000.0, 1500.0, 2500.0]
        assert detect_emotional_trading(prices, timestamps) is None

    def test_insufficient_data(self):
        assert detect_emotional_trading([0.50, 0.55], [1000.0, 1500.0]) is None
        assert detect_emotional_trading([], []) is None


# ---------------------------------------------------------------------------
# Composite scanner
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_scan_empty_markets():
    result = await scan_for_opportunities([])
    assert result == []

@pytest.mark.asyncio
async def test_scan_none_markets():
    result = await scan_for_opportunities(None)
    assert result == []

@pytest.mark.asyncio
async def test_scan_finds_multiple_types():
    """Scanner should detect price discrepancy and liquidity gap in one pass."""
    markets = [
        {
            "condition_id": "m1",
            "question": "Arb market",
            "yes_price": 0.45,
            "no_price": 0.45,
            "volume": 5000,
            "spread_cents": 8.0,
        },
    ]
    result = await scan_for_opportunities(markets)
    types = {o.type for o in result}
    assert "price_discrepancy" in types
    assert "liquidity_gap" in types

@pytest.mark.asyncio
async def test_scan_sorted_by_expected_value():
    """Results should be sorted descending by expected_value."""
    markets = [
        {
            "condition_id": "m1",
            "question": "Small edge",
            "yes_price": 0.48,
            "no_price": 0.48,
        },
        {
            "condition_id": "m2",
            "question": "Big edge",
            "yes_price": 0.40,
            "no_price": 0.40,
        },
    ]
    result = await scan_for_opportunities(markets)
    assert len(result) >= 2
    for i in range(len(result) - 1):
        assert result[i].expected_value >= result[i + 1].expected_value

@pytest.mark.asyncio
async def test_scan_no_opportunities_clean_market():
    """Market with no edges returns empty."""
    markets = [
        {
            "condition_id": "m1",
            "question": "Fair market",
            "yes_price": 0.55,
            "no_price": 0.46,
            "spread_cents": 2.0,
            "volume": 5000,
        },
    ]
    result = await scan_for_opportunities(markets)
    assert result == []
