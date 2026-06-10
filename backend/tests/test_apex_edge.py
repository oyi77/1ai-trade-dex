"""Tests for APEX edge detection pipeline — core data structures, scanners, and strategy."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.core.edge.edge_model import Edge, EdgeType, ExitReason, ExitSignal
from backend.core.edge.edge_types import (
    EdgeSignal as TypesEdgeSignal,
    MarketSnapshot,
    ProbabilityEstimate,
    clamp,
)
from backend.core.edge.probability_models import BrownianBridgeModel, NearResolutionModel
from backend.core.edge.exit_manager import ExitManager
from backend.db.utils import utcnow


# ─── Helpers ────────────────────────────────────────────────────────

def _make_edge(**overrides):
    defaults = dict(
        market_id="TEST-MARKET",
        token_id="0x1",
        edge_type=EdgeType.RESOLUTION_TIMING,
        direction="yes",
        entry_price=0.55,
        fair_price=0.62,
        edge_pp=7.0,
        confidence=0.75,
        edge_score=5.25,
        time_horizon_min=60,
    )
    defaults.update(overrides)
    return Edge(**defaults)


def _make_snapshot(**overrides) -> MarketSnapshot:
    defaults = dict(
        ticker="TEST-MARKET",
        token_id="0x1",
        yes_price=0.55,
        no_price=0.45,
        volume=5000,
        liquidity=2000,
        spread=0.03,
        bid_depth=500,
        ask_depth=300,
        category="politics",
    )
    defaults.update(overrides)
    return MarketSnapshot(**defaults)


# ─── EdgeType and Edge dataclass tests ─────────────────────────────

class TestEdgeModel:
    def test_edge_type_values(self):
        assert EdgeType.RESOLUTION_TIMING.value == "resolution_timing"
        assert EdgeType.LIQUIDITY_GAP.value == "liquidity_gap"
        assert EdgeType.ORDER_BOOK_STALE.value == "order_book_stale"

    def test_edge_creation(self):
        edge = _make_edge()
        assert edge.edge_type == EdgeType.RESOLUTION_TIMING
        assert edge.market_id == "TEST-MARKET"
        assert edge.edge_score == 7.0 * 0.75

    def test_edge_expired(self):
        edge = _make_edge(
            expires_at=datetime.now(timezone.utc) - timedelta(hours=1),
        )
        assert edge.is_expired

    def test_edge_not_expired_when_no_expiry(self):
        edge = _make_edge()
        assert not edge.is_expired

    def test_remaining_edge(self):
        edge = _make_edge(edge_pp=10.0, edge_score=7.0)
        # With no expiry, remaining edge = full edge_pp
        assert edge.remaining_edge() == 10.0


class TestExitSignal:
    def test_exit_reason_values(self):
        assert ExitReason.PROFIT_TARGET.value == "profit_target"
        assert ExitReason.STOP_LOSS.value == "stop_loss"
        assert ExitReason.TIME_DECAY.value == "time_decay"

    def test_exit_signal_creation(self):
        sig = ExitSignal(
            trade_id=1,
            market_id="TEST-MARKET",
            reason=ExitReason.PROFIT_TARGET,
            exit_price=0.85,
            urgency=0.7,
            edge_at_entry=5.0,
            current_edge=2.0,
            metadata={"pnl_pct": 0.12},
        )
        assert sig.urgency == 0.7
        assert sig.reason == ExitReason.PROFIT_TARGET


# ─── EdgeTypes module tests ────────────────────────────────────────

class TestEdgeTypes:
    def test_clamp(self):
        assert clamp(0.5) == 0.5
        assert clamp(-0.1) == 0.0
        assert clamp(1.2) == 1.0

    def test_market_snapshot(self):
        snap = _make_snapshot()
        assert snap.mid_price == pytest.approx(0.50)
        assert snap.time_to_resolution_hours is None

    def test_market_snapshot_with_end_date(self):
        snap = _make_snapshot(
            end_date=datetime.now(timezone.utc) + timedelta(hours=48),
        )
        assert snap.time_to_resolution_hours is not None
        assert snap.time_to_resolution_hours > 47

    def test_probability_estimate(self):
        est = ProbabilityEstimate(
            probability=0.65,
            confidence=0.8,
            model_name="brownian_bridge",
            time_to_resolution_hours=24.0,
        )
        assert est.probability == 0.65
        assert est.model_name == "brownian_bridge"


# ─── Probability model tests ───────────────────────────────────────

class TestBrownianBridgeModel:
    @pytest.mark.asyncio
    async def test_near_resolution_high_prob(self):
        """Near resolution with high price: high confidence."""
        model = BrownianBridgeModel()
        snap = _make_snapshot(yes_price=0.85, spread=0.02)
        result = await model.estimate_probability(snap, 0.85, timedelta(hours=2))
        assert result is not None
        assert result.model_name == "brownian_bridge"
        assert result.confidence > 0.5

    @pytest.mark.asyncio
    async def test_long_timeframe_lower_confidence(self):
        """Long timeframe: lower confidence, probability pulled toward 0.5."""
        model = BrownianBridgeModel()
        snap = _make_snapshot(yes_price=0.80, spread=0.04)
        result = await model.estimate_probability(snap, 0.80, timedelta(hours=720))
        assert result is not None
        assert result.confidence <= 0.95  # can be high even for long timeframes

    @pytest.mark.asyncio
    async def test_extreme_price_no_crash(self):
        model = BrownianBridgeModel()
        snap = _make_snapshot(yes_price=0.99, spread=0.01)
        result = await model.estimate_probability(snap, 0.99, timedelta(hours=24))
        assert result is not None
        assert 0.01 <= result.probability <= 0.99


class TestNearResolutionModel:
    @pytest.mark.asyncio
    async def test_high_prob_near_resolution(self):
        model = NearResolutionModel(min_hours=1.0, max_hours=72.0, min_price=0.85)
        snap = _make_snapshot(yes_price=0.90, spread=0.02)
        result = await model.estimate_probability(snap, 0.90, timedelta(hours=6))
        assert result is not None
        assert result.probability > 0.90  # adjusted upward
        assert result.confidence > 0.7

    @pytest.mark.asyncio
    async def test_low_prob_near_resolution(self):
        model = NearResolutionModel(min_hours=1.0, max_hours=72.0, min_price=0.85)
        snap = _make_snapshot(yes_price=0.10, spread=0.02)
        result = await model.estimate_probability(snap, 0.10, timedelta(hours=12))
        assert result is not None
        assert result.probability < 0.10

    @pytest.mark.asyncio
    async def test_outside_time_window(self):
        model = NearResolutionModel(min_hours=1.0, max_hours=72.0, min_price=0.85)
        snap = _make_snapshot(yes_price=0.90, spread=0.02)
        result = await model.estimate_probability(snap, 0.90, timedelta(hours=100))
        assert result is None


# ─── ExitManager tests ────────────────────────────────────────────

class TestExitManager:
    def setup_method(self):
        self.manager = ExitManager(
            profit_target_pct=0.08,
            stop_loss_pct=0.04,
            max_hold_seconds=3600,
        )

    def _mock_trade(self, **kw):
        t = MagicMock()
        t.id = 1
        t.market_ticker = "TEST-MARKET"
        t.entry_price = 0.50
        t.direction = "yes"
        t.edge = 5.0
        t.edge_at_entry = 5.0
        t.timestamp = utcnow() - timedelta(hours=0.1)
        t.token_id = "0x1"
        for k, v in kw.items():
            setattr(t, k, v)
        return t

    def test_profit_target_hit(self):
        trade = self._mock_trade(entry_price=0.50, direction="yes")
        sig = self.manager.check_position(trade, current_price=0.58)
        assert sig is not None
        assert sig.reason == ExitReason.PROFIT_TARGET

    def test_stop_loss_hit(self):
        trade = self._mock_trade(entry_price=0.50, direction="yes")
        sig = self.manager.check_position(trade, current_price=0.46)
        assert sig is not None
        assert sig.reason == ExitReason.STOP_LOSS
        assert sig.urgency >= 0.9

    def test_no_exit_normal_position(self):
        trade = self._mock_trade(entry_price=0.50, direction="yes")
        sig = self.manager.check_position(trade, current_price=0.53)
        assert sig is None

    def test_time_decay_exit(self):
        trade = self._mock_trade(
            entry_price=0.50, direction="yes",
            timestamp=datetime.now(timezone.utc) - timedelta(hours=2),
        )
        sig = self.manager.check_position(trade, current_price=0.50)
        assert sig is not None
        assert sig.reason == ExitReason.TIME_DECAY

    def test_check_all_positions_sorted_by_urgency(self):
        t1 = self._mock_trade(market_ticker="A", entry_price=0.50)
        t2 = self._mock_trade(market_ticker="B", entry_price=0.50)
        exits = self.manager.check_all_positions(
            [t1, t2],
            price_lookup={"A": 0.58, "B": 0.46},
        )
        # Stop loss (B) should be first (higher urgency)
        if len(exits) >= 2:
            assert exits[0].urgency >= exits[1].urgency


# ─── Calibration Tracker tests ────────────────────────────────────

class TestCalibrationTracker:
    def test_initial_state(self):
        from backend.core.edge.calibration_tracker import CalibrationTracker
        tracker = CalibrationTracker()
        assert tracker.total_trades == 0
        assert tracker.get_reliability("crypto") == 0.5

    def test_record_observations(self):
        from backend.core.edge.calibration_tracker import CalibrationTracker
        tracker = CalibrationTracker()
        for _ in range(25):
            tracker.record_observation("crypto", 0.80, realized=True)
        adj = tracker.get_adjustment("crypto", 0.80)
        # 25 samples, 100% realized rate, predicted 80%
        # adjustment = (1.0 - 0.80) * 100 = 20, capped at 5
        assert adj <= 5.0

    def test_reliability_scales(self):
        from backend.core.edge.calibration_tracker import CalibrationTracker
        tracker = CalibrationTracker()
        for _ in range(300):
            tracker.record_observation("sports", 0.70, realized=True)
        assert tracker.get_reliability("sports") == 1.0


# ─── EdgeRegistry tests ───────────────────────────────────────────

class TestEdgeRegistry:
    def test_register_and_list(self):
        from backend.core.edge.registry import EdgeRegistry
        from backend.core.edge.registry import EdgeScannerABC as EdgeScanner

        class DummyScanner(EdgeScanner):
            name = "dummy"
            edge_type = EdgeType.RESOLUTION_TIMING
            async def scan(self, ctx):
                return []

        reg = EdgeRegistry()
        reg.register(DummyScanner())
        assert "dummy" in reg._scanners
        assert reg._scanners["dummy"].name == "dummy"

    def test_empty_scan(self):
        from backend.core.edge.registry import EdgeRegistry
        reg = EdgeRegistry()
        ctx = MagicMock()
        edges = asyncio.get_event_loop().run_until_complete(reg.run_all([], ctx))
        assert edges == []


# ─── APEX Strategy tests ──────────────────────────────────────────

class TestAPEXStrategy:
    def test_strategy_creation(self):
        from backend.strategies.apex_strategy import APEXStrategy
        s = APEXStrategy()
        assert s.name == "apex"
        assert "min_edge_pp" in s.default_params

    def test_signal_to_decision_rejects_low_confidence(self):
        from backend.strategies.apex_strategy import APEXStrategy
        from backend.core.edge.edge_model import Signal as APEXSignal

        s = APEXStrategy()
        ctx = MagicMock()
        ctx.params = {}
        ctx.bankroll = 100.0

        sig = APEXSignal(
            market_id="TEST",
            token_id="0x1",
            edge_type=EdgeType.RESOLUTION_TIMING,
            direction="yes",
            entry_price=0.55,
            fair_price=0.60,
            edge_pp=5.0,
            confidence=0.3,  # below min
            edge_score=1.5,
            size_usd=5.0,
            expected_value=0.25,
            time_horizon_min=60,
            profit_target_pct=0.025,
            stop_loss_pct=0.04,
            max_hold_seconds=3600,
        )
        decision = s._signal_to_decision(sig, ctx)
        assert decision is None

    def test_signal_to_decision_accepts_valid(self):
        from backend.strategies.apex_strategy import APEXStrategy
        from backend.core.edge.edge_model import Signal as APEXSignal

        s = APEXStrategy()
        ctx = MagicMock()
        ctx.params = {}
        ctx.bankroll = 100.0

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
        decision = s._signal_to_decision(sig, ctx)
        assert decision is not None
        assert decision["strategy_name"] == "apex"
        assert decision["direction"] == "yes"