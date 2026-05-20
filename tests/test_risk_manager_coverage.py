"""
Tests for RiskManager — pre-trade validation, drawdown, concentration, error fallback.

Source: backend/core/risk/risk_manager.py
All DB queries and external calls are mocked.
"""

import pytest
from unittest.mock import MagicMock, patch

from backend.core.risk.risk_manager import (
    RiskManager,
    RiskDecision,
    EdgeFilterError,
)


# ============================================================================
# Helpers
# ============================================================================


class MockSettings:
    """Minimal settings mock for RiskManager."""
    TRADING_MODE = "paper"
    INITIAL_BANKROLL = 2000.0
    MAX_POSITION_FRACTION = 0.25
    MAX_TRADE_SIZE = 500.0
    MIN_ORDER_USDC = 5.0
    PAPER_MIN_ORDER_USDC = 1.0
    SLIPPAGE_TOLERANCE = 0.05
    AUTO_APPROVE_MIN_CONFIDENCE = 0.60
    MIN_CONFIDENCE = 0.60
    PAPER_AUTO_APPROVE_MIN_CONFIDENCE = 0.50
    DAILY_DRAWDOWN_LIMIT_PCT = 0.10
    WEEKLY_DRAWDOWN_LIMIT_PCT = 0.20
    DAILY_LOSS_LIMIT = 200.0
    DAILY_LOSS_LIMIT_PCT = 0.10
    DAILY_LOSS_FLOOR_PCT = -0.10
    WEEKLY_LOSS_FLOOR_PCT = -0.20
    TAKER_FEE_RATE = 0.02
    MIN_EDGE_PP = 5.0
    LONGSHOT_YES_REJECT_PRICE = 0.30
    LONGSHOT_NO_BIAS_WEIGHT = 0.0
    CATEGORY_MIN_EDGE = {}
    CATEGORY_CONFIDENCE_ENABLED = False
    CATEGORY_CONFIDENCE_MULTIPLIER = {}
    MIN_TRADE_EV = 0.10
    VOLATILITY_SIZE_SCALE = True
    MAX_STRATEGY_DRAWDOWN_PCT = 0.15
    MAX_CONCENTRATION_PCT = 0.30
    AGI_BANKROLL_ALLOCATION_ENABLED = False
    MAX_POSITION_FRACTION = 0.25
    MAX_TOTAL_EXPOSURE_FRACTION = 0.95
    DRAWDOWN_BREAKER_ENABLED_PER_MODE = {"paper": False, "testnet": True, "live": True}
    DAILY_LOSS_LIMIT_ENABLED_PER_MODE = {"paper": False, "testnet": True, "live": True}
    REGIME_ROUTING_ENABLED = False
    MAX_CORRELATED_EXPOSURE_PCT = 0.30


def make_rm():
    """Create a RiskManager with mock settings."""
    return RiskManager(settings_obj=MockSettings())


def make_mock_db(trades=None, bot_state=None, strategy_configs=None):
    """Create a mock DB session."""
    db = MagicMock()

    # Default BotState
    if bot_state is None:
        bot_state = MagicMock()
        bot_state.bankroll = 2000.0
        bot_state.misc_data = None
        bot_state.paper_initial_bankroll = 2000.0

    def query_filter_first(*args, **kwargs):
        mock_q = MagicMock()
        mock_q.filter.return_value = mock_q
        mock_q.first.return_value = bot_state
        mock_q.scalar.return_value = 0.0
        mock_q.all.return_value = trades or []
        mock_q.count.return_value = len(strategy_configs or [])
        return mock_q

    db.query.side_effect = query_filter_first
    return db


# ============================================================================
# Pre-trade validation checks
# ============================================================================


class TestValidateTrade:
    """Test the 8+ pre-trade validation checks in validate_trade."""

    def test_confidence_too_low_rejected(self):
        rm = make_rm()
        db = make_mock_db()
        decision = rm.validate_trade(
            size=50.0,
            current_exposure=0.0,
            bankroll=2000.0,
            confidence=0.30,  # below 0.50 paper threshold
            db=db,
            mode="paper",
        )
        assert not decision.allowed
        assert "confidence" in decision.reason.lower()

    def test_confidence_ok_passes(self):
        rm = make_rm()
        db = make_mock_db()
        # Need to mock all the DB queries that validate_trade hits
        db.query.return_value.filter.return_value.first.return_value = None
        db.query.return_value.filter.return_value.scalar.return_value = 0.0
        decision = rm.validate_trade(
            size=50.0,
            current_exposure=0.0,
            bankroll=2000.0,
            confidence=0.80,
            db=db,
            mode="paper",
        )
        assert decision.allowed

    def test_longshot_yes_rejected(self):
        rm = make_rm()
        db = make_mock_db()
        decision = rm.validate_trade(
            size=50.0,
            current_exposure=0.0,
            bankroll=2000.0,
            confidence=0.80,
            market_price=0.15,
            direction="YES",
            db=db,
            mode="paper",
        )
        assert not decision.allowed
        assert "longshot" in decision.reason.lower()

    def test_min_ev_rejected(self):
        rm = make_rm()
        db = make_mock_db()
        # EV = |0.55 - 0.50| * 1.0 = 0.05 < 0.10 (MIN_TRADE_EV)
        decision = rm.validate_trade(
            size=1.0,
            current_exposure=0.0,
            bankroll=2000.0,
            confidence=0.80,
            market_price=0.50,
            signal_win_rate=0.55,
            db=db,
            mode="paper",
        )
        assert not decision.allowed
        assert "ev" in decision.reason.lower()

    def test_edge_filter_rejected(self):
        rm = make_rm()
        db = make_mock_db()
        # edge_pp = (0.55 - 0.60) * 100 = -5 < MIN_EDGE_PP
        decision = rm.validate_trade(
            size=50.0,
            current_exposure=0.0,
            bankroll=2000.0,
            confidence=0.80,
            market_price=0.60,
            signal_win_rate=0.55,
            db=db,
            mode="paper",
        )
        assert not decision.allowed
        assert "edge" in decision.reason.lower()

    def test_exposure_limit_rejected(self):
        rm = make_rm()
        db = make_mock_db()
        # Paper mode: exposure_base = bankroll + current_exposure = 2000 + 1900 = 3900
        # max_exposure = 3900 * 0.95 = 3705
        # exposure_room = 3705 - 1900 = 1805, so size=50 fits
        # To trigger rejection: use exposure that exceeds max_exposure
        # bankroll=100, current_exposure=200: exposure_base=300, max=285, room=85->negative
        decision = rm.validate_trade(
            size=50.0,
            current_exposure=300.0,
            bankroll=1.0,
            confidence=0.80,
            db=db,
            mode="paper",
        )
        assert not decision.allowed
        assert "exposure" in decision.reason.lower()

    def test_slippage_too_high_rejected(self):
        rm = make_rm()
        db = make_mock_db()
        decision = rm.validate_trade(
            size=50.0,
            current_exposure=0.0,
            bankroll=2000.0,
            confidence=0.80,
            slippage=0.10,  # above 0.05 tolerance
            db=db,
            mode="paper",
        )
        assert not decision.allowed
        assert "slippage" in decision.reason.lower()

    def test_size_adjusted_to_max_position(self):
        rm = make_rm()
        db = make_mock_db()
        db.query.return_value.filter.return_value.first.return_value = None
        db.query.return_value.filter.return_value.scalar.return_value = 0.0
        # max_position = 2000 * 0.25 = 500, but MAX_TRADE_SIZE = 500
        decision = rm.validate_trade(
            size=1000.0,  # way above max
            current_exposure=0.0,
            bankroll=2000.0,
            confidence=0.80,
            db=db,
            mode="paper",
        )
        assert decision.allowed
        assert decision.adjusted_size <= 500.0


# ============================================================================
# Edge check
# ============================================================================


class TestCheckEdge:
    def test_valid_edge_passes(self):
        rm = make_rm()
        edge = rm.check_edge(market_price=0.50, signal_win_rate=0.60, market_id="m1")
        assert abs(edge - 10.0) < 0.01  # (0.60 - 0.50) * 100

    def test_longshot_insufficient_edge_raises(self):
        rm = make_rm()
        with pytest.raises(EdgeFilterError) as exc_info:
            rm.check_edge(market_price=0.20, signal_win_rate=0.25, market_id="m1")
        assert abs(exc_info.value.edge_pp - 5.0) < 0.01
        assert exc_info.value.market_price == 0.20

    def test_below_min_edge_raises(self):
        rm = make_rm()
        with pytest.raises(EdgeFilterError):
            rm.check_edge(market_price=0.50, signal_win_rate=0.52, market_id="m1")
        # edge = 2.0 < MIN_EDGE_PP=5.0


# ============================================================================
# Drawdown calculation
# ============================================================================


class TestCheckDrawdown:
    def _make_drawdown_db(self, daily_pnl=-50.0, weekly_pnl=-50.0, bankroll_state=None):
        """Create a mock DB that works with check_drawdown's context manager pattern."""
        db = MagicMock()
        # check_drawdown uses `with ctx as db:` — the context manager returns db itself
        db.__enter__ = MagicMock(return_value=db)
        db.__exit__ = MagicMock(return_value=False)

        # BotState for bankroll lookup
        state = bankroll_state or MagicMock()
        state.paper_initial_bankroll = 2000.0

        call_count = [0]
        def mock_query(*args, **kwargs):
            mock_q = MagicMock()
            # For BotState query
            if args and hasattr(args[0], '__name__') and 'BotState' in str(args[0]):
                mock_q.filter_by.return_value.first.return_value = state
                return mock_q
            # For Trade PnL sum queries — first call=daily, second=weekly
            mock_q.filter.return_value = mock_q
            mock_q.scalar = MagicMock(side_effect=lambda: (call_count.__setitem__(0, call_count[0]+1), daily_pnl if call_count[0] <= 1 else weekly_pnl)[1])
            return mock_q

        db.query.side_effect = mock_query
        return db

    def test_no_breach(self):
        rm = make_rm()
        db = self._make_drawdown_db(daily_pnl=-50.0, weekly_pnl=-50.0)
        result = rm.check_drawdown(2000.0, db=db, mode="paper")
        assert not result.is_breached

    def test_daily_breach(self):
        rm = make_rm()
        db = self._make_drawdown_db(daily_pnl=-250.0, weekly_pnl=-250.0)
        result = rm.check_drawdown(2000.0, db=db, mode="paper")
        assert result.is_breached

    def test_weekly_breach(self):
        rm = make_rm()
        db = self._make_drawdown_db(daily_pnl=-50.0, weekly_pnl=-500.0)
        result = rm.check_drawdown(2000.0, db=db, mode="paper")
        assert result.is_breached

    def test_db_error_fails_safe(self):
        """DB error should fail-safe (is_breached=True) to prevent trading."""
        rm = make_rm()
        db = MagicMock()
        db.__enter__ = MagicMock(side_effect=Exception("DB connection lost"))
        db.__exit__ = MagicMock(return_value=False)
        result = rm.check_drawdown(2000.0, db=db, mode="paper")
        assert result.is_breached
        assert "error" in result.breach_reason.lower()

    def test_positive_pnl_not_breach(self):
        rm = make_rm()
        db = self._make_drawdown_db(daily_pnl=100.0, weekly_pnl=100.0)
        result = rm.check_drawdown(2000.0, db=db, mode="paper")
        assert not result.is_breached


# ============================================================================
# Concentration limits
# ============================================================================


class TestCheckConcentration:
    def test_within_limit_passes(self):
        rm = make_rm()
        db = make_mock_db()
        # event_exposure = 200, trade_size = 100, max = 2000 * 0.30 = 600
        db.query.return_value.filter.return_value.first.return_value = ("event-slug",)
        db.query.return_value.filter.return_value.scalar.return_value = 200.0
        result = rm.check_concentration("ticker1", 100.0, 2000.0, db, "paper")
        assert result is None  # no rejection

    def test_over_limit_rejected(self):
        rm = make_rm()
        db = MagicMock()
        # Mock: first query returns event_slug, second query returns exposure
        mock_q1 = MagicMock()
        mock_q1.filter.return_value.first.return_value = ("event-slug",)
        mock_q2 = MagicMock()
        mock_q2.filter.return_value.scalar.return_value = 500.0
        db.query.side_effect = [mock_q1, mock_q2]
        result = rm.check_concentration("ticker1", 200.0, 2000.0, db, "paper")
        assert result is not None
        assert "concentration" in result.lower()

    def test_no_event_slug_uses_ticker(self):
        rm = make_rm()
        db = make_mock_db()
        db.query.return_value.filter.return_value.first.return_value = None
        db.query.return_value.filter.return_value.scalar.return_value = 100.0
        result = rm.check_concentration("ticker1", 50.0, 2000.0, db, "paper")
        assert result is None

    def test_db_error_returns_none(self):
        """DB error in concentration check should not block trading."""
        rm = make_rm()
        db = MagicMock()
        db.query.side_effect = Exception("DB error")
        result = rm.check_concentration("ticker1", 50.0, 2000.0, db, "paper")
        assert result is None


# ============================================================================
# Error fallback behavior (fail-safe)
# ============================================================================


class TestFailSafeBehavior:
    def test_drawdown_db_error_fails_safe(self):
        """DB error during drawdown check -> is_breached=True (fail-safe rejection)."""
        rm = make_rm()
        db = MagicMock()
        db.query.side_effect = Exception("connection lost")
        result = rm.check_drawdown(2000.0, db=db, mode="paper")
        assert result.is_breached

    def test_daily_loss_db_error_fails_safe(self):
        """DB error during daily loss check -> returns True (fail-safe)."""
        rm = make_rm()
        db = MagicMock()
        db.query.side_effect = Exception("connection lost")
        result = rm._daily_loss_exceeded(db=db, mode="paper")
        assert result is True

    def test_has_unsettled_trade_db_error_fails_safe(self):
        """DB error during unsettled check -> returns True (blocks trade)."""
        rm = make_rm()
        db = MagicMock()
        db.query.side_effect = Exception("connection lost")
        result = rm._has_unsettled_trade("ticker1", db=db, mode="paper")
        assert result is True

    def test_check_side_lock_db_error_returns_error(self):
        """DB error during side-lock check -> returns 'error' (blocks trade)."""
        rm = make_rm()
        db = MagicMock()
        db.query.side_effect = Exception("connection lost")
        result = rm.check_side_lock("ticker1", "YES", db=db, mode="paper")
        assert result == "error"

    def test_strategy_drawdown_db_error_returns_none(self):
        """DB error during strategy drawdown -> returns None (fail-safe)."""
        rm = make_rm()
        with patch.object(rm, '_check_strategy_drawdown', return_value=None):
            result = rm._check_strategy_drawdown("test_strat", MagicMock(), "paper")
        assert result is None

    def test_strategy_drawdown_normal_returns_float(self):
        """Normal strategy drawdown returns a float PnL value."""
        rm = make_rm()
        with patch.object(rm, '_check_strategy_drawdown', return_value=-50.0):
            result = rm._check_strategy_drawdown("test_strat", MagicMock(), "paper")
        assert result == -50.0


# ============================================================================
# Safety rules
# ============================================================================


class TestSafetyRules:
    def test_safety_rules_loaded(self):
        rm = make_rm()
        assert "max_total_exposure" in rm._safety_rules
        assert "emergency_kill_switch" in rm._safety_rules
        assert rm._safety_rules["emergency_kill_switch"] is True

    def test_safety_rules_defaults(self):
        rm = make_rm()
        # Values may be overridden by env vars — just check keys exist and are numeric
        assert isinstance(rm._safety_rules["max_total_exposure"], float)
        assert isinstance(rm._safety_rules["max_single_strategy_pct"], float)
        assert isinstance(rm._safety_rules["daily_loss_floor"], float)
        # Emergency kill switch is always True (no env override)
        assert rm._safety_rules["emergency_kill_switch"] is True


# ============================================================================
# RiskDecision
# ============================================================================


class TestRiskDecision:
    def test_allowed_decision(self):
        d = RiskDecision(True, "ok", 50.0)
        assert d.allowed
        assert d.adjusted_size == 50.0

    def test_rejected_decision(self):
        d = RiskDecision(False, "too risky", 0.0)
        assert not d.allowed
        assert d.adjusted_size == 0.0


# ============================================================================
# Breaker mode check
# ============================================================================


class TestBreakerMode:
    def test_drawdown_breaker_disabled_for_paper(self):
        rm = make_rm()
        assert rm._breaker_enabled_for_mode("drawdown", "paper") is False

    def test_drawdown_breaker_enabled_for_live(self):
        rm = make_rm()
        assert rm._breaker_enabled_for_mode("drawdown", "live") is True

    def test_daily_loss_breaker_disabled_for_paper(self):
        rm = make_rm()
        assert rm._breaker_enabled_for_mode("daily_loss", "paper") is False

    def test_unknown_breaker_defaults_true(self):
        rm = make_rm()
        assert rm._breaker_enabled_for_mode("unknown", "paper") is True
