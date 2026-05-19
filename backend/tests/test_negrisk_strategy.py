"""Tests for negrisk_strategy: detection, fair probability, order construction."""
import pytest

from backend.strategies.negrisk_strategy import (
    NegRiskEvent,
    FairProbResult,
    calculate_fair_probabilities,
    calculate_kelly_bets,
    detect_neg_risk_events,
    construct_orders,
)


# ---------------------------------------------------------------------------
# Fair probability tests
# ---------------------------------------------------------------------------


class TestFairProbabilities:
    def test_normalized_probabilities_sum_to_one(self):
        """Fair probs must always sum to 1.0."""
        prices = [0.30, 0.40, 0.20]
        fair = calculate_fair_probabilities(prices)
        assert abs(sum(fair) - 1.0) < 1e-9

    def test_already_fair_market_unchanged(self):
        """When prices already sum to 1.0, fair probs equal market probs."""
        prices = [0.25, 0.25, 0.25, 0.25]
        fair = calculate_fair_probabilities(prices)
        for f, p in zip(fair, prices):
            assert abs(f - p) < 1e-9

    def test_underpriced_sum_normalizes_up(self):
        """When sum < 1.0, each fair prob should be higher than market."""
        prices = [0.20, 0.20, 0.20]  # sum = 0.60
        fair = calculate_fair_probabilities(prices)
        assert all(f > p for f, p in zip(fair, prices))
        assert abs(sum(fair) - 1.0) < 1e-9

    def test_overpriced_sum_normalizes_down(self):
        """When sum > 1.0, each fair prob should be lower than market."""
        prices = [0.40, 0.40, 0.40]  # sum = 1.20
        fair = calculate_fair_probabilities(prices)
        assert all(f < p for f, p in zip(fair, prices))
        assert abs(sum(fair) - 1.0) < 1e-9

    def test_zero_sum_returns_uniform(self):
        """Zero sum returns uniform distribution."""
        prices = [0.0, 0.0, 0.0]
        fair = calculate_fair_probabilities(prices)
        assert len(fair) == 3
        assert all(abs(f - 1 / 3) < 1e-9 for f in fair)

    def test_two_outcomes(self):
        """Works for binary markets."""
        prices = [0.60, 0.50]  # sum = 1.10
        fair = calculate_fair_probabilities(prices)
        assert abs(fair[0] - 0.60 / 1.10) < 1e-9
        assert abs(fair[1] - 0.50 / 1.10) < 1e-9


# ---------------------------------------------------------------------------
# Kelly bet tests
# ---------------------------------------------------------------------------


class TestKellyBets:
    def test_positive_edge_produces_positive_bet(self):
        """When fair > market Kelly should produce a positive bet."""
        fair_probs = [0.40, 0.35, 0.25]
        market_probs = [0.20, 0.20, 0.20]  # all underpriced (fair > market)
        bets = calculate_kelly_bets(fair_probs, market_probs, bankroll=100.0)
        assert all(b > 0 for b in bets)

    def test_no_edge_produces_zero_bet(self):
        """When fair == market Kelly should be zero."""
        probs = [0.33, 0.33, 0.34]
        bets = calculate_kelly_bets(probs, probs, bankroll=100.0)
        assert all(b == 0.0 for b in bets)

    def test_negative_edge_produces_zero_bet(self):
        """When fair < market (overpriced) Kelly should be zero."""
        fair_probs = [0.20, 0.20, 0.20]
        market_probs = [0.40, 0.40, 0.40]
        bets = calculate_kelly_bets(fair_probs, market_probs, bankroll=100.0)
        assert all(b == 0.0 for b in bets)

    def test_kelly_fraction_scales_bets(self):
        """Higher kelly_fraction should produce larger bets."""
        fair_probs = [0.40, 0.35, 0.25]
        market_probs = [0.30, 0.30, 0.30]
        bets_low = calculate_kelly_bets(
            fair_probs, market_probs, bankroll=100.0, kelly_fraction=0.10
        )
        bets_high = calculate_kelly_bets(
            fair_probs, market_probs, bankroll=100.0, kelly_fraction=0.50
        )
        for lo, hi in zip(bets_low, bets_high):
            assert hi >= lo

    def test_bets_capped_at_max_bet_frac(self):
        """No bet should exceed max_bet_frac * bankroll."""
        bankroll = 1000.0
        max_frac = 0.10
        fair_probs = [0.90, 0.05, 0.05]
        market_probs = [0.30, 0.30, 0.30]
        bets = calculate_kelly_bets(
            fair_probs,
            market_probs,
            bankroll=bankroll,
            kelly_fraction=1.0,
            max_bet_frac=max_frac,
        )
        cap = max_frac * bankroll
        assert all(b <= cap + 0.01 for b in bets)

    def test_extreme_market_price_skipped(self):
        """Market price near 0 or 1 should produce zero bet."""
        fair_probs = [0.50, 0.50]
        market_probs = [0.005, 0.995]
        bets = calculate_kelly_bets(fair_probs, market_probs, bankroll=100.0)
        assert bets == [0.0, 0.0]


# ---------------------------------------------------------------------------
# Event detection tests
# ---------------------------------------------------------------------------


class TestDetectNegRiskEvents:
    def _make_market(self, slug, question, yes_price, no_price=0.5, token_id="tok"):
        return {
            "slug": slug,
            "question": question,
            "yes_price": yes_price,
            "no_price": no_price,
            "token_id": token_id,
            "market_id": token_id,
        }

    def test_detects_event_with_sum_above_one(self):
        """3 outcomes summing > 1.0 should be detected."""
        markets = [
            self._make_market("who-wins", "Alice", 0.40),
            self._make_market("who-wins", "Bob", 0.40),
            self._make_market("who-wins", "Carol", 0.30),
        ]
        events = detect_neg_risk_events(markets, min_outcomes=3, min_sum_deviation=0.01)
        assert len(events) == 1
        assert events[0].event_id == "who-wins"
        assert events[0].num_outcomes == 3
        assert events[0].sum_of_prices == pytest.approx(1.10)
        assert events[0].deviation == pytest.approx(0.10)

    def test_detects_event_with_sum_below_one(self):
        """3 outcomes summing < 1.0 should also be detected."""
        markets = [
            self._make_market("who-wins", "A", 0.20),
            self._make_market("who-wins", "B", 0.20),
            self._make_market("who-wins", "C", 0.20),
        ]
        events = detect_neg_risk_events(markets, min_outcomes=3, min_sum_deviation=0.01)
        assert len(events) == 1
        assert events[0].deviation == pytest.approx(0.40)

    def test_ignores_two_outcome_events(self):
        """Events with < min_outcomes should be skipped."""
        markets = [
            self._make_market("binary", "Yes", 0.55),
            self._make_market("binary", "No", 0.50),
        ]
        events = detect_neg_risk_events(markets, min_outcomes=3)
        assert len(events) == 0

    def test_ignores_fairly_priced_events(self):
        """Events with sum close to 1.0 should be skipped."""
        markets = [
            self._make_market("fair", "A", 0.33),
            self._make_market("fair", "B", 0.34),
            self._make_market("fair", "C", 0.33),
        ]
        events = detect_neg_risk_events(markets, min_outcomes=3, min_sum_deviation=0.02)
        assert len(events) == 0

    def test_sorted_by_deviation_desc(self):
        """Events should be sorted by deviation, highest first."""
        markets_low = [
            self._make_market("low", "A", 0.34),
            self._make_market("low", "B", 0.34),
            self._make_market("low", "C", 0.34),
        ]
        markets_high = [
            self._make_market("high", "A", 0.40),
            self._make_market("high", "B", 0.40),
            self._make_market("high", "C", 0.40),
        ]
        events = detect_neg_risk_events(
            markets_low + markets_high, min_outcomes=3, min_sum_deviation=0.01
        )
        assert len(events) == 2
        assert events[0].event_id == "high"
        assert events[1].event_id == "low"

    def test_multiple_events_detected(self):
        """Multiple distinct slugs produce multiple events."""
        markets = [
            self._make_market("evt-a", "A1", 0.40),
            self._make_market("evt-a", "A2", 0.40),
            self._make_market("evt-a", "A3", 0.30),
            self._make_market("evt-b", "B1", 0.30),
            self._make_market("evt-b", "B2", 0.30),
            self._make_market("evt-b", "B3", 0.30),
        ]
        events = detect_neg_risk_events(markets, min_outcomes=3, min_sum_deviation=0.01)
        slugs = {e.event_id for e in events}
        assert "evt-a" in slugs
        assert "evt-b" in slugs


# ---------------------------------------------------------------------------
# Order construction tests
# ---------------------------------------------------------------------------


class TestConstructOrders:
    def _make_event_and_result(self, prices, fair_probs, kelly_bets):
        outcomes = [
            {
                "label": f"Outcome {i}",
                "token_id": f"tok_{i}",
                "yes_price": p,
                "no_price": 1.0 - p,
            }
            for i, p in enumerate(prices)
        ]
        event = NegRiskEvent(
            event_id="test-event",
            slug="test-event",
            question="Test",
            outcomes=outcomes,
            sum_of_prices=sum(prices),
            deviation=abs(sum(prices) - 1.0),
            num_outcomes=len(prices),
        )
        mispricings = [f - m for f, m in zip(fair_probs, prices)]
        fair_result = FairProbResult(
            event_id="test-event",
            fair_probs=fair_probs,
            market_probs=prices,
            mispricings=mispricings,
            sum_deviation=abs(sum(prices) - 1.0),
            kelly_bets=kelly_bets,
        )
        return event, fair_result

    def test_constructs_buy_orders_for_underpriced(self):
        """Underpriced outcomes should produce BUY orders."""
        prices = [0.30, 0.30, 0.30]
        fair_probs = [0.333, 0.333, 0.334]
        kelly_bets = [10.0, 10.0, 10.0]
        event, result = self._make_event_and_result(prices, fair_probs, kelly_bets)

        orders = construct_orders(event, result, min_edge=0.01, max_position_usd=50.0)
        assert len(orders) == 3
        for o in orders:
            assert o.side == "BUY"
            assert o.size_usd > 0

    def test_no_orders_when_no_edge(self):
        """No orders when mispricing < min_edge."""
        prices = [0.33, 0.34, 0.33]
        fair_probs = [0.333, 0.334, 0.333]
        kelly_bets = [5.0, 5.0, 5.0]
        event, result = self._make_event_and_result(prices, fair_probs, kelly_bets)

        orders = construct_orders(event, result, min_edge=0.05, max_position_usd=50.0)
        assert len(orders) == 0

    def test_no_orders_when_kelly_zero(self):
        """No orders when Kelly bet is zero."""
        prices = [0.30, 0.30, 0.30]
        fair_probs = [0.35, 0.35, 0.30]
        kelly_bets = [0.0, 0.0, 0.0]
        event, result = self._make_event_and_result(prices, fair_probs, kelly_bets)

        orders = construct_orders(event, result, min_edge=0.01, max_position_usd=50.0)
        assert len(orders) == 0

    def test_size_capped_at_max_position(self):
        """Order size should not exceed max_position_usd."""
        prices = [0.20, 0.20, 0.20]
        fair_probs = [0.333, 0.333, 0.334]
        kelly_bets = [100.0, 100.0, 100.0]  # large Kelly
        event, result = self._make_event_and_result(prices, fair_probs, kelly_bets)

        orders = construct_orders(event, result, min_edge=0.01, max_position_usd=25.0)
        for o in orders:
            assert o.size_usd <= 25.0

    def test_overpriced_outcome_gets_no_buy(self):
        """Overpriced outcomes (edge < 0) should produce BUY NO orders."""
        prices = [0.50, 0.50, 0.50]  # sum = 1.50, all overpriced
        fair_probs = [0.333, 0.333, 0.334]
        kelly_bets = [10.0, 10.0, 10.0]
        event, result = self._make_event_and_result(prices, fair_probs, kelly_bets)

        orders = construct_orders(event, result, min_edge=0.01, max_position_usd=50.0)
        # All overpriced -> BUY NO (at no_price)
        assert len(orders) == 3
        for o in orders:
            assert o.side == "BUY"
            assert o.edge > 0


# ---------------------------------------------------------------------------
# Integration: full pipeline
# ---------------------------------------------------------------------------


class TestFullPipeline:
    def test_end_to_end_underpriced_event(self):
        """Full pipeline: detect -> fair prob -> Kelly -> orders."""
        markets = [
            {"slug": "election", "question": "Alice", "yes_price": 0.25, "no_price": 0.80, "token_id": "t0"},
            {"slug": "election", "question": "Bob", "yes_price": 0.25, "no_price": 0.80, "token_id": "t1"},
            {"slug": "election", "question": "Carol", "yes_price": 0.25, "no_price": 0.80, "token_id": "t2"},
        ]

        # Step 1: detect
        events = detect_neg_risk_events(markets, min_outcomes=3, min_sum_deviation=0.01)
        assert len(events) == 1
        event = events[0]
        assert event.sum_of_prices == pytest.approx(0.75)
        assert event.deviation == pytest.approx(0.25)

        # Step 2: fair probs
        outcome_prices = [o["yes_price"] for o in event.outcomes]
        fair_probs = calculate_fair_probabilities(outcome_prices)
        assert abs(sum(fair_probs) - 1.0) < 1e-9
        assert all(fp > mp for fp, mp in zip(fair_probs, outcome_prices))

        # Step 3: Kelly
        kelly_bets = calculate_kelly_bets(
            fair_probs, outcome_prices, bankroll=500.0, kelly_fraction=0.25
        )
        assert all(b > 0 for b in kelly_bets)

        # Step 4: construct orders
        mispricings = [f - m for f, m in zip(fair_probs, outcome_prices)]
        fair_result = FairProbResult(
            event_id=event.event_id,
            fair_probs=fair_probs,
            market_probs=outcome_prices,
            mispricings=mispricings,
            sum_deviation=event.deviation,
            kelly_bets=kelly_bets,
        )
        orders = construct_orders(event, fair_result, min_edge=0.02, max_position_usd=50.0)
        assert len(orders) == 3
        for o in orders:
            assert o.side == "BUY"
            assert o.event_id == "election"
            assert o.token_id.startswith("t")
