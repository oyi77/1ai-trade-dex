"""Tests for strategy replication module.

Verifies rule generation, paper simulation, config output, and confidence
scoring across profitable, losing, and edge-case source wallets.
"""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock

from backend.strategies.fingerprint import StrategyFingerprint
from backend.strategies.replication import (
    ReplicatedStrategy,
    _compute_replication_confidence,
    _decompose_rules,
    _simulate_paper,
    generate_strategy_config,
    replicate_strategy,
)


# ---------------------------------------------------------------------------
# Helpers — synthetic position builders
# ---------------------------------------------------------------------------


def _make_positions(
    n: int,
    pnl: float = 5.0,
    category_title: str = "BTC 5-minute",
    outcome: str = "YES",
    avg_price: float = 0.45,
    total_bought: float = 50.0,
) -> list[dict]:
    """Build n synthetic closed positions."""
    base_ts = 1_700_000_000
    return [
        {
            "title": category_title,
            "slug": "btc-5m",
            "eventSlug": "btc-pr",
            "outcome": outcome,
            "side": "BUY",
            "avgPrice": avg_price,
            "totalBought": total_bought,
            "realizedPnl": pnl,
            "timestamp": base_ts + i * 3600,
        }
        for i in range(n)
    ]


def _make_fp(**overrides) -> StrategyFingerprint:
    """Build a StrategyFingerprint with sensible defaults."""
    defaults = dict(
        strategy_type="SWING",
        confidence=0.7,
        primary_category="BTC_5m",
        primary_category_share=0.8,
        avg_position_size=50.0,
        size_strategy="FIXED",
        win_rate=0.55,
        profit_factor=1.5,
        sharpe_ratio=1.2,
        avg_hold_time_hours=4.0,
        hold_style="SWING",
        preferred_outcome="YES",
        preferred_side="BUY",
        avg_price_entry=0.45,
        limit_order_pct=0.3,
        max_consecutive_losses=3,
        recovery_ability=0.8,
        is_replicable=True,
        replication_difficulty="EASY",
        copy_trade_suitability=7,
    )
    defaults.update(overrides)
    return StrategyFingerprint(**defaults)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestProfitableSource:
    """A profitable wallet produces rules with positive confidence."""

    @pytest.mark.asyncio
    async def test_replicate_generates_rules(self, monkeypatch):
        positions = _make_positions(50, pnl=8.0)
        monkeypatch.setattr(
            "backend.strategies.replication.get_all_closed_positions",
            lambda wallet: _async_return(positions),
        )
        result = await replicate_strategy("0xprofit", 2000.0)
        assert len(result.rules) > 0
        assert result.confidence_score > 0
        assert isinstance(result, ReplicatedStrategy)

    @pytest.mark.asyncio
    async def test_replicate_profitable_ready_for_live(self, monkeypatch):
        positions = _make_positions(100, pnl=12.0, total_bought=80.0)
        import backend.strategies.replication as _mod
        _orig = _mod.get_all_closed_positions
        _mod.get_all_closed_positions = AsyncMock(return_value=positions)
        try:
            result = await replicate_strategy("0xgood", 2000.0)
            assert result.confidence_score > 0.7
            assert result.paper_results["pnl"] > 0
        finally:
            _mod.get_all_closed_positions = _orig


class TestLosingSource:
    """A losing wallet generates rules with low confidence, not ready for live."""

    @pytest.mark.asyncio
    async def test_losing_wallet_low_confidence(self, monkeypatch):
        positions = _make_positions(40, pnl=-3.0)
        import backend.strategies.replication as _mod
        _orig = _mod.get_all_closed_positions
        _mod.get_all_closed_positions = AsyncMock(return_value=positions)
        try:
            result = await replicate_strategy("0xbad", 2000.0)
            assert result.paper_results["pnl"] < 0
            assert result.is_ready_for_live is False
        finally:
            _mod.get_all_closed_positions = _orig


class TestRuleGeneration:
    """Rule decomposition respects fingerprint patterns."""

    def test_btc_specialist_gets_btc_category_rule(self):
        fp = _make_fp(primary_category="BTC_5m")
        positions = _make_positions(30)
        rules = _decompose_rules(fp, positions)
        assert len(rules) > 0
        category_rules = [r for r in rules if "BTC_5m" in r.condition]
        assert len(category_rules) > 0
        assert category_rules[0].action == "BUY"

    def test_scalper_gets_short_hold_exit(self):
        fp = _make_fp(
            hold_style="SCALPER",
            avg_hold_time_hours=0.3,
            strategy_type="SCALPER",
        )
        rules = _decompose_rules(fp, _make_positions(20))
        hold_rules = [r for r in rules if "hold_time" in r.condition]
        assert len(hold_rules) > 0

    def test_neutral_outcome_defaults_to_yes(self):
        fp = _make_fp(preferred_outcome="NEUTRAL")
        rules = _decompose_rules(fp, _make_positions(20))
        assert len(rules) > 0
        assert rules[0].outcome == "YES"


class TestPaperSimulation:
    """Paper simulation produces correct PnL curve from historical data."""

    def test_simulation_basic(self):
        positions = _make_positions(20, pnl=5.0)
        result = _simulate_paper(positions, [{"dummy": True}], 1000.0)
        assert result["total_trades"] == 20
        assert result["wins"] == 20
        assert result["losses"] == 0
        assert result["pnl"] == 100.0
        assert result["win_rate"] == 1.0

    def test_simulation_mixed_pnl(self):
        positions = _make_positions(10, pnl=5.0)
        positions.extend(_make_positions(5, pnl=-10.0))
        result = _simulate_paper(positions, [{"dummy": True}], 1000.0)
        assert result["wins"] == 10
        assert result["losses"] == 5
        assert result["pnl"] == 0.0  # 10*5 + 5*(-10) = 0
        assert result["max_drawdown"] > 0

    def test_simulation_empty(self):
        result = _simulate_paper([], [], 1000.0)
        assert result["total_trades"] == 0
        assert result["pnl"] == 0.0


class TestConfigFormat:
    """Generated config is a dict with required keys."""

    def test_config_has_required_keys(self):
        fp = _make_fp()
        config = generate_strategy_config(fp, 2000.0)
        required = {
            "name",
            "category",
            "entry_rules",
            "exit_rules",
            "position_sizing",
            "max_positions",
            "daily_budget",
        }
        assert required.issubset(config.keys())

    def test_config_category_matches_fingerprint(self):
        fp = _make_fp(primary_category="BTC_5m")
        config = generate_strategy_config(fp, 2000.0)
        assert config["category"] == "BTC_5m"

    def test_config_scalper_gets_more_positions(self):
        fp = _make_fp(strategy_type="SCALPER")
        config = generate_strategy_config(fp, 2000.0)
        assert config["max_positions"] == 10

    def test_config_whale_gets_fewer_positions(self):
        fp = _make_fp(strategy_type="WHALE")
        config = generate_strategy_config(fp, 2000.0)
        assert config["max_positions"] == 2

    def test_daily_budget_is_fraction_of_capital(self):
        fp = _make_fp()
        config = generate_strategy_config(fp, 10000.0)
        assert config["daily_budget"] == 2000.0  # 20%


class TestEmptySource:
    """Graceful handling when source wallet has no positions."""

    @pytest.mark.asyncio
    async def test_empty_wallet_returns_defaults(self, monkeypatch):
        monkeypatch.setattr(
            "backend.strategies.replication.get_all_closed_positions",
            lambda wallet: _async_return([]),
        )
        result = await replicate_strategy("0xempty", 2000.0)
        assert result.rules == []
        assert result.confidence_score == 0.0
        assert result.is_ready_for_live is False
        assert result.paper_results == {}


class TestConfidenceScoring:
    """Confidence computation edge cases."""

    def test_high_sample_high_pf(self):
        fp = _make_fp(win_rate=0.55, profit_factor=2.0, confidence=0.8)
        paper = {"pnl": 500.0}
        score = _compute_replication_confidence(fp, paper, 300)
        assert score > 0.7

    def test_low_sample_low_pf(self):
        fp = _make_fp(win_rate=0.40, profit_factor=0.8, confidence=0.2)
        paper = {"pnl": -100.0}
        score = _compute_replication_confidence(fp, paper, 5)
        assert score < 0.3

    def test_medium_scenario(self):
        fp = _make_fp(win_rate=0.52, profit_factor=1.3, confidence=0.5)
        paper = {"pnl": 50.0}
        score = _compute_replication_confidence(fp, paper, 50)
        assert 0.3 < score < 0.8


# ---------------------------------------------------------------------------
# Async helper
# ---------------------------------------------------------------------------


async def _async_return(value):
    """Helper to return a value as a coroutine."""
    return value
