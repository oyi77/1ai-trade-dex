"""Tests for auto_improve guardrails, clamping, rollback logic, and job integration."""

import pytest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from backend.core.auto_improve import (
    _confidence_to_float,
    clamp_to_bounds,
    validate_and_clamp_params,
    apply_params_to_settings,
    rollback_params,
    _get_current_params,
    check_rollback_needed,
    MIN_CONFIDENCE_FOR_AUTO_APPLY,
    MAX_PARAM_CHANGE_FRACTION,
    ROLLBACK_TRADE_WINDOW,
    ROLLBACK_PERF_DEGRADATION_THRESHOLD,
)
import backend.core.auto_improve as auto_improve_mod


def _make_settings(**overrides):
    defaults = {
        "KELLY_FRACTION": 0.05,
        "MIN_EDGE_THRESHOLD": 0.05,
        "MAX_TRADE_SIZE": 8.0,
        "DAILY_LOSS_LIMIT": 5.0,
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def _make_trade(result="win", settled=True, settlement_time=None, pnl=1.0):
    return SimpleNamespace(
        result=result,
        settled=settled,
        settlement_time=settlement_time or datetime.now(timezone.utc),
        pnl=pnl,
    )


class TestConfidenceToFloat:
    def test_numeric_passthrough(self):
        assert _confidence_to_float(0.85) == 0.85
        assert _confidence_to_float(1) == 1.0

    def test_string_high(self):
        assert _confidence_to_float("high") == 0.9

    def test_string_medium(self):
        assert _confidence_to_float("medium") == 0.6

    def test_string_low(self):
        assert _confidence_to_float("low") == 0.3

    def test_unknown_string(self):
        assert _confidence_to_float("unknown") == 0.0

    def test_case_insensitive(self):
        assert _confidence_to_float("HIGH") == 0.9
        assert _confidence_to_float("  High  ") == 0.9


class TestClampToBounds:
    def test_within_bounds_unchanged(self):
        assert clamp_to_bounds(100.0, 110.0) == 110.0

    def test_exactly_at_upper_bound(self):
        assert clamp_to_bounds(100.0, 130.0) == 130.0

    def test_exactly_at_lower_bound(self):
        assert clamp_to_bounds(100.0, 70.0) == 70.0

    def test_above_upper_bound_clamped(self):
        result = clamp_to_bounds(100.0, 200.0)
        assert result == 130.0

    def test_below_lower_bound_clamped(self):
        result = clamp_to_bounds(100.0, 10.0)
        assert result == 70.0

    def test_zero_current_returns_zero(self):
        assert clamp_to_bounds(0.0, 50.0) == 0.0

    def test_negative_current_returns_zero(self):
        assert clamp_to_bounds(-5.0, 50.0) == 0.0

    def test_small_values(self):
        result = clamp_to_bounds(0.05, 0.10)
        assert result == 0.065

    def test_suggested_equals_current(self):
        assert clamp_to_bounds(10.0, 10.0) == 10.0


class TestValidateAndClampParams:
    def test_all_params_clamped(self):
        current = {
            "kelly_fraction": 0.05,
            "min_edge_threshold": 0.05,
            "max_trade_size": 8.0,
            "daily_loss_limit": 5.0,
        }
        suggested = {
            "kelly_fraction": 1.0,
            "min_edge_threshold": 1.0,
            "max_trade_size": 100.0,
            "daily_loss_limit": 50.0,
        }
        result = validate_and_clamp_params(current, suggested)
        assert result["kelly_fraction"] == clamp_to_bounds(0.05, 1.0)
        assert result["max_trade_size"] == clamp_to_bounds(8.0, 100.0)

    def test_missing_key_skipped(self):
        current = {"kelly_fraction": 0.05}
        suggested = {"kelly_fraction": 0.06, "unknown_param": 99.0}
        result = validate_and_clamp_params(current, suggested)
        assert "kelly_fraction" in result
        assert "unknown_param" not in result

    def test_none_values_skipped(self):
        current = {"kelly_fraction": 0.05, "min_edge_threshold": None}
        suggested = {"kelly_fraction": 0.06, "min_edge_threshold": 0.07}
        result = validate_and_clamp_params(current, suggested)
        assert "kelly_fraction" in result
        assert "min_edge_threshold" not in result

    def test_empty_dicts(self):
        assert validate_and_clamp_params({}, {}) == {}


class TestApplyAndRollback:
    def test_apply_modifies_settings(self):
        s = _make_settings()
        previous = apply_params_to_settings({"kelly_fraction": 0.06}, target_settings=s)
        assert s.KELLY_FRACTION == 0.06
        assert previous == {"kelly_fraction": 0.05}

    def test_rollback_restores_settings(self):
        s = _make_settings()
        previous = apply_params_to_settings(
            {"kelly_fraction": 0.06, "max_trade_size": 10.0}, target_settings=s
        )
        assert s.KELLY_FRACTION == 0.06
        assert s.MAX_TRADE_SIZE == 10.0
        rollback_params(previous, target_settings=s)
        assert s.KELLY_FRACTION == 0.05
        assert s.MAX_TRADE_SIZE == 8.0

    def test_apply_only_known_params(self):
        s = _make_settings()
        previous = apply_params_to_settings({"unknown_key": 999}, target_settings=s)
        assert previous == {}

    def test_get_current_params(self):
        s = _make_settings()
        params = _get_current_params(target_settings=s)
        assert params["kelly_fraction"] == 0.05
        assert params["max_trade_size"] == 8.0


class TestCheckRollbackNeeded:
    def _setup_rollback_state(self, pre_win_rate=0.6, previous_values=None):
        auto_improve_mod._last_param_change = {
            "previous_values": previous_values or {"kelly_fraction": 0.05},
            "applied_values": {"kelly_fraction": 0.06},
            "applied_at": datetime.now(timezone.utc) - timedelta(hours=1),
            "pre_change_win_rate": pre_win_rate,
            "pre_change_pnl": 10.0,
            "trade_count_at_apply": 50,
        }

    def teardown_method(self):
        auto_improve_mod._last_param_change = None

    def test_no_pending_change_returns_false(self):
        auto_improve_mod._last_param_change = None
        db = MagicMock()
        assert check_rollback_needed(db) is False

    def test_not_enough_trades_returns_false(self):
        self._setup_rollback_state()
        db = MagicMock()
        query = db.query.return_value.filter.return_value.order_by.return_value.limit.return_value
        query.all.return_value = [_make_trade() for _ in range(5)]
        assert check_rollback_needed(db) is False
        assert auto_improve_mod._last_param_change is not None

    def test_good_performance_clears_state(self):
        self._setup_rollback_state(pre_win_rate=0.6)
        s = _make_settings()
        db = MagicMock()
        trades = [_make_trade(result="win") for _ in range(8)] + [
            _make_trade(result="loss") for _ in range(2)
        ]
        query = db.query.return_value.filter.return_value.order_by.return_value.limit.return_value
        query.all.return_value = trades
        result = check_rollback_needed(db, target_settings=s)
        assert result is False
        assert auto_improve_mod._last_param_change is None

    @patch("backend.core.auto_improve.rollback_params")
    def test_degraded_performance_triggers_rollback(self, mock_rollback):
        self._setup_rollback_state(pre_win_rate=0.7)
        s = _make_settings()
        db = MagicMock()
        trades = [_make_trade(result="win") for _ in range(3)] + [
            _make_trade(result="loss") for _ in range(7)
        ]
        query = db.query.return_value.filter.return_value.order_by.return_value.limit.return_value
        query.all.return_value = trades
        result = check_rollback_needed(db, target_settings=s)
        assert result is True
        mock_rollback.assert_called_once()
        assert auto_improve_mod._last_param_change is None

    def test_zero_pre_win_rate_no_rollback(self):
        self._setup_rollback_state(pre_win_rate=0.0)
        db = MagicMock()
        trades = [_make_trade(result="loss") for _ in range(ROLLBACK_TRADE_WINDOW)]
        query = db.query.return_value.filter.return_value.order_by.return_value.limit.return_value
        query.all.return_value = trades
        result = check_rollback_needed(db)
        assert result is False

    def test_borderline_performance_no_rollback(self):
        self._setup_rollback_state(pre_win_rate=0.6)
        db = MagicMock()
        post_win_rate_target = 0.6 * (1.0 - ROLLBACK_PERF_DEGRADATION_THRESHOLD)
        win_count = round(post_win_rate_target * ROLLBACK_TRADE_WINDOW) + 1
        trades = [_make_trade(result="win") for _ in range(win_count)] + [
            _make_trade(result="loss") for _ in range(ROLLBACK_TRADE_WINDOW - win_count)
        ]
        query = db.query.return_value.filter.return_value.order_by.return_value.limit.return_value
        query.all.return_value = trades
        result = check_rollback_needed(db)
        assert result is False


class TestGuardrailConstants:
    def test_confidence_threshold(self):
        assert MIN_CONFIDENCE_FOR_AUTO_APPLY == 0.8

    def test_param_change_fraction(self):
        assert MAX_PARAM_CHANGE_FRACTION == 0.30

    def test_rollback_window(self):
        assert ROLLBACK_TRADE_WINDOW == 10

    def test_degradation_threshold(self):
        assert ROLLBACK_PERF_DEGRADATION_THRESHOLD == 0.15


class TestEndToEndClampGuardrail:
    def test_extreme_suggestion_clamped_to_30pct(self):
        s = _make_settings(KELLY_FRACTION=0.10, MAX_TRADE_SIZE=10.0)
        current = _get_current_params(target_settings=s)
        suggested = {"kelly_fraction": 0.50, "max_trade_size": 50.0}
        clamped = validate_and_clamp_params(current, suggested)
        assert clamped["kelly_fraction"] == clamp_to_bounds(0.10, 0.50)
        assert clamped["kelly_fraction"] <= 0.10 * 1.30
        assert clamped["max_trade_size"] <= 10.0 * 1.30

    def test_apply_clamped_then_rollback(self):
        s = _make_settings()
        original_kelly = s.KELLY_FRACTION
        clamped = validate_and_clamp_params(
            _get_current_params(target_settings=s),
            {"kelly_fraction": 1.0, "max_trade_size": 100.0},
        )
        previous = apply_params_to_settings(clamped, target_settings=s)
        assert s.KELLY_FRACTION <= original_kelly * 1.30
        rollback_params(previous, target_settings=s)
        assert s.KELLY_FRACTION == original_kelly


# ===================================================================
# Integration tests: auto_improve_job full flow
# ===================================================================


def _make_job_settings(**overrides):
    defaults = {
        "KELLY_FRACTION": 0.10,
        "MIN_EDGE_THRESHOLD": 0.03,
        "MAX_TRADE_SIZE": 100.0,
        "DAILY_LOSS_LIMIT": 500.0,
        "GROQ_API_KEY": None,
        "AI_PROVIDER": "groq",
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def _bigbrain_mock():
    bb = AsyncMock()
    bb.write_trade_outcome = AsyncMock()
    bb.write_strategy_insight = AsyncMock()
    bb.write_parameter_tuning = AsyncMock()
    bb.write_signal_analysis = AsyncMock()
    bb.close = AsyncMock()
    return bb


def _optimizer_mock(confidence="high", suggestions=None):
    sug = suggestions or {
        "kelly_fraction": 0.12,
        "min_edge_threshold": 0.035,
        "max_trade_size": 110.0,
        "daily_loss_limit": 520.0,
        "reasoning": "Test reasoning",
        "confidence": confidence,
    }
    optimizer = MagicMock()
    optimizer.analyze_performance.return_value = {
        "total_trades": 50,
        "win_rate": 0.65,
        "pnl": 150.0,
        "avg_win_edge": 0.05,
        "avg_loss_edge": 0.02,
        "top_strategy": "test_strat",
    }
    optimizer.get_suggestions = AsyncMock(
        return_value={"status": "ok", "suggestions": sug}
    )
    return optimizer


class TestAutoImproveJob:
    @pytest.fixture(autouse=True)
    def _reset_module_state(self):
        auto_improve_mod._last_param_change = None
        yield
        auto_improve_mod._last_param_change = None

    @pytest.mark.asyncio
    @patch("backend.core.auto_improve.get_bigbrain")
    @patch("backend.core.auto_improve.SessionLocal")
    @patch("backend.core.auto_improve.ParameterOptimizer")
    @patch("backend.core.auto_improve._write_outcomes_to_brain", new_callable=AsyncMock)
    @patch("backend.core.auto_improve._write_market_insights", new_callable=AsyncMock)
    async def test_high_confidence_applies_params(
        self,
        mock_insights,
        mock_outcomes,
        MockOptimizer,
        MockSession,
        mock_bb,
    ):
        fake_s = _make_job_settings()
        bb = _bigbrain_mock()
        mock_bb.return_value = bb

        db = MagicMock()
        db.query.return_value.filter.return_value.count.return_value = 60
        MockSession.return_value = db

        MockOptimizer.return_value = _optimizer_mock(confidence="high")

        with patch.object(auto_improve_mod, "settings", fake_s):
            await auto_improve_mod.auto_improve_job()

        assert fake_s.KELLY_FRACTION == 0.12
        assert auto_improve_mod._last_param_change is not None
        assert (
            auto_improve_mod._last_param_change["applied_values"]["kelly_fraction"]
            == 0.12
        )

    @pytest.mark.asyncio
    @patch("backend.core.auto_improve.get_bigbrain")
    @patch("backend.core.auto_improve.SessionLocal")
    @patch("backend.core.auto_improve.ParameterOptimizer")
    @patch("backend.core.auto_improve._write_outcomes_to_brain", new_callable=AsyncMock)
    @patch("backend.core.auto_improve._write_market_insights", new_callable=AsyncMock)
    async def test_low_confidence_skips_apply(
        self,
        mock_insights,
        mock_outcomes,
        MockOptimizer,
        MockSession,
        mock_bb,
    ):
        fake_s = _make_job_settings()
        bb = _bigbrain_mock()
        mock_bb.return_value = bb
        MockSession.return_value = MagicMock()
        MockOptimizer.return_value = _optimizer_mock(confidence="low")

        with patch.object(auto_improve_mod, "settings", fake_s):
            await auto_improve_mod.auto_improve_job()

        assert fake_s.KELLY_FRACTION == 0.10
        assert auto_improve_mod._last_param_change is None

    @pytest.mark.asyncio
    @patch("backend.core.auto_improve.get_bigbrain")
    @patch("backend.core.auto_improve.SessionLocal")
    @patch("backend.core.auto_improve.ParameterOptimizer")
    @patch("backend.core.auto_improve._write_outcomes_to_brain", new_callable=AsyncMock)
    @patch("backend.core.auto_improve._write_market_insights", new_callable=AsyncMock)
    async def test_excessive_suggestion_clamped_to_30pct(
        self,
        mock_insights,
        mock_outcomes,
        MockOptimizer,
        MockSession,
        mock_bb,
    ):
        fake_s = _make_job_settings()
        bb = _bigbrain_mock()
        mock_bb.return_value = bb

        db = MagicMock()
        db.query.return_value.filter.return_value.count.return_value = 60
        MockSession.return_value = db

        MockOptimizer.return_value = _optimizer_mock(
            confidence="high",
            suggestions={
                "kelly_fraction": 0.50,
                "min_edge_threshold": 0.035,
                "reasoning": "Extreme suggestion",
                "confidence": "high",
            },
        )

        with patch.object(auto_improve_mod, "settings", fake_s):
            await auto_improve_mod.auto_improve_job()

        assert fake_s.KELLY_FRACTION == 0.13
        assert (
            auto_improve_mod._last_param_change["applied_values"]["kelly_fraction"]
            == 0.13
        )

    @pytest.mark.asyncio
    @patch("backend.core.auto_improve.get_bigbrain")
    @patch("backend.core.auto_improve.SessionLocal")
    @patch("backend.core.auto_improve.ParameterOptimizer")
    @patch("backend.core.auto_improve._write_outcomes_to_brain", new_callable=AsyncMock)
    @patch("backend.core.auto_improve._write_market_insights", new_callable=AsyncMock)
    async def test_pending_change_blocks_new_apply(
        self,
        mock_insights,
        mock_outcomes,
        MockOptimizer,
        MockSession,
        mock_bb,
    ):
        fake_s = _make_job_settings()
        auto_improve_mod._last_param_change = {
            "previous_values": {"kelly_fraction": 0.09},
            "applied_values": {"kelly_fraction": 0.12},
            "applied_at": datetime.now(timezone.utc),
            "pre_change_win_rate": 0.65,
            "pre_change_pnl": 100.0,
            "trade_count_at_apply": 40,
        }

        bb = _bigbrain_mock()
        mock_bb.return_value = bb

        db = MagicMock()
        db.query.return_value.filter.return_value.order_by.return_value.limit.return_value.all.return_value = []
        MockSession.return_value = db

        MockOptimizer.return_value = _optimizer_mock(confidence="high")

        with patch.object(auto_improve_mod, "settings", fake_s):
            await auto_improve_mod.auto_improve_job()

        assert fake_s.KELLY_FRACTION == 0.10

    @pytest.mark.asyncio
    @patch("backend.core.auto_improve.get_bigbrain")
    @patch("backend.core.auto_improve.SessionLocal")
    @patch("backend.core.auto_improve.ParameterOptimizer")
    @patch("backend.core.auto_improve._write_outcomes_to_brain", new_callable=AsyncMock)
    @patch("backend.core.auto_improve._write_market_insights", new_callable=AsyncMock)
    async def test_insufficient_trades_skips_optimization(
        self,
        mock_insights,
        mock_outcomes,
        MockOptimizer,
        MockSession,
        mock_bb,
    ):
        fake_s = _make_job_settings()
        bb = _bigbrain_mock()
        mock_bb.return_value = bb
        MockSession.return_value = MagicMock()

        optimizer = MagicMock()
        optimizer.analyze_performance.return_value = {
            "total_trades": 15,
            "win_rate": 0.60,
            "pnl": 50.0,
            "avg_win_edge": 0.04,
            "avg_loss_edge": 0.02,
            "top_strategy": "test_strat",
        }
        MockOptimizer.return_value = optimizer

        with patch.object(auto_improve_mod, "settings", fake_s):
            await auto_improve_mod.auto_improve_job()

        optimizer.get_suggestions.assert_not_called()
        assert fake_s.KELLY_FRACTION == 0.10

    @pytest.mark.asyncio
    @patch("backend.core.auto_improve.get_bigbrain")
    @patch("backend.core.auto_improve.SessionLocal")
    @patch("backend.core.auto_improve.ParameterOptimizer")
    @patch("backend.core.auto_improve._write_outcomes_to_brain", new_callable=AsyncMock)
    @patch("backend.core.auto_improve._write_market_insights", new_callable=AsyncMock)
    async def test_medium_confidence_skips_apply(
        self,
        mock_insights,
        mock_outcomes,
        MockOptimizer,
        MockSession,
        mock_bb,
    ):
        fake_s = _make_job_settings()
        bb = _bigbrain_mock()
        mock_bb.return_value = bb
        MockSession.return_value = MagicMock()
        MockOptimizer.return_value = _optimizer_mock(confidence="medium")

        with patch.object(auto_improve_mod, "settings", fake_s):
            await auto_improve_mod.auto_improve_job()

        assert fake_s.KELLY_FRACTION == 0.10
        assert auto_improve_mod._last_param_change is None
