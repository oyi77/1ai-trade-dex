
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.core.agi_goal_engine import (
    AGIGoalEngine,
    GoalPerformance,
    REGIME_GOAL_MAP,
)
from backend.core.agi_types import AGIGoal, MarketRegime
from backend.models.kg_models import Base, DecisionAuditLog


def make_goal_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()
    engine = AGIGoalEngine(session=session)
    return engine, session, engine


class TestAGIGoalEngineGetGoal:
    def test_get_goal_bull_returns_maximize_pnl(self):
        engine, _, _ = make_goal_session()
        result = engine.get_current_goal(MarketRegime.BULL)
        assert result == AGIGoal.MAXIMIZE_PNL

    def test_get_goal_bear_returns_preserve_capital(self):
        engine, _, _ = make_goal_session()
        result = engine.get_current_goal(MarketRegime.BEAR)
        assert result == AGIGoal.PRESERVE_CAPITAL

    def test_get_goal_sideways_returns_grow_allocation(self):
        engine, _, _ = make_goal_session()
        result = engine.get_current_goal(MarketRegime.SIDEWAYS)
        assert result == AGIGoal.GROW_ALLOCATION

    def test_get_goal_sideways_volatile_returns_reduce_exposure(self):
        engine, _, _ = make_goal_session()
        result = engine.get_current_goal(MarketRegime.SIDEWAYS_VOLATILE)
        assert result == AGIGoal.REDUCE_EXPOSURE

    def test_get_goal_crisis_returns_preserve_capital(self):
        engine, _, _ = make_goal_session()
        result = engine.get_current_goal(MarketRegime.CRISIS)
        assert result == AGIGoal.PRESERVE_CAPITAL

    def test_get_goal_unknown_returns_preserve_capital(self):
        engine, _, _ = make_goal_session()
        result = engine.get_current_goal(MarketRegime.UNKNOWN)
        assert result == AGIGoal.PRESERVE_CAPITAL

    def test_get_goal_returns_set_goal(self):
        engine, _, _ = make_goal_session()
        engine.set_goal(AGIGoal.GROW_ALLOCATION, "test override")
        result = engine.get_current_goal(MarketRegime.BULL)
        assert result == AGIGoal.GROW_ALLOCATION


class TestAGIGoalEngineSetGoal:
    def test_set_goal_creates_audit_entry(self):
        engine, session, _ = make_goal_session()
        audit_entry = engine.set_goal(AGIGoal.MAXIMIZE_PNL, "riding the bull trend")
        assert audit_entry is not None
        assert audit_entry.goal == AGIGoal.MAXIMIZE_PNL
        db_audit = session.query(DecisionAuditLog).filter_by(decision_type="goal_change").first()
        assert db_audit is not None
        assert "maximize_pnl" in str(db_audit.input_data)

    def test_set_goal_updates_current_goal(self):
        engine, _, _ = make_goal_session()
        engine.set_goal(AGIGoal.REDUCE_EXPOSURE, "volatility detected")
        assert engine._current_goal == AGIGoal.REDUCE_EXPOSURE
        assert engine._goal_reason == "volatility detected"


class TestAGIGoalEngineEvaluatePerformance:
    def test_evaluate_empty_trades(self):
        engine, _, _ = make_goal_session()
        perf = engine.evaluate_goal_performance(AGIGoal.MAXIMIZE_PNL, [])
        assert perf.trades == 0
        assert perf.wins == 0
        assert perf.pnl == 0.0
        assert perf.win_rate == 0.0

    def test_evaluate_winning_trades(self):
        engine, _, _ = make_goal_session()
        trades = [
            {"result": "win", "pnl": 10.0},
            {"result": "win", "pnl": 20.0},
            {"result": "loss", "pnl": -5.0},
        ]
        perf = engine.evaluate_goal_performance(AGIGoal.MAXIMIZE_PNL, trades)
        assert perf.trades == 3
        assert perf.wins == 2
        assert perf.pnl == 25.0
        assert perf.win_rate == pytest.approx(2 / 3)

    def test_evaluate_goal_preserve_capital(self):
        engine, _, _ = make_goal_session()
        trades = [
            {"result": "loss", "pnl": -50.0},
            {"result": "win", "pnl": 10.0},
        ]
        perf = engine.evaluate_goal_performance(AGIGoal.PRESERVE_CAPITAL, trades)
        assert perf.pnl == -40.0
        assert perf.win_rate == 0.5


class TestAGIGoalEngineRegimeChange:
    def test_handle_regime_change_updates_goal(self):
        engine, session, _ = make_goal_session()
        transition = {"from_regime": "bull", "to_regime": "bear", "confidence": 0.9}
        new_goal = engine.handle_regime_change(transition)
        assert new_goal == AGIGoal.PRESERVE_CAPITAL
        assert engine._current_goal == AGIGoal.PRESERVE_CAPITAL

    def test_handle_regime_change_creates_audit(self):
        engine, session, _ = make_goal_session()
        transition = {"from_regime": "bull", "to_regime": "crisis", "confidence": 0.95}
        engine.handle_regime_change(transition)
        audit = session.query(DecisionAuditLog).filter_by(decision_type="goal_change").first()
        assert audit is not None
        assert "CRISIS" in str(audit.input_data) or "crisis" in str(audit.input_data)

    def test_handle_regime_change_invalid_regime(self):
        engine, _, _ = make_goal_session()
        transition = {"from_regime": "bull", "to_regime": "invalid", "confidence": 0.8}
        new_goal = engine.handle_regime_change(transition)
        assert new_goal == AGIGoal.PRESERVE_CAPITAL


class TestGoalPerformance:
    def test_goal_performance_creation(self):
        perf = GoalPerformance(goal=AGIGoal.MAXIMIZE_PNL, trades=10, wins=6, pnl=50.0)
        assert perf.goal == AGIGoal.MAXIMIZE_PNL
        assert perf.trades == 10
        assert perf.wins == 6
        assert perf.pnl == 50.0
        assert perf.win_rate == 0.6

    def test_goal_performance_empty(self):
        perf = GoalPerformance(goal=AGIGoal.PRESERVE_CAPITAL)
        assert perf.trades == 0
        assert perf.wins == 0
        assert perf.pnl == 0.0
        assert perf.win_rate == 0.0


class TestREGIME_GOAL_MAP:
    def test_all_regimes_have_goal(self):
        for regime in MarketRegime:
            assert regime in REGIME_GOAL_MAP

    def test_bull_maximize_pnl(self):
        assert REGIME_GOAL_MAP[MarketRegime.BULL] == AGIGoal.MAXIMIZE_PNL

    def test_crisis_preserve_capital(self):
        assert REGIME_GOAL_MAP[MarketRegime.CRISIS] == AGIGoal.PRESERVE_CAPITAL
