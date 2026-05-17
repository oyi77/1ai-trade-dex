"""Strategy template dataclasses for knowledge-driven strategy generation.

Provides structured entry/exit/risk criteria and regime effectiveness
maps used by FinancialKnowledgeManager and StrategySynthesizer.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List


@dataclass
class EntryCriteria:
    """Conditions that must be met to enter a trade."""
    signal: str
    confirmations: List[str] = field(default_factory=list)
    market_regime_filter: List[str] = field(default_factory=list)
    min_confidence: float = 0.5

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> EntryCriteria:
        return cls(**data)


@dataclass
class ExitCriteria:
    """Conditions that trigger trade exit."""
    take_profit_pct: float = 0.10
    stop_loss_pct: float = 0.05
    time_stop_minutes: int = 60
    signal_reversal: bool = True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ExitCriteria:
        return cls(**data)


@dataclass
class RiskParameters:
    """Position sizing and risk constraints."""
    max_position_pct: float = 0.08
    max_portfolio_heat: float = 0.70
    kelly_fraction: float = 0.30

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RiskParameters:
        return cls(**data)


@dataclass
class StrategyTemplate:
    """Complete strategy template with entry/exit/risk and regime effectiveness."""
    template_id: str
    strategy_class: str
    entry: EntryCriteria
    exit: ExitCriteria
    risk: RiskParameters
    regime_effectiveness: Dict[str, float] = field(default_factory=dict)
    description: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "template_id": self.template_id,
            "strategy_class": self.strategy_class,
            "entry": self.entry.to_dict(),
            "exit": self.exit.to_dict(),
            "risk": self.risk.to_dict(),
            "regime_effectiveness": self.regime_effectiveness,
            "description": self.description,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> StrategyTemplate:
        return cls(
            template_id=data["template_id"],
            strategy_class=data["strategy_class"],
            entry=EntryCriteria.from_dict(data.get("entry", {})),
            exit=ExitCriteria.from_dict(data.get("exit", {})),
            risk=RiskParameters.from_dict(data.get("risk", {})),
            regime_effectiveness=data.get("regime_effectiveness", {}),
            description=data.get("description", ""),
        )
