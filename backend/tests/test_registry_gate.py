"""Tests for registry performance gate (REGISTRY_MIN_WIN_RATE / REGISTRY_MIN_ROI)."""
from __future__ import annotations

import pytest

from backend.strategies.registry import (
    STRATEGY_REGISTRY,
    _check_performance_gate,
    _extract_metric,
    _extract_win_rate,
    create_strategy,
    BaseStrategy,
)


class _BadStrategy(BaseStrategy):
    name = "_test_bad_perf"
    description = "4W/11L, -49.5% ROI test strategy"
    category = "test"
    default_params = {}

    async def run_cycle(self, ctx):
        pass


class _GoodStrategy(BaseStrategy):
    name = "_test_good_perf"
    description = "Solid strategy"
    category = "test"
    default_params = {}

    async def run_cycle(self, ctx):
        pass


def test_extract_roi():
    assert _extract_metric("ROI: -49.5%", "roi") == pytest.approx(-0.495)
    assert _extract_metric("no metric here", "roi") is None
    assert _extract_metric("ROI: 25.3%", "roi") == pytest.approx(0.253)


def test_extract_win_rate():
    assert _extract_win_rate("4W/11L") == pytest.approx(4.0 / 15.0)
    assert _extract_win_rate("no record") is None


def test_performance_gate_rejects_bad_strategy():
    from backend.strategies.registry import _extract_metric, _extract_win_rate
    roi = _extract_metric("4W/11L, -49.5% ROI test strategy", "roi")
    win_rate = _extract_win_rate("4W/11L, -49.5% ROI test strategy")
    assert roi is not None and roi < -0.30
    assert win_rate is not None and win_rate < 0.30
    if "_test_bad_perf" in STRATEGY_REGISTRY:
        with pytest.raises(ValueError, match="below threshold"):
            _check_performance_gate("_test_bad_perf")


def test_performance_gate_silent_good_strategy(caplog):
    with caplog.at_level("WARNING"):
        _check_performance_gate("_test_good_perf")
    assert not any("below threshold" in r.message.lower() for r in caplog.records)


def test_create_strategy_force_enable():
    if "_test_bad_perf" in STRATEGY_REGISTRY:
        strategy = create_strategy("_test_bad_perf", force_enable=True)
        assert strategy is not None
