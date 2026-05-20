import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.core.agi_orchestrator import (
    AGIOrchestrator,
    AGIStatus,
    AGICycleResult,
)
from backend.core.agi_types import MarketRegime, AGIGoal
from backend.models.kg_models import Base, DecisionAuditLog


def make_orchestrator_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()
    orchestrator = AGIOrchestrator(session=session)
    return orchestrator, session, engine


class TestAGIOrchestratorEmergencyStop:
    def test_emergency_stop_sets_flag(self):
        orchestrator, _, _ = make_orchestrator_session()
        assert orchestrator._emergency_stop is False
        orchestrator.emergency_stop()
        assert orchestrator._emergency_stop is True

    def test_emergency_stop_creates_audit(self):
        orchestrator, session, _ = make_orchestrator_session()
        orchestrator.emergency_stop()
        audit = (
            session.query(DecisionAuditLog)
            .filter_by(decision_type="agi_emergency_stop")
            .first()
        )
        assert audit is not None
        assert "stop" in str(audit.output_data).lower()


class TestAGIOrchestratorGetStatus:
    def test_get_status_default(self):
        orchestrator, _, _ = make_orchestrator_session()
        status = orchestrator.get_status()
        assert status.regime == MarketRegime.UNKNOWN
        assert status.goal == AGIGoal.PRESERVE_CAPITAL
        assert status.health == "healthy"
        assert status.emergency_stop is False

    def test_get_status_emergency_stopped(self):
        orchestrator, _, _ = make_orchestrator_session()
        orchestrator.emergency_stop()
        status = orchestrator.get_status()
        assert status.health == "stopped"
        assert status.emergency_stop is True


class TestAGIOrchestratorRunCycle:
    @pytest.mark.asyncio
    async def test_run_cycle_emergency_stop(self):
        orchestrator, _, _ = make_orchestrator_session()
        orchestrator.emergency_stop()
        result = await orchestrator.run_cycle()
        assert result.regime == MarketRegime.UNKNOWN
        assert result.goal == AGIGoal.PRESERVE_CAPITAL
        assert any("Emergency stop" in e for e in result.errors)

    @pytest.mark.asyncio
    async def test_run_cycle_basic(self):
        orchestrator, session, _ = make_orchestrator_session()
        result = await orchestrator.run_cycle()
        assert result.regime is not None
        assert result.goal is not None
        assert result.actions_taken >= 0


class TestAGIStatus:
    def test_creation(self):
        status = AGIStatus(
            regime=MarketRegime.BULL,
            goal=AGIGoal.MAXIMIZE_PNL,
            allocations={"strat1": 0.6, "strat2": 0.4},
            health="healthy",
        )
        assert status.regime == MarketRegime.BULL
        assert status.goal == AGIGoal.MAXIMIZE_PNL
        assert len(status.allocations) == 2
        assert status.health == "healthy"
        assert status.emergency_stop is False

    def test_to_dict(self):
        status = AGIStatus(
            regime=MarketRegime.BEAR,
            goal=AGIGoal.PRESERVE_CAPITAL,
            health="stopped",
            emergency_stop=True,
        )
        d = status.to_dict()
        assert d["regime"] == "bear"
        assert d["goal"] == "preserve_capital"
        assert d["health"] == "stopped"
        assert d["emergency_stop"] is True


class TestAGICycleResult:
    def test_creation(self):
        result = AGICycleResult(
            regime=MarketRegime.SIDEWAYS,
            goal=AGIGoal.GROW_ALLOCATION,
            actions_taken=5,
            errors=[],
        )
        assert result.regime == MarketRegime.SIDEWAYS
        assert result.goal == AGIGoal.GROW_ALLOCATION
        assert result.actions_taken == 5
        assert len(result.errors) == 0

    def test_with_errors(self):
        result = AGICycleResult(
            regime=MarketRegime.CRISIS,
            goal=AGIGoal.PRESERVE_CAPITAL,
            errors=["Regime detection failed", "Allocation failed"],
        )
        assert len(result.errors) == 2
        assert any("detection" in e.lower() for e in result.errors)

    def test_to_dict(self):
        result = AGICycleResult(
            regime=MarketRegime.UNKNOWN,
            goal=AGIGoal.PRESERVE_CAPITAL,
            actions_taken=3,
        )
        d = result.to_dict()
        assert d["regime"] == "unknown"
        assert d["actions_taken"] == 3
