"""G-22: Unit tests for backend/core/strategy_gate.py."""
import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime, timezone

from backend.core.strategy_gate import (
    StrategyGate,
    STAGE_REQUIREMENTS,
    SHADOW_EXEMPT,
    _count_paper_trades,
    _check_fronttest,
    _check_shadow,
    check_risk_and_disable,
    MAX_DAILY_LOSS_PER_STRATEGY,
)


class TestGetStage:
    """Test StrategyGate.get_stage() logic."""

    def test_no_config_returns_paper(self):
        db = MagicMock()
        db.query.return_value.filter_by.return_value.first.return_value = None
        assert StrategyGate.get_stage("new_strategy", db) == "paper"

    def test_live_mode(self):
        db = MagicMock()
        cfg = MagicMock()
        cfg.mode = "live"
        db.query.return_value.filter_by.return_value.first.return_value = cfg
        assert StrategyGate.get_stage("test_strat", db) == "live"

    def test_shadow_mode(self):
        db = MagicMock()
        cfg = MagicMock()
        cfg.mode = "shadow"
        db.query.return_value.filter_by.return_value.first.return_value = cfg
        assert StrategyGate.get_stage("test_strat", db) == "shadow"

    def test_enabled_returns_fronttest(self):
        db = MagicMock()
        cfg = MagicMock()
        cfg.mode = None
        cfg.enabled = True
        db.query.return_value.filter_by.return_value.first.return_value = cfg
        assert StrategyGate.get_stage("test_strat", db) == "fronttest"

    def test_disabled_returns_paper(self):
        db = MagicMock()
        cfg = MagicMock()
        cfg.mode = None
        cfg.enabled = False
        db.query.return_value.filter_by.return_value.first.return_value = cfg
        assert StrategyGate.get_stage("test_strat", db) == "paper"


class TestCanExecuteLive:
    """Test StrategyGate.can_execute_live()."""

    def test_live_returns_true(self):
        db = MagicMock()
        cfg = MagicMock()
        cfg.mode = "live"
        db.query.return_value.filter_by.return_value.first.return_value = cfg
        allowed, reason = StrategyGate.can_execute_live("test", db)
        assert allowed is True
        assert "live" in reason

    def test_shadow_returns_false(self):
        db = MagicMock()
        cfg = MagicMock()
        cfg.mode = "shadow"
        db.query.return_value.filter_by.return_value.first.return_value = cfg
        allowed, reason = StrategyGate.can_execute_live("test", db)
        assert allowed is False

    def test_paper_returns_false(self):
        db = MagicMock()
        db.query.return_value.filter_by.return_value.first.return_value = None
        allowed, reason = StrategyGate.can_execute_live("test", db)
        assert allowed is False


class TestCanAdvanceToLive:
    """Test StrategyGate.can_advance_to_live()."""

    def test_no_config_returns_not_approved(self):
        db = MagicMock()
        db.query.return_value.filter_by.return_value.first.return_value = None
        result = StrategyGate.can_advance_to_live("test", db)
        assert result["approved"] is False

    def test_insufficient_paper_trades(self):
        db = MagicMock()
        cfg = MagicMock()
        db.query.return_value.filter_by.return_value.first.return_value = cfg
        with patch("backend.core.strategy_gate._count_paper_trades", return_value=3):
            result = StrategyGate.can_advance_to_live("test", db)
        assert result["approved"] is False


class TestShadowExempt:
    """Test SHADOW_EXEMPT set."""

    def test_whale_frontrun_exempt(self):
        assert "whale_frontrun" in SHADOW_EXEMPT

    def test_bond_scanner_exempt(self):
        assert "bond_scanner" in SHADOW_EXEMPT

    def test_cex_pm_leadlag_exempt(self):
        assert "cex_pm_leadlag" in SHADOW_EXEMPT


class TestStageRequirements:
    """Test STAGE_REQUIREMENTS constants."""

    def test_paper_requirements(self):
        assert STAGE_REQUIREMENTS["paper"]["min_trades"] == 5
        assert STAGE_REQUIREMENTS["paper"]["min_days"] == 3

    def test_fronttest_requirements(self):
        assert STAGE_REQUIREMENTS["fronttest"]["min_trades"] == 20
        assert STAGE_REQUIREMENTS["fronttest"]["min_win_rate"] == 0.55
        assert STAGE_REQUIREMENTS["fronttest"]["min_pnl"] == 0.0

    def test_shadow_requirements(self):
        assert STAGE_REQUIREMENTS["shadow"]["min_trades"] == 30
        assert STAGE_REQUIREMENTS["shadow"]["max_drawdown"] == 0.15


class TestCheckRiskAndDisable:
    """Test check_risk_and_disable() risk limits."""

    def test_returns_list(self):
        db = MagicMock()
        db.execute.return_value.fetchall.return_value = []
        db.execute.return_value.scalar.return_value = 0
        result = check_risk_and_disable(db)
        assert isinstance(result, list)
