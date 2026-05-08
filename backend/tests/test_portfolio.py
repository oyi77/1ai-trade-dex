"""Tests for portfolio optimizer and strategy attribution."""
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

from backend.core.portfolio_optimizer import (
    AllocationResult,
    PortfolioOptimizer,
    StrategyMetrics,
)
from backend.core.attribution import (
    compute_attribution,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _metrics(name: str, sharpe: float) -> StrategyMetrics:
    return StrategyMetrics(
        name=name,
        total_pnl=100.0,
        trade_count=10,
        win_rate=0.6,
        sharpe_ratio=sharpe,
        max_drawdown=0.05,
        avg_edge=0.05,
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


# ---------------------------------------------------------------------------
# PortfolioOptimizer tests
# ---------------------------------------------------------------------------

class TestAllocateByShareRatio:
    """test_allocate_by_sharpe — higher Sharpe gets more weight."""

    def test_higher_sharpe_gets_more_weight(self):
        optimizer = PortfolioOptimizer()
        metrics = [_metrics("low_sharpe", 0.5), _metrics("high_sharpe", 2.0)]
        result = optimizer.allocate(metrics, bankroll=10_000)
        assert result.allocations["high_sharpe"] > result.allocations["low_sharpe"]

    def test_proportional_to_sharpe(self):
        # Use a high per-strategy cap so neither strategy is capped, allowing
        # the Sharpe-proportional weights to come through unchanged.
        optimizer = PortfolioOptimizer(max_total_exposure=0.50, max_per_strategy=0.50)
        metrics = [_metrics("a", 1.0), _metrics("b", 3.0)]
        result = optimizer.allocate(metrics, bankroll=10_000)
        # b has 3x the Sharpe so should get 3x the allocation
        ratio = result.allocations["b"] / result.allocations["a"]
        assert abs(ratio - 3.0) < 1e-6


class TestNegativeSharpeExcluded:
    """test_negative_sharpe_excluded — negative Sharpe strategies get 0 allocation."""

    def test_negative_sharpe_zero_allocation(self):
        optimizer = PortfolioOptimizer()
        metrics = [_metrics("bad", -0.5), _metrics("good", 1.5)]
        result = optimizer.allocate(metrics, bankroll=10_000)
        assert result.allocations["bad"] == 0.0
        assert result.allocations["good"] > 0.0

    def test_zero_sharpe_excluded(self):
        optimizer = PortfolioOptimizer()
        metrics = [_metrics("flat", 0.0), _metrics("good", 1.0)]
        result = optimizer.allocate(metrics, bankroll=10_000)
        assert result.allocations["flat"] == 0.0

    def test_all_negative_sharpe_returns_zero_exposure(self):
        optimizer = PortfolioOptimizer()
        metrics = [_metrics("a", -1.0), _metrics("b", -0.3)]
        result = optimizer.allocate(metrics, bankroll=10_000)
        assert result.total_exposure == 0.0
        assert all(v == 0.0 for v in result.allocations.values())


class TestExposureCap:
    """test_exposure_cap — total allocation doesn't exceed max_total_exposure."""

    def test_total_exposure_within_limit(self):
        optimizer = PortfolioOptimizer(max_total_exposure=0.50, max_per_strategy=0.30)
        metrics = [_metrics(f"s{i}", float(i + 1)) for i in range(5)]
        result = optimizer.allocate(metrics, bankroll=10_000)
        assert result.total_exposure <= 0.50 + 1e-9

    def test_single_strategy_exposure_within_limit(self):
        optimizer = PortfolioOptimizer(max_total_exposure=0.40)
        metrics = [_metrics("only", 2.0)]
        result = optimizer.allocate(metrics, bankroll=5_000)
        assert result.total_exposure <= 0.40 + 1e-9


class TestPerStrategyCap:
    """test_per_strategy_cap — no strategy exceeds max_per_strategy."""

    def test_no_strategy_exceeds_cap(self):
        optimizer = PortfolioOptimizer(max_per_strategy=0.20)
        # One dominant strategy should be capped
        metrics = [_metrics("dominant", 10.0), _metrics("small", 0.1)]
        result = optimizer.allocate(metrics, bankroll=10_000)
        for name, weight in result.allocations.items():
            assert weight <= 0.20 + 1e-9, f"{name} exceeded cap: {weight}"

    def test_cap_respected_across_many_strategies(self):
        optimizer = PortfolioOptimizer(max_total_exposure=0.50, max_per_strategy=0.10)
        metrics = [_metrics(f"s{i}", 1.0) for i in range(6)]
        result = optimizer.allocate(metrics, bankroll=10_000)
        for name, weight in result.allocations.items():
            assert weight <= 0.10 + 1e-9, f"{name} exceeded cap: {weight}"


# ---------------------------------------------------------------------------
# Attribution tests
# ---------------------------------------------------------------------------

class TestAttributionSumsTo100:
    """test_attribution_sums_to_100 — contribution_pct sums correctly."""

    def test_contribution_pct_sums_to_100(self):
        now = datetime.now(timezone.utc)
        trades = [
            _make_trade(strategy="a", pnl=30.0, timestamp=now),
            _make_trade(strategy="b", pnl=70.0, timestamp=now),
        ]
        result = compute_attribution(trades, now - timedelta(hours=1), now + timedelta(hours=1))
        total_pct = sum(a.contribution_pct for a in result)
        assert abs(total_pct - 100.0) < 1e-6

    def test_zero_total_pnl_gives_zero_contribution(self):
        now = datetime.now(timezone.utc)
        trades = [
            _make_trade(strategy="a", pnl=0.0, timestamp=now),
            _make_trade(strategy="b", pnl=0.0, timestamp=now),
        ]
        result = compute_attribution(trades, now - timedelta(hours=1), now + timedelta(hours=1))
        for a in result:
            assert a.contribution_pct == 0.0

    def test_unsettled_trades_excluded(self):
        now = datetime.now(timezone.utc)
        trades = [
            _make_trade(strategy="a", pnl=50.0, settled=True, timestamp=now),
            _make_trade(strategy="b", pnl=50.0, settled=False, timestamp=now),
        ]
        result = compute_attribution(trades, now - timedelta(hours=1), now + timedelta(hours=1))
        # Only strategy a should appear
        strategies = {a.strategy for a in result}
        assert "b" not in strategies

    def test_out_of_period_trades_excluded(self):
        now = datetime.now(timezone.utc)
        old = now - timedelta(days=10)
        trades = [
            _make_trade(strategy="a", pnl=50.0, timestamp=now),
            _make_trade(strategy="b", pnl=50.0, timestamp=old),
        ]
        result = compute_attribution(
            trades,
            now - timedelta(hours=1),
            now + timedelta(hours=1),
        )
        strategies = {a.strategy for a in result}
        assert "b" not in strategies


# ---------------------------------------------------------------------------
# Rebalance drift test
# ---------------------------------------------------------------------------

class TestRebalanceNeededDrift:
    """test_rebalance_needed_drift — detects when drift exceeds tolerance."""

    def _target(self, allocs: dict) -> AllocationResult:
        return AllocationResult(
            allocations=allocs,
            total_exposure=sum(allocs.values()),
            reasoning=[],
        )

    def test_no_rebalance_within_tolerance(self):
        optimizer = PortfolioOptimizer()
        target = self._target({"a": 0.20, "b": 0.15})
        current = {"a": 0.22, "b": 0.15}  # drift=0.02 < 0.05
        assert optimizer.rebalance_needed(current, target) is False

    def test_rebalance_when_drift_exceeds_tolerance(self):
        optimizer = PortfolioOptimizer()
        target = self._target({"a": 0.20, "b": 0.15})
        current = {"a": 0.28, "b": 0.15}  # drift=0.08 > 0.05
        assert optimizer.rebalance_needed(current, target) is True

    def test_rebalance_detects_missing_strategy(self):
        optimizer = PortfolioOptimizer()
        target = self._target({"a": 0.20, "b": 0.15})
        current = {"a": 0.20}  # b missing entirely, drift=0.15 > 0.05
        assert optimizer.rebalance_needed(current, target) is True

    def test_custom_tolerance(self):
        optimizer = PortfolioOptimizer()
        target = self._target({"a": 0.20})
        current = {"a": 0.24}  # drift=0.04
        # With tight tolerance 0.01 -> rebalance needed
        assert optimizer.rebalance_needed(current, target, drift_tolerance=0.01) is True
        # With loose tolerance 0.10 -> no rebalance
        assert optimizer.rebalance_needed(current, target, drift_tolerance=0.10) is False
