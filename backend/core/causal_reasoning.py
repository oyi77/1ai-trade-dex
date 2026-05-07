from __future__ import annotations

from typing import Any, Optional

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session

from backend.core.agi_types import MarketRegime
from backend.models.kg_models import Base, KGEntity as KGEntityModel, KGRelation as KGRelationModel


class CausalExplanation:
    def __init__(
        self,
        event: str,
        cause: str,
        confidence: float,
        evidence: list[str] | None = None,
        counterfactual: str | None = None,
    ):
        self.event = event
        self.cause = cause
        self.confidence = confidence
        self.evidence = evidence or []
        self.counterfactual = counterfactual

    def to_dict(self) -> dict[str, Any]:
        return {
            "event": self.event,
            "cause": self.cause,
            "confidence": self.confidence,
            "evidence": self.evidence,
            "counterfactual": self.counterfactual,
        }


class Prediction:
    def __init__(self, regime: MarketRegime, strategy: str, predicted_outcome: str, confidence: float):
        self.regime = regime
        self.strategy = strategy
        self.predicted_outcome = predicted_outcome
        self.confidence = confidence

    def to_dict(self) -> dict[str, Any]:
        return {
            "regime": self.regime.value,
            "strategy": self.strategy,
            "predicted_outcome": self.predicted_outcome,
            "confidence": self.confidence,
        }


class CausalReasoner:
    def __init__(self, session: Optional[Session] = None, db_url: str = "sqlite:///:memory:"):
        if session is not None:
            self._session = session
            self._owns_session = False
        else:
            self._engine = create_engine(db_url)
            Base.metadata.create_all(self._engine)
            self._session = sessionmaker(bind=self._engine)()
            self._owns_session = True

    def close(self):
        if self._owns_session:
            self._session.close()

    def why_did_trade_fail(self, trade: dict[str, Any], context: dict[str, Any]) -> CausalExplanation:
        regime = context.get("regime", "unknown")
        strategy = trade.get("strategy", "unknown")
        direction = trade.get("direction", "unknown")
        outcome = trade.get("outcome", "unknown")

        evidence = [
            f"Trade direction: {direction}",
            f"Regime: {regime}",
            f"Strategy: {strategy}",
            f"Outcome: {outcome}",
        ]

        if regime == "bear" and direction == "up":
            cause = "Regime mismatch: bullish trade in bear market"
            counterfactual = "If direction was 'down', trade might have succeeded"
        elif regime == "bull" and direction == "down":
            cause = "Regime mismatch: bearish trade in bull market"
            counterfactual = "If direction was 'up', trade might have succeeded"
        elif outcome == "loss":
            cause = "Market moved against expected direction"
            counterfactual = "If market moved as predicted, trade would have profited"
        else:
            cause = "Multiple factors contributed to failure"
            counterfactual = "Different regime or signal might have changed outcome"

        return CausalExplanation(
            event=f"Trade failed: {strategy}",
            cause=cause,
            confidence=0.7,
            evidence=evidence,
            counterfactual=counterfactual,
        )

    def why_did_strategy_succeed(
        self, strategy: str, regime: MarketRegime, trades: list[dict[str, Any]]
    ) -> CausalExplanation:
        wins = sum(1 for t in trades if t.get("outcome") == "win")
        total = len(trades)
        win_rate = wins / total if total > 0 else 0.0

        evidence = [
            f"Strategy: {strategy}",
            f"Regime: {regime.value}",
            f"Win rate: {win_rate:.1%}",
            f"Total trades: {total}",
        ]

        if win_rate >= 0.6:
            cause = f"Strategy aligned with {regime.value} regime conditions"
            counterfactual = f"In {regime.value} regime, this strategy performs well"
        else:
            cause = "Strategy underperformed despite favorable conditions"
            counterfactual = "Different strategy might perform better in this regime"

        return CausalExplanation(
            event=f"Strategy succeeded: {strategy}",
            cause=cause,
            confidence=min(win_rate + 0.2, 1.0),
            evidence=evidence,
            counterfactual=counterfactual,
        )

    def what_if(self, regime: MarketRegime, strategy: str) -> Prediction:
        _regime_str = regime.value
        if regime == MarketRegime.BULL:
            predicted = "profit likely"
            confidence = 0.8
        elif regime == MarketRegime.BEAR:
            predicted = "loss likely"
            confidence = 0.7
        elif regime == MarketRegime.SIDEWAYS:
            predicted = "mixed results"
            confidence = 0.5
        else:
            predicted = "uncertain"
            confidence = 0.3

        return Prediction(
            regime=regime,
            strategy=strategy,
            predicted_outcome=predicted,
            confidence=confidence,
        )

    def trace_causation(self, event_id: str) -> list[CausalExplanation]:
        entity = (
            self._session.query(KGEntityModel)
            .filter(KGEntityModel.entity_id == event_id)
            .first()
        )
        if not entity:
            return []

        relations = (
            self._session.query(KGRelationModel)
            .filter(KGRelationModel.from_entity_id == entity.id)
            .all()
        )

        explanations = []
        for rel in relations:
            to_entity = (
                self._session.query(KGEntityModel)
                .filter(KGEntityModel.id == rel.to_entity_id)
                .first()
            )
            if to_entity:
                explanations.append(
                    CausalExplanation(
                        event=event_id,
                        cause=f"Related to {to_entity.entity_id} via {rel.relation_type}",
                        confidence=rel.confidence,
                        evidence=[f"Relation: {rel.relation_type}", f"Weight: {rel.weight}"],
                    )
                )
        return explanations
