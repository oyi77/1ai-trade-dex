"""Tests for APEX strategy integration."""

from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock

import pytest

from backend.core.edge.edge_types import EdgeType
from backend.core.edge.edge_model import Signal as APEXSignal


class TestAPEXStrategy:
    @pytest.fixture
    def strategy(self):
        from backend.strategies.apex_strategy import APEXStrategy
        return APEXStrategy()

    def test_name_and_category(self, strategy):
        assert strategy.name == "apex"
        assert strategy.category == "value"

    def test_default_params(self, strategy):
        assert "min_edge_pp" in strategy.default_params
        assert "min_confidence" in strategy.default_params
        assert "max_concurrent" in strategy.default_params

    def test_signal_to_decision_high_edge(self, strategy):
        """High edge signal produces a valid decision."""
        sig = APEXSignal(
            market_id="TEST",
            token_id="0x1",
            edge_type=EdgeType.RESOLUTION_TIMING,
            direction="yes",
            entry_price=0.55,
            fair_price=0.65,
            edge_pp=10.0,
            confidence=0.75,
            edge_score=7.5,
            size_usd=8.0,
            expected_value=0.80,
            time_horizon_min=60,
            profit_target_pct=0.025,
            stop_loss_pct=0.04,
            max_hold_seconds=3600,
        )
        ctx = MagicMock()
        ctx.params = {}
        ctx.bankroll = 100.0

        decision = strategy._signal_to_decision(sig, ctx)
        assert decision is not None
        assert decision["strategy_name"] == "apex"
        assert decision["decision"] == "BUY"

    def test_signal_to_decision_low_confidence_filtered(self, strategy):
        sig = APEXSignal(
            market_id="TEST", token_id="0x1",
            edge_type=EdgeType.RESOLUTION_TIMING,
            direction="yes", entry_price=0.55, fair_price=0.60,
            edge_pp=5.0, confidence=0.3, edge_score=1.5,
            size_usd=5.0, expected_value=0.25,
            time_horizon_min=60,
            profit_target_pct=0.025, stop_loss_pct=0.04,
            max_hold_seconds=3600,
        )
        ctx = MagicMock()
        ctx.params = {}
        ctx.bankroll = 100.0
        decision = strategy._signal_to_decision(sig, ctx)
        assert decision is None

    def test_signal_to_decision_low_edge_filtered(self, strategy):
        sig = APEXSignal(
            market_id="TEST", token_id="0x1",
            edge_type=EdgeType.RESOLUTION_TIMING,
            direction="yes", entry_price=0.55, fair_price=0.57,
            edge_pp=1.5, confidence=0.8, edge_score=1.2,
            size_usd=5.0, expected_value=0.075,
            time_horizon_min=60,
            profit_target_pct=0.025, stop_loss_pct=0.04,
            max_hold_seconds=3600,
        )
        ctx = MagicMock()
        ctx.params = {}
        ctx.bankroll = 100.0
        decision = strategy._signal_to_decision(sig, ctx)
        assert decision is None

    def test_signal_to_decision_position_sizing(self, strategy):
        sig = APEXSignal(
            market_id="TEST", token_id="0x1",
            edge_type=EdgeType.RESOLUTION_TIMING,
            direction="yes", entry_price=0.55, fair_price=0.65,
            edge_pp=10.0, confidence=0.75, edge_score=7.5,
            size_usd=80.0, expected_value=8.0,
            time_horizon_min=60,
            profit_target_pct=0.025, stop_loss_pct=0.04,
            max_hold_seconds=3600,
        )
        ctx = MagicMock()
        ctx.params = {}
        ctx.bankroll = 1000.0
        decision = strategy._signal_to_decision(sig, ctx)
        assert decision is not None
        # size_usd should be capped at bankroll_pct * bankroll = 0.08 * 1000 = 80
        assert decision["size"] == 80.0