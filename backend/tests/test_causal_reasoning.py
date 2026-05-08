
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.core.causal_reasoning import (
    CausalReasoner,
    CausalExplanation,
    Prediction,
)
from backend.core.agi_types import MarketRegime
from backend.models.kg_models import Base, KGEntity as KGEntityModel, KGRelation as KGRelationModel


def make_reasoner_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()
    reasoner = CausalReasoner(session=session)
    return reasoner, session, engine


class TestCausalReasonerWhyTradeFail:
    def test_bear_regime_with_bull_trade(self):
        reasoner, _, _ = make_reasoner_session()
        trade = {"direction": "up", "outcome": "loss", "strategy": "momentum"}
        context = {"regime": "bear"}
        result = reasoner.why_did_trade_fail(trade, context)
        assert "bear" in result.cause.lower() or "regime mismatch" in result.cause.lower()
        assert result.counterfactual is not None
        assert result.confidence > 0.0

    def test_bull_regime_with_bear_trade(self):
        reasoner, _, _ = make_reasoner_session()
        trade = {"direction": "down", "outcome": "loss", "strategy": "momentum"}
        context = {"regime": "bull"}
        result = reasoner.why_did_trade_fail(trade, context)
        assert "bull" in result.cause.lower() or "regime mismatch" in result.cause.lower()

    def test_loss_with_no_regime_mismatch(self):
        reasoner, _, _ = make_reasoner_session()
        trade = {"direction": "up", "outcome": "loss", "strategy": "momentum"}
        context = {"regime": "bull"}
        result = reasoner.why_did_trade_fail(trade, context)
        assert "moved against" in result.cause.lower() or "underperformed" in result.cause.lower()

    def test_evidence_includes_trade_info(self):
        reasoner, _, _ = make_reasoner_session()
        trade = {"direction": "up", "outcome": "loss", "strategy": "test"}
        context = {"regime": "bear"}
        result = reasoner.why_did_trade_fail(trade, context)
        assert len(result.evidence) > 0
        assert any("direction" in e.lower() for e in result.evidence)


class TestCausalReasonerWhyStrategySucceed:
    def test_high_win_rate_strategy(self):
        reasoner, _, _ = make_reasoner_session()
        trades = [{"outcome": "win"} for _ in range(7)] + [{"outcome": "loss"} for _ in range(3)]
        result = reasoner.why_did_strategy_succeed("momentum", MarketRegime.BULL, trades)
        assert "aligned" in result.cause.lower() or "bull" in result.cause.lower()
        assert result.confidence > 0.0

    def test_low_win_rate_strategy(self):
        reasoner, _, _ = make_reasoner_session()
        trades = [{"outcome": "loss"} for _ in range(7)] + [{"outcome": "win"} for _ in range(3)]
        result = reasoner.why_did_strategy_succeed("momentum", MarketRegime.BULL, trades)
        assert "underperformed" in result.cause.lower() or "different" in result.cause.lower()


class TestCausalReasonerWhatIf:
    def test_what_if_bull_regime(self):
        reasoner, _, _ = make_reasoner_session()
        result = reasoner.what_if(MarketRegime.BULL, "momentum")
        assert result.regime == MarketRegime.BULL
        assert result.predicted_outcome == "profit likely"
        assert result.confidence > 0.5

    def test_what_if_bear_regime(self):
        reasoner, _, _ = make_reasoner_session()
        result = reasoner.what_if(MarketRegime.BEAR, "momentum")
        assert result.regime == MarketRegime.BEAR
        assert result.predicted_outcome == "loss likely"

    def test_what_if_sideways_regime(self):
        reasoner, _, _ = make_reasoner_session()
        result = reasoner.what_if(MarketRegime.SIDEWAYS, "scalping")
        assert result.regime == MarketRegime.SIDEWAYS
        assert result.predicted_outcome == "mixed results"


class TestCausalReasonerTraceCausation:
    def test_trace_with_relations(self):
        reasoner, session, _ = make_reasoner_session()
        entity = KGEntityModel(
            entity_type="trade",
            entity_id="trade:123",
            properties={"outcome": "loss"},
        )
        related_entity = KGEntityModel(
            entity_type="signal",
            entity_id="signal:456",
            properties={"direction": "up"},
        )
        session.add_all([entity, related_entity])
        session.commit()

        rel = KGRelationModel(
            from_entity_id=entity.id,
            to_entity_id=related_entity.id,
            relation_type="caused_by",
            weight=0.8,
            confidence=0.9,
        )
        session.add(rel)
        session.commit()

        explanations = reasoner.trace_causation("trade:123")
        assert len(explanations) > 0
        assert any("caused_by" in e.cause for e in explanations)

    def test_trace_no_entity(self):
        reasoner, _, _ = make_reasoner_session()
        explanations = reasoner.trace_causation("nonexistent")
        assert len(explanations) == 0


class TestCausalExplanation:
    def test_creation(self):
        exp = CausalExplanation(
            event="Trade failed",
            cause="Regime mismatch",
            confidence=0.8,
            evidence=["Trade was bullish", "Regime was bear"],
            counterfactual="If regime was bull, trade might win",
        )
        assert exp.event == "Trade failed"
        assert exp.cause == "Regime mismatch"
        assert exp.confidence == 0.8
        assert len(exp.evidence) == 2
        assert exp.counterfactual is not None

    def test_to_dict(self):
        exp = CausalExplanation(
            event="Test",
            cause="Test cause",
            confidence=0.5,
        )
        d = exp.to_dict()
        assert d["event"] == "Test"
        assert d["cause"] == "Test cause"
        assert d["confidence"] == 0.5


class TestPrediction:
    def test_creation(self):
        pred = Prediction(
            regime=MarketRegime.BULL,
            strategy="momentum",
            predicted_outcome="profit likely",
            confidence=0.8,
        )
        assert pred.regime == MarketRegime.BULL
        assert pred.strategy == "momentum"
        assert pred.predicted_outcome == "profit likely"
        assert pred.confidence == 0.8

    def test_to_dict(self):
        pred = Prediction(
            regime=MarketRegime.BEAR,
            strategy="contrarian",
            predicted_outcome="loss likely",
            confidence=0.6,
        )
        d = pred.to_dict()
        assert d["regime"] == "bear"
        assert d["strategy"] == "contrarian"
        assert d["predicted_outcome"] == "loss likely"
