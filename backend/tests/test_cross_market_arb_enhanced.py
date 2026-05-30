"""Tests for CrossMarketArbEnhanced — multi-provider arbitrage detection."""

import pytest
from backend.strategies.cross_market_arb_enhanced import (
    CrossMarketArbEnhanced,
    ArbOpportunityEnhanced,
    ScanResult,
    _questions_match,
    _normalize_number,
    _normalize_crypto_tokens,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def detector():
    return CrossMarketArbEnhanced(
        poly_fee_pct=0.02,
        kalshi_fee_pct=0.07,
        slippage_bps=5.0,
        min_net_profit_pct=0.01,
        max_execution_risk=0.5,
    )


def _make_market(
    question="Will BTC reach 100k?",
    yes_price=0.50,
    no_price=0.50,
    event_id="evt1",
    platform="polymarket",
    slug="btc-100k",
    fee_pct=0.02,
    clob_token_ids=None,
):
    return {
        "question": question,
        "yes_price": yes_price,
        "no_price": no_price,
        "event_id": event_id,
        "platform": platform,
        "slug": slug,
        "fee_pct": fee_pct,
        "clobTokenIds": clob_token_ids or [],
    }


# ---------------------------------------------------------------------------
# YES/NO Sum Arbitrage
# ---------------------------------------------------------------------------


class TestYesNoSum:
    def test_detects_underpriced_sum(self, detector):
        """YES + NO < 1.0 after fees should detect arb."""
        market = _make_market(yes_price=0.45, no_price=0.45)
        opp = detector.detect_yes_no_sum(market)
        assert opp is not None
        assert opp.kind == "yes_no_sum"
        assert opp.net_profit > 0

    def test_no_arb_when_sum_near_one(self, detector):
        """YES + NO = 1.0 should not detect arb."""
        market = _make_market(yes_price=0.50, no_price=0.50)
        opp = detector.detect_yes_no_sum(market)
        assert opp is None

    def test_no_arb_when_sum_above_one(self, detector):
        """YES + NO > 1.0 should not detect arb."""
        market = _make_market(yes_price=0.60, no_price=0.50)
        opp = detector.detect_yes_no_sum(market)
        assert opp is None

    def test_none_prices_returns_none(self, detector):
        """Missing prices should return None."""
        market = _make_market(yes_price=None, no_price=None)
        opp = detector.detect_yes_no_sum(market)
        assert opp is None

    def test_zero_prices_returns_none(self, detector):
        """Zero or negative prices should return None."""
        market = _make_market(yes_price=0.0, no_price=0.50)
        opp = detector.detect_yes_no_sum(market)
        assert opp is None

    def test_small_spread_below_threshold(self, detector):
        """Spread below min_net_profit_pct is filtered out."""
        # YES=0.49, NO=0.49 => sum=0.98, spread=0.02
        # fees=0.02, slippage=0.001, net=0.02-0.02-0.001 < 0
        market = _make_market(yes_price=0.49, no_price=0.49)
        opp = detector.detect_yes_no_sum(market)
        assert opp is None


# ---------------------------------------------------------------------------
# Complementary / Multi-Outcome Detection
# ---------------------------------------------------------------------------


class TestComplementary:
    def test_detects_multi_outcome_arb(self, detector):
        """Multiple outcomes with YES prices summing < 1.0 is an arb."""
        markets = [
            _make_market(yes_price=0.30, event_id="evt1", platform="polymarket"),
            _make_market(yes_price=0.30, event_id="evt1", platform="polymarket"),
            _make_market(yes_price=0.30, event_id="evt1", platform="polymarket"),
        ]
        opps = detector.detect_complementary(markets)
        assert len(opps) >= 1
        assert opps[0].kind == "multi_outcome"

    def test_no_arb_when_sum_near_one(self, detector):
        """Outcomes summing to 1.0 -> no arb."""
        markets = [
            _make_market(yes_price=0.50, event_id="evt1"),
            _make_market(yes_price=0.50, event_id="evt1"),
        ]
        opps = detector.detect_complementary(markets)
        assert len(opps) == 0

    def test_single_outcome_no_complementary(self, detector):
        """Single outcome cannot be complementary."""
        markets = [_make_market(yes_price=0.30, event_id="evt1")]
        opps = detector.detect_complementary(markets)
        assert len(opps) == 0

    def test_different_event_ids_no_arb(self, detector):
        """Markets with different event_ids don't form complementary arb."""
        markets = [
            _make_market(yes_price=0.30, event_id="evt1"),
            _make_market(yes_price=0.30, event_id="evt2"),
        ]
        opps = detector.detect_complementary(markets)
        assert len(opps) == 0


# ---------------------------------------------------------------------------
# Cross-Platform Detection
# ---------------------------------------------------------------------------


class TestCrossPlatform:
    def test_detects_cross_platform_arb(self, detector):
        """Same question on two platforms with YES + YES < 1.0."""
        poly = [_make_market(yes_price=0.45, platform="polymarket", event_id="evt1", slug="btc-100k")]
        kalshi = [_make_market(yes_price=0.45, platform="kalshi", event_id="evt1", slug="btc-100k")]
        opps = detector.detect_cross_platform_generic(poly, kalshi)
        assert len(opps) >= 1
        assert opps[0].platform_a == "polymarket"
        assert opps[0].platform_b == "kalshi"

    def test_no_arb_when_sum_above_one(self, detector):
        """YES + YES >= 1.0 -> no arb."""
        poly = [_make_market(yes_price=0.55, platform="polymarket", event_id="evt1", slug="btc-100k")]
        kalshi = [_make_market(yes_price=0.55, platform="kalshi", event_id="evt1", slug="btc-100k")]
        opps = detector.detect_cross_platform_generic(poly, kalshi)
        assert len(opps) == 0

    def test_empty_market_sets(self, detector):
        """Empty market lists return no opps."""
        assert detector.detect_cross_platform_generic([], [_make_market()]) == []
        assert detector.detect_cross_platform_generic([_make_market()], []) == []

    def test_fuzzy_question_matching(self, detector):
        """Questions with similar words match across platforms."""
        poly = [_make_market(
            question="Will Bitcoin price exceed $100,000?",
            yes_price=0.40, platform="polymarket", event_id="", slug=""
        )]
        kalshi = [_make_market(
            question="Bitcoin price above $100000?",
            yes_price=0.40, platform="kalshi", event_id="", slug=""
        )]
        opps = detector.detect_cross_platform_generic(poly, kalshi)
        assert len(opps) >= 1

    def test_unrelated_questions_no_match(self, detector):
        """Completely different questions don't match."""
        poly = [_make_market(
            question="Will Bitcoin reach 100k?",
            yes_price=0.40, platform="polymarket", event_id="", slug=""
        )]
        kalshi = [_make_market(
            question="Will it rain in Tokyo tomorrow?",
            yes_price=0.40, platform="kalshi", event_id="", slug=""
        )]
        opps = detector.detect_cross_platform_generic(poly, kalshi)
        assert len(opps) == 0


# ---------------------------------------------------------------------------
# Same-Game Correlation Detection
# ---------------------------------------------------------------------------


class TestSameGameCorrelation:
    def test_detects_moneyline_arb(self, detector):
        """Two moneyline bets on same game with complementary pricing."""
        markets = [
            {
                "question": "Lakers vs Celtics",
                "yes_price": 0.40,
                "event_id": "ml1",
                "platform": "sxbet",
                "_raw": {"outcomeOneName": "Lakers"},
            },
            {
                "question": "Lakers vs Celtics",
                "yes_price": 0.40,
                "event_id": "ml2",
                "platform": "sxbet",
                "_raw": {"outcomeOneName": "Celtics"},
            },
        ]
        opps = detector.detect_same_game_correlation(markets)
        assert len(opps) >= 1

    def test_no_game_key_excluded(self, detector):
        """Markets without ' vs ' in question are excluded."""
        markets = [
            {"question": "Bitcoin above 100k?", "yes_price": 0.50, "event_id": "e1"},
            {"question": "Bitcoin above 100k?", "yes_price": 0.50, "event_id": "e2"},
        ]
        opps = detector.detect_same_game_correlation(markets)
        assert len(opps) == 0

    def test_empty_markets(self, detector):
        assert detector.detect_same_game_correlation([]) == []


# ---------------------------------------------------------------------------
# Cross-Timeframe Arbitrage
# ---------------------------------------------------------------------------


class TestCrossTimeframe:
    def test_detects_timeframe_arb(self, detector):
        """BTC 5-min YES cheap + BTC 15-min NO cheap."""
        markets = [
            _make_market(
                question="Will BTC be above 100k in 5 min?",
                yes_price=0.80,
                no_price=0.20,
                event_id="evt5m",
                platform="polymarket",
            ),
            _make_market(
                question="Will BTC be above 100k in 15 min?",
                yes_price=0.05,
                no_price=0.95,
                event_id="evt15m",
                platform="polymarket",
            ),
        ]
        opps = detector.detect_cross_timeframe_arb(markets)
        # YES(5m)=0.80 + NO(15m)=0.95 => sum=1.75, not arb
        # NO(5m)=0.20 + YES(15m)=0.05 => sum=0.25 < 0.96 => arb!
        assert len(opps) >= 1
        assert opps[0].kind == "cross_timeframe"

    def test_no_timeframe_no_arb(self, detector):
        """Markets without timeframe info don't produce timeframe arbs."""
        markets = [
            _make_market(question="Will something happen?", yes_price=0.40, event_id="evt1"),
            _make_market(question="Will something else happen?", yes_price=0.40, event_id="evt2"),
        ]
        opps = detector.detect_cross_timeframe_arb(markets)
        assert len(opps) == 0

    def test_empty_markets(self, detector):
        assert detector.detect_cross_timeframe_arb([]) == []


# ---------------------------------------------------------------------------
# scan_all_providers integration
# ---------------------------------------------------------------------------


class TestScanAllProviders:
    def test_scan_returns_scan_result(self, detector):
        """scan_all_providers returns a ScanResult."""
        all_markets = {
            "polymarket": [_make_market(yes_price=0.45, no_price=0.45)],
        }
        result = detector.scan_all_providers(all_markets)
        assert isinstance(result, ScanResult)
        assert result.markets_scanned == 1

    def test_scan_detects_yes_no_arb(self, detector):
        """Scan detects YES/NO sum arb within a single provider."""
        all_markets = {
            "polymarket": [_make_market(yes_price=0.45, no_price=0.45)],
        }
        result = detector.scan_all_providers(all_markets)
        assert len(result.opportunities) >= 1

    def test_scan_empty_providers(self, detector):
        """Empty providers dict returns zero markets scanned."""
        result = detector.scan_all_providers({})
        assert result.markets_scanned == 0
        assert len(result.opportunities) == 0

    def test_scan_multiple_providers(self, detector):
        """Cross-platform arb detected between two providers."""
        all_markets = {
            "polymarket": [_make_market(yes_price=0.40, platform="polymarket", event_id="evt1", slug="btc-100k")],
            "kalshi": [_make_market(yes_price=0.40, platform="kalshi", event_id="evt1", slug="btc-100k")],
        }
        result = detector.scan_all_providers(all_markets)
        cross_opps = [o for o in result.opportunities if "cross_platform" in o.kind]
        assert len(cross_opps) >= 1

    def test_scan_respects_execution_risk_filter(self, detector):
        """Opportunities above max_execution_risk are filtered out."""
        detector.max_execution_risk = 0.0  # Filter everything out
        all_markets = {
            "polymarket": [_make_market(yes_price=0.45, no_price=0.45)],
        }
        result = detector.scan_all_providers(all_markets)
        assert len(result.opportunities) == 0

    def test_opportunities_sorted_by_net_profit(self, detector):
        """Results are sorted by net_profit descending."""
        all_markets = {
            "polymarket": [
                _make_market(yes_price=0.40, no_price=0.40, event_id="evt1", slug="big-arb"),
                _make_market(yes_price=0.48, no_price=0.48, event_id="evt2", slug="small-arb"),
            ],
        }
        result = detector.scan_all_providers(all_markets)
        if len(result.opportunities) >= 2:
            for i in range(len(result.opportunities) - 1):
                assert result.opportunities[i].net_profit >= result.opportunities[i + 1].net_profit


# ---------------------------------------------------------------------------
# Legacy scan_all
# ---------------------------------------------------------------------------


class TestLegacyScanAll:
    def test_scan_all_delegates_to_scan_all_providers(self, detector):
        poly = [_make_market(yes_price=0.45, no_price=0.45)]
        result = detector.scan_all(poly_markets=poly)
        assert isinstance(result, ScanResult)
        assert result.markets_scanned == 1

    def test_scan_all_with_kalshi(self, detector):
        poly = [_make_market(yes_price=0.45, no_price=0.45, platform="polymarket")]
        kalshi = [_make_market(yes_price=0.45, no_price=0.45, platform="kalshi")]
        result = detector.scan_all(poly_markets=poly, kalshi_markets=kalshi)
        assert result.markets_scanned == 2


# ---------------------------------------------------------------------------
# Question matching
# ---------------------------------------------------------------------------


class TestQuestionMatching:
    def test_exact_match(self):
        assert _questions_match("Will BTC reach 100k?", "Will BTC reach 100k?")

    def test_similar_match(self):
        assert _questions_match("Bitcoin above $100,000?", "BTC over $100000")

    def test_different_no_match(self):
        assert not _questions_match("Will it rain tomorrow?", "Bitcoin above 100k")

    def test_short_questions_no_match(self):
        """Questions with fewer than 2 meaningful words should not match."""
        assert not _questions_match("Yes?", "No?")

    def test_stop_words_filtered(self):
        """Stop words are filtered out for matching."""
        q1 = "Will the price of Bitcoin go above 100k"
        q2 = "Bitcoin price above 100k"
        assert _questions_match(q1, q2)


# ---------------------------------------------------------------------------
# Number normalization
# ---------------------------------------------------------------------------


class TestNormalization:
    def test_thousands(self):
        assert "100000" in _normalize_number("$100,000")

    def test_k_suffix(self):
        assert "100000" in _normalize_number("100k")

    def test_m_suffix(self):
        assert "1000000" in _normalize_number("1m")

    def test_crypto_synonyms(self):
        result = _normalize_crypto_tokens("bitcoin price above")
        assert "btc" in result

    def test_ethereum_synonym(self):
        result = _normalize_crypto_tokens("ethereum merge")
        assert "eth" in result


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------


class TestHelperFunctions:
    def test_are_opposite_bets_over_under(self):
        from backend.strategies.cross_market_arb_enhanced import CrossMarketArbEnhanced
        assert CrossMarketArbEnhanced._are_opposite_bets("Over 48.5", "Under 48.5")

    def test_are_opposite_bets_spread(self):
        from backend.strategies.cross_market_arb_enhanced import CrossMarketArbEnhanced
        assert CrossMarketArbEnhanced._are_opposite_bets("Lakers +3.5", "Celtics -3.5")

    def test_are_not_opposite(self):
        from backend.strategies.cross_market_arb_enhanced import CrossMarketArbEnhanced
        assert not CrossMarketArbEnhanced._are_opposite_bets("Over 48.5", "Under 50.5")

    def test_is_moneyline(self, detector):
        m = {"_raw": {"outcomeOneName": "Lakers"}}
        assert detector._is_moneyline(m)

    def test_is_spread(self, detector):
        m = {"_raw": {"outcomeOneName": "Lakers +3.5"}}
        assert detector._is_spread(m)

    def test_is_total(self, detector):
        m = {"_raw": {"outcomeOneName": "Over 48.5"}}
        assert detector._is_total(m)
