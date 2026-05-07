"""Tests for KG, regime, and experiment database models."""

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.models.database import Base
from backend.models.kg_models import (
    DecisionAuditLog,
    ExperimentRecord,
    KGEntity,
    KGRelation,
    LLMCostRecord,
    MarketRegimeSnapshot,
)


def _make_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


def test_kg_entity_create():
    for session in _make_session():
        entity = KGEntity(
            entity_type="strategy",
            entity_id="btc_momentum",
            properties={"win_rate": 0.65, "sharpe": 1.2},
        )
        session.add(entity)
        session.commit()
        fetched = session.query(KGEntity).first()
        assert fetched.entity_type == "strategy"
        assert fetched.entity_id == "btc_momentum"
        assert fetched.properties["win_rate"] == 0.65


def test_kg_entity_unique_constraint():
    for session in _make_session():
        e1 = KGEntity(entity_type="strategy", entity_id="unique_id")
        session.add(e1)
        session.commit()
        e2 = KGEntity(entity_type="market", entity_id="unique_id")
        session.add(e2)
        try:
            session.commit()
            assert False, "Should have raised IntegrityError"
        except Exception:
            session.rollback()


def test_kg_relation_fk():
    for session in _make_session():
        e1 = KGEntity(entity_type="strategy", entity_id="btc_momentum", properties={})
        e2 = KGEntity(entity_type="regime", entity_id="bull", properties={})
        session.add_all([e1, e2])
        session.commit()
        rel = KGRelation(
            from_entity_id=e1.id,
            to_entity_id=e2.id,
            relation_type="performs_well_in",
            weight=0.85,
            confidence=0.72,
        )
        session.add(rel)
        session.commit()
        fetched = session.query(KGRelation).first()
        assert fetched.from_entity_id == e1.id
        assert fetched.to_entity_id == e2.id
        assert fetched.relation_type == "performs_well_in"
        assert fetched.weight == 0.85


def test_market_regime_snapshot():
    for session in _make_session():
        snap = MarketRegimeSnapshot(
            regime="bull",
            confidence=0.87,
            indicators={"sma_cross": "bullish", "vol_percentile": 0.3},
            regime_metadata={"source": "regime_detector"},
        )
        session.add(snap)
        session.commit()
        fetched = session.query(MarketRegimeSnapshot).first()
        assert fetched.regime == "bull"
        assert fetched.confidence == 0.87
        assert fetched.indicators["sma_cross"] == "bullish"


def test_experiment_record_defaults():
    for session in _make_session():
        exp = ExperimentRecord(
            name="btc_momentum_v2",
            strategy_composition={"signal_source": "btc_momentum", "filter": "rsi"},
        )
        session.add(exp)
        session.commit()
        fetched = session.query(ExperimentRecord).first()
        assert fetched.name == "btc_momentum_v2"
        assert fetched.status == "draft"
        assert fetched.shadow_pnl == 0.0
        assert fetched.shadow_trades == 0
        assert fetched.shadow_win_rate == 0.0
        assert fetched.promoted_at is None
        assert fetched.retired_at is None


def test_decision_audit_log():
    for session in _make_session():
        log = DecisionAuditLog(
            agent_name="test_agent",
            decision_type="trade_execution",
            input_data={"edge": 0.15, "confidence": 0.8},
            output_data={"action": "buy", "size": 50.0},
            reasoning="Strong momentum signal",
            confidence=0.85,
        )
        session.add(log)
        session.commit()
        fetched = session.query(DecisionAuditLog).first()
        assert fetched.agent_name == "test_agent"
        assert fetched.decision_type == "trade_execution"
        assert fetched.input_data["edge"] == 0.15
        assert fetched.output_data["action"] == "buy"
        assert fetched.confidence == 0.85


def test_llm_cost_record():
    for session in _make_session():
        rec = LLMCostRecord(
            model="claude-3-opus",
            token_count=1500,
            cost_usd=0.045,
            purpose="strategy_generation",
            budget_remaining=9.955,
        )
        session.add(rec)
        session.commit()
        fetched = session.query(LLMCostRecord).first()
        assert fetched.model == "claude-3-opus"
        assert fetched.token_count == 1500
        assert fetched.cost_usd == 0.045
        assert fetched.purpose == "strategy_generation"
        assert fetched.budget_remaining == 9.955
