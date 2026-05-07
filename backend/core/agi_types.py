"""AGI type primitives — enums, dataclasses, and serialization.

Pure types module. No runtime logic, no imports from other core modules.
All dataclasses support to_dict() / from_dict() for JSON serialization.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class MarketRegime(Enum):
    BULL = "bull"
    BEAR = "bear"
    SIDEWAYS = "sideways"
    SIDEWAYS_VOLATILE = "sideways_volatile"
    CRISIS = "crisis"
    UNKNOWN = "unknown"


class AGIGoal(Enum):
    MAXIMIZE_PNL = "maximize_pnl"
    PRESERVE_CAPITAL = "preserve_capital"
    GROW_ALLOCATION = "grow_allocation"
    REDUCE_EXPOSURE = "reduce_exposure"


class ExperimentStatus(Enum):
    DRAFT = "draft"
    BACKTEST = "backtest"
    SHADOW = "shadow"
    PAPER = "paper"
    LIVE_TRIAL = "live_trial"       # temporary live trial with capped bankroll
    LIVE_PROMOTED = "live_promoted" # permanent live with full allocation
    LIVE_FAILED = "live_failed"
    REVIEW = "review"
    RETIRED = "retired"


@dataclass
class StrategyBlock:
    signal_source: str
    filter: str
    position_sizer: str
    risk_rule: str
    exit_rule: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> StrategyBlock:
        return cls(**d)


@dataclass
class DecisionAuditEntry:
    timestamp: datetime
    regime: MarketRegime
    goal: AGIGoal
    strategy: str
    signal: dict[str, Any]
    reasoning: str
    outcome: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp.isoformat(),
            "regime": self.regime.value,
            "goal": self.goal.value,
            "strategy": self.strategy,
            "signal": self.signal,
            "reasoning": self.reasoning,
            "outcome": self.outcome,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> DecisionAuditEntry:
        return cls(
            timestamp=datetime.fromisoformat(d["timestamp"]),
            regime=MarketRegime(d["regime"]),
            goal=AGIGoal(d["goal"]),
            strategy=d["strategy"],
            signal=d["signal"],
            reasoning=d["reasoning"],
            outcome=d["outcome"],
        )


@dataclass
class KGEntity:
    entity_type: str
    entity_id: str
    properties: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> KGEntity:
        return cls(**d)


@dataclass
class KGRelation:
    from_entity: str
    to_entity: str
    relation_type: str
    weight: float
    confidence: float
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> dict[str, Any]:
        return {
            "from_entity": self.from_entity,
            "to_entity": self.to_entity,
            "relation_type": self.relation_type,
            "weight": self.weight,
            "confidence": self.confidence,
            "timestamp": self.timestamp.isoformat(),
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> KGRelation:
        return cls(
            from_entity=d["from_entity"],
            to_entity=d["to_entity"],
            relation_type=d["relation_type"],
            weight=d["weight"],
            confidence=d["confidence"],
            timestamp=datetime.fromisoformat(d["timestamp"]),
        )


@dataclass
class RegimeTransition:
    from_regime: MarketRegime
    to_regime: MarketRegime
    confidence: float
    timestamp: datetime

    def to_dict(self) -> dict[str, Any]:
        return {
            "from_regime": self.from_regime.value,
            "to_regime": self.to_regime.value,
            "confidence": self.confidence,
            "timestamp": self.timestamp.isoformat(),
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> RegimeTransition:
        return cls(
            from_regime=MarketRegime(d["from_regime"]),
            to_regime=MarketRegime(d["to_regime"]),
            confidence=d["confidence"],
            timestamp=datetime.fromisoformat(d["timestamp"]),
        )
