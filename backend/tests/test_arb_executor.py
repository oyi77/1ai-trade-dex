"""Tests for arb_executor detection functions."""
from backend.strategies.arb_executor import (
    detect_intra_market_arb,
    detect_cross_platform_arb,
    detect_negrisk_arb,
)


def test_intra_market_arb_detected():
    """YES=0.45, NO=0.45 sums to 0.90 < 0.96 threshold — arb exists."""
    opp = detect_intra_market_arb(yes_price=0.45, no_price=0.45, fee_rate=0.02, market_id="m1")
    assert opp is not None
    assert opp.arb_type == "intra_market"
    assert opp.market_id == "m1"
    assert opp.spread > 0
    # total=0.90, threshold=0.96, spread=0.06
    assert abs(opp.spread - 0.06) < 1e-9


def test_intra_market_no_arb():
    """YES=0.50, NO=0.52 sums to 1.02 >= 0.96 threshold — no arb."""
    opp = detect_intra_market_arb(yes_price=0.50, no_price=0.52, fee_rate=0.02, market_id="m2")
    assert opp is None


def test_cross_platform_arb_detected():
    """poly=0.60, kalshi=0.45 -> raw spread=0.15, net=0.11 > min_spread=0.03."""
    opp = detect_cross_platform_arb(
        poly_price=0.60,
        kalshi_price=0.45,
        min_spread=0.03,
        fee_rate=0.02,
        market_id="cx1",
    )
    assert opp is not None
    assert opp.arb_type == "cross_platform"
    assert opp.market_id == "cx1"
    # net_spread = 0.15 - 0.04 = 0.11
    assert abs(opp.spread - 0.11) < 1e-9
    assert opp.details["buy_on"] == "kalshi"


def test_cross_platform_no_arb():
    """poly=0.50, kalshi=0.49 -> spread too small after fees."""
    opp = detect_cross_platform_arb(
        poly_price=0.50,
        kalshi_price=0.49,
        min_spread=0.03,
        fee_rate=0.02,
        market_id="cx2",
    )
    assert opp is None


def test_negrisk_arb_detected():
    """3 outcomes summing to 0.90 — deviation=0.10, fees=0.06, profit=0.04."""
    opp = detect_negrisk_arb(
        outcome_prices=[0.30, 0.30, 0.30],
        fee_rate=0.02,
        market_id="nr1",
        min_deviation=0.02,
    )
    assert opp is not None
    assert opp.arb_type == "negrisk"
    assert opp.market_id == "nr1"
    # sum=0.90, deviation=0.10, total_fees=0.06, profit=0.04
    assert abs(opp.spread - 0.04) < 1e-9
    assert opp.details["direction"] == "buy_all_yes"


def test_negrisk_no_arb_when_sum_near_one():
    """Outcomes nearly sum to 1.0 — no meaningful arb after fees."""
    opp = detect_negrisk_arb(
        outcome_prices=[0.33, 0.34, 0.33],
        fee_rate=0.02,
        market_id="nr2",
        min_deviation=0.02,
    )
    assert opp is None
