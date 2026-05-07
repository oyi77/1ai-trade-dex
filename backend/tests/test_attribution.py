"""Tests for backend/core/attribution.py — strategy metrics, max drawdown, and edge cases."""

import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

from backend.core.attribution import (
    compute_attribution,
    compute_strategy_metrics,
    _compute_max_drawdown,
)


def _make_trade(
    *,
    strategy: str = "btc",
    pnl: float = 10.0,
    result: str = "win",
    settled: bool = True,
    timestamp: datetime = None,
    edge_at_entry: float = 0.05,
) -> MagicMock:
    t = MagicMock()
    t.strategy = strategy
    t.pnl = pnl
    t.result = result
    t.settled = settled
    t.timestamp = timestamp or datetime.now(timezone.utc)
    t.edge_at_entry = edge_at_entry
    return t


NOW = datetime.now(timezone.utc)
WINDOW_START = NOW - timedelta(hours=1)
WINDOW_END = NOW + timedelta(hours=1)


class TestComputeMaxDrawdown:
    def test_empty_list_returns_zero(self):
        assert _compute_max_drawdown([]) == 0.0

    def test_only_gains_no_drawdown(self):
        assert _compute_max_drawdown([10.0, 20.0, 5.0]) == 0.0

    def test_single_loss(self):
        dd = _compute_max_drawdown([10.0, -5.0])
        assert dd == pytest.approx(5.0)

    def test_recovery_after_drawdown(self):
        dd = _compute_max_drawdown([10.0, -5.0, 20.0])
        assert dd == pytest.approx(5.0)

    def test_deeper_second_drawdown(self):
        dd = _compute_max_drawdown([10.0, -3.0, 5.0, -15.0])
        assert dd == pytest.approx(15.0)

    def test_all_losses(self):
        dd = _compute_max_drawdown([-10.0, -5.0, -3.0])
        assert dd == pytest.approx(18.0)

    def test_single_element(self):
        assert _compute_max_drawdown([5.0]) == 0.0
        assert _compute_max_drawdown([-5.0]) == pytest.approx(5.0)


class TestComputeStrategyMetrics:
    def test_basic_metrics(self):
        trades = [
            _make_trade(strategy="alpha", pnl=10.0, result="win"),
            _make_trade(strategy="alpha", pnl=-5.0, result="loss"),
            _make_trade(strategy="alpha", pnl=8.0, result="win"),
        ]
        m = compute_strategy_metrics(trades, "alpha")
        assert m.name == "alpha"
        assert m.total_pnl == pytest.approx(13.0)
        assert m.trade_count == 3
        assert m.win_rate == pytest.approx(2 / 3)
        assert m.max_drawdown >= 0.0

    def test_filters_by_strategy_name(self):
        trades = [
            _make_trade(strategy="alpha", pnl=10.0),
            _make_trade(strategy="beta", pnl=100.0),
        ]
        m = compute_strategy_metrics(trades, "alpha")
        assert m.trade_count == 1
        assert m.total_pnl == pytest.approx(10.0)

    def test_filters_unsettled_trades(self):
        trades = [
            _make_trade(strategy="alpha", pnl=10.0, settled=True),
            _make_trade(strategy="alpha", pnl=50.0, settled=False),
        ]
        m = compute_strategy_metrics(trades, "alpha")
        assert m.trade_count == 1
        assert m.total_pnl == pytest.approx(10.0)

    def test_empty_trades_returns_zeros(self):
        m = compute_strategy_metrics([], "alpha")
        assert m.trade_count == 0
        assert m.total_pnl == 0.0
        assert m.win_rate == 0.0
        assert m.sharpe_ratio == 0.0
        assert m.max_drawdown == 0.0
        assert m.avg_edge == 0.0

    def test_single_trade_sharpe_is_zero(self):
        trades = [_make_trade(strategy="alpha", pnl=10.0)]
        m = compute_strategy_metrics(trades, "alpha")
        assert m.sharpe_ratio == 0.0

    def test_sharpe_positive_for_consistent_gains(self):
        trades = [
            _make_trade(strategy="alpha", pnl=10.0, result="win"),
            _make_trade(strategy="alpha", pnl=12.0, result="win"),
            _make_trade(strategy="alpha", pnl=11.0, result="win"),
        ]
        m = compute_strategy_metrics(trades, "alpha")
        assert m.sharpe_ratio > 0.0

    def test_sharpe_zero_when_identical_pnl(self):
        trades = [
            _make_trade(strategy="alpha", pnl=10.0, result="win"),
            _make_trade(strategy="alpha", pnl=10.0, result="win"),
        ]
        m = compute_strategy_metrics(trades, "alpha")
        assert m.sharpe_ratio == 0.0

    def test_avg_edge_computed(self):
        trades = [
            _make_trade(strategy="alpha", pnl=10.0, edge_at_entry=0.10),
            _make_trade(strategy="alpha", pnl=5.0, edge_at_entry=0.06),
        ]
        m = compute_strategy_metrics(trades, "alpha")
        assert m.avg_edge == pytest.approx(0.08)

    def test_avg_edge_ignores_none_edges(self):
        trades = [
            _make_trade(strategy="alpha", pnl=10.0, edge_at_entry=0.10),
            _make_trade(strategy="alpha", pnl=5.0, edge_at_entry=None),
        ]
        m = compute_strategy_metrics(trades, "alpha")
        assert m.avg_edge == pytest.approx(0.10)

    def test_no_strategy_match_returns_zeros(self):
        trades = [_make_trade(strategy="beta", pnl=10.0)]
        m = compute_strategy_metrics(trades, "alpha")
        assert m.trade_count == 0


class TestComputeAttributionEdgeCases:
    def test_negative_pnl_attribution(self):
        trades = [
            _make_trade(strategy="a", pnl=-30.0, timestamp=NOW),
            _make_trade(strategy="b", pnl=-70.0, timestamp=NOW),
        ]
        result = compute_attribution(trades, WINDOW_START, WINDOW_END)
        total_pct = sum(a.contribution_pct for a in result)
        assert abs(total_pct - 100.0) < 1e-6

    def test_mixed_positive_negative_pnl(self):
        trades = [
            _make_trade(strategy="a", pnl=100.0, timestamp=NOW),
            _make_trade(strategy="b", pnl=-50.0, timestamp=NOW),
        ]
        result = compute_attribution(trades, WINDOW_START, WINDOW_END)
        by_name = {a.strategy: a for a in result}
        assert by_name["a"].contribution_pct == pytest.approx(200.0)
        assert by_name["b"].contribution_pct == pytest.approx(-100.0)

    def test_empty_trades(self):
        result = compute_attribution([], WINDOW_START, WINDOW_END)
        assert result == []

    def test_single_strategy(self):
        trades = [_make_trade(strategy="solo", pnl=42.0, timestamp=NOW)]
        result = compute_attribution(trades, WINDOW_START, WINDOW_END)
        assert len(result) == 1
        assert result[0].strategy == "solo"
        assert result[0].contribution_pct == pytest.approx(100.0)

    def test_none_strategy_grouped_as_unknown(self):
        t = _make_trade(pnl=10.0, timestamp=NOW)
        t.strategy = None
        result = compute_attribution([t], WINDOW_START, WINDOW_END)
        assert result[0].strategy == "unknown"

    def test_win_rate_calculated_correctly(self):
        trades = [
            _make_trade(strategy="a", pnl=10.0, result="win", timestamp=NOW),
            _make_trade(strategy="a", pnl=-5.0, result="loss", timestamp=NOW),
            _make_trade(strategy="a", pnl=3.0, result="win", timestamp=NOW),
        ]
        result = compute_attribution(trades, WINDOW_START, WINDOW_END)
        assert result[0].period_win_rate == pytest.approx(2 / 3)
        assert result[0].period_trades == 3
