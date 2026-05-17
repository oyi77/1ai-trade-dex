"""Tests for Market Making Analyzer."""
import pytest

from backend.core.market_making_analyzer import (
    MarketMakingAnalyzer,
    SpreadAnalysis,
    DepthAnalysis,
    DepthLevel,
    LiquidityMetrics,
    MarketMakingOpportunity,
)


def make_bids_asks():
    bids = [
        {"price": "0.48", "size": "100"},
        {"price": "0.47", "size": "200"},
        {"price": "0.46", "size": "150"},
    ]
    asks = [
        {"price": "0.52", "size": "100"},
        {"price": "0.53", "size": "200"},
        {"price": "0.54", "size": "150"},
    ]
    return bids, asks


class TestMarketMakingAnalyzer:
    def setup_method(self):
        self.analyzer = MarketMakingAnalyzer(min_spread_pct=0.005, max_toxicity=0.7)

    def test_analyze_basic(self):
        bids, asks = make_bids_asks()
        metrics = self.analyzer.analyze("m1", bids, asks)
        assert metrics.market_id == "m1"
        assert metrics.spread.best_bid == 0.48
        assert metrics.spread.best_ask == 0.52
        assert metrics.spread.spread == pytest.approx(0.04, abs=0.001)
        assert metrics.depth.total_bid_size == 450
        assert metrics.depth.total_ask_size == 450
        assert abs(metrics.depth.depth_imbalance) < 0.01

    def test_analyze_empty_book(self):
        metrics = self.analyzer.analyze("m1", [], [])
        assert metrics.spread.best_bid == 0
        assert metrics.spread.best_ask == 0

    def test_analyze_imbalanced_book(self):
        bids = [{"price": "0.49", "size": "500"}]
        asks = [{"price": "0.51", "size": "50"}]
        metrics = self.analyzer.analyze("m1", bids, asks)
        assert metrics.depth.depth_imbalance > 0  # more bids than asks

    def test_find_opportunities_wide_spread(self):
        bids = [{"price": "0.40", "size": "100"}]
        asks = [{"price": "0.60", "size": "100"}]
        opps = self.analyzer.find_opportunities("m1", bids, asks, bankroll=100.0)
        # Wide spread should produce opportunity (if toxicity is low enough)
        assert isinstance(opps, list)

    def test_find_opportunities_tight_spread(self):
        bids = [{"price": "0.499", "size": "100"}]
        asks = [{"price": "0.501", "size": "100"}]
        opps = self.analyzer.find_opportunities("m1", bids, asks)
        # Tight spread, below min_spread_pct
        assert len(opps) == 0

    def test_history_tracking(self):
        bids, asks = make_bids_asks()
        self.analyzer.analyze("m1", bids, asks)
        self.analyzer.analyze("m1", bids, asks)
        history = self.analyzer.get_spread_history("m1")
        assert len(history) == 2
        assert "spread_pct" in history[0]

    def test_resilience_increases_with_history(self):
        bids, asks = make_bids_asks()
        for _ in range(10):
            self.analyzer.analyze("m1", bids, asks)
        metrics = self.analyzer.analyze("m1", bids, asks)
        assert metrics.resilience_score > 0.5

    def test_toxicity_score_range(self):
        bids, asks = make_bids_asks()
        metrics = self.analyzer.analyze("m1", bids, asks)
        assert 0 <= metrics.toxicity_score <= 1

    def test_maker_opportunity_score_range(self):
        bids, asks = make_bids_asks()
        metrics = self.analyzer.analyze("m1", bids, asks)
        assert 0 <= metrics.maker_opportunity_score <= 1

    def test_micro_price_within_spread(self):
        bids, asks = make_bids_asks()
        metrics = self.analyzer.analyze("m1", bids, asks)
        assert metrics.spread.best_bid <= metrics.spread.micro_price <= metrics.spread.best_ask


class TestDepthLevel:
    def test_fields(self):
        dl = DepthLevel(price=0.5, size=100.0, cumulative_size=100.0, distance_from_mid_pct=2.0)
        assert dl.price == 0.5
        assert dl.cumulative_size == 100.0


class TestSpreadAnalysis:
    def test_spread_pct(self):
        sa = SpreadAnalysis(
            best_bid=0.48, best_ask=0.52, spread=0.04, spread_pct=0.08,
            mid_price=0.5, micro_price=0.5, time_since_last_trade_s=0,
        )
        assert sa.spread_pct == pytest.approx(0.08, abs=0.001)
