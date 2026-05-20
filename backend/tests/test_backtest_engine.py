"""Tests for Enhanced Backtest Engine."""

import pytest
from datetime import datetime, timezone, timedelta

from backend.core.backtest_engine import (
    EnhancedBacktestEngine,
    EnhancedBacktestConfig,
)


def make_config(strategies=None, **kwargs):
    return EnhancedBacktestConfig(
        strategies=strategies or ["test_strategy"],
        start_date=datetime.now(timezone.utc) - timedelta(days=30),
        end_date=datetime.now(timezone.utc),
        initial_bankroll=100.0,
        monte_carlo_sims=kwargs.pop("monte_carlo_sims", 100),
        **kwargs,
    )


class TestStrategyComparisonResult:
    def test_empty_result(self):
        r = EnhancedBacktestEngine._empty_result("test")
        assert r.strategy_name == "test"
        assert r.total_trades == 0
        assert r.win_rate == 0.0
        assert r.total_pnl == 0.0


class TestEnhancedBacktestEngine:
    def test_init(self):
        config = make_config()
        engine = EnhancedBacktestEngine(config)
        assert engine.config.strategies == ["test_strategy"]

    def test_simulate_signals_basic(self):
        config = make_config()
        engine = EnhancedBacktestEngine(config)
        signals = [
            {
                "timestamp": datetime.now(timezone.utc),
                "price": 0.5,
                "edge": 0.05,
                "size": 10.0,
                "pnl": 0.5,
            },
            {
                "timestamp": datetime.now(timezone.utc),
                "price": 0.5,
                "edge": 0.03,
                "size": 10.0,
                "pnl": -0.3,
            },
            {
                "timestamp": datetime.now(timezone.utc),
                "price": 0.5,
                "edge": 0.04,
                "size": 10.0,
                "pnl": 0.8,
            },
        ]
        result = engine._simulate_signals(signals, "test")
        assert result.total_trades == 3
        assert result.winning_trades == 2
        assert result.win_rate == pytest.approx(2 / 3, abs=0.01)
        assert result.strategy_name == "test"

    def test_simulate_signals_empty(self):
        config = make_config()
        engine = EnhancedBacktestEngine(config)
        result = engine._simulate_signals([], "empty")
        assert result.total_trades == 0
        assert result.win_rate == 0.0

    def test_split_walk_forward(self):
        config = make_config(walk_forward_folds=3, train_ratio=0.7)
        engine = EnhancedBacktestEngine(config)
        signals = [{"pnl": i * 0.1} for i in range(30)]
        folds = engine._split_walk_forward(signals)
        assert len(folds) == 3
        for train, test in folds:
            assert len(train) > 0
            assert len(test) > 0

    @pytest.mark.asyncio
    async def test_compare_strategies_no_db(self):
        config = make_config(strategies=["s1", "s2"])
        engine = EnhancedBacktestEngine(config)
        # Without DB, _fetch_signals will fail but should return empty results
        results = await engine.compare_strategies(db=None)
        # Should not crash, may return empty
        assert isinstance(results, list)

    @pytest.mark.asyncio
    async def test_monte_carlo_with_pnl_list(self):
        config = make_config(monte_carlo_sims=50)
        engine = EnhancedBacktestEngine(config)
        # Monkey-patch _fetch_signals to return synthetic data
        engine._fetch_signals = lambda name, db=None: [
            {"pnl": 0.5},
            {"pnl": -0.3},
            {"pnl": 0.8},
            {"pnl": 0.1},
            {"pnl": -0.2},
        ]
        result = await engine.monte_carlo_simulate("test")
        assert result.simulations == 50
        assert result.probability_of_profit > 0
        assert result.percentile_5 < result.percentile_95

    @pytest.mark.asyncio
    async def test_monte_carlo_no_signals(self):
        config = make_config()
        engine = EnhancedBacktestEngine(config)
        engine._fetch_signals = lambda name, db=None: []
        result = await engine.monte_carlo_simulate("test")
        assert result.simulations == 0
