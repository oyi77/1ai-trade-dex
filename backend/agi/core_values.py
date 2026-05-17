from dataclasses import dataclass
from typing import List, Optional

@dataclass
class CoreValue:
    name: str
    priority: int
    description: str

@dataclass
class AlignmentResult:
    is_aligned: bool
    concerns: List[str]
    approved_with_conditions: bool

class CoreValues:
    VALUES = [
        CoreValue("safety", 1, "Protect capital and avoid catastrophic losses"),
        CoreValue("transparency", 2, "Decisions are explainable and auditable"),
        CoreValue("fairness", 3, "No front-running or insider information usage"),
        CoreValue("long_term_thinking", 4, "Prefer sustainable gains over short-term profits"),
        CoreValue("risk_management", 5, "Never risk more than 5% on single trade"),
    ]

    def __init__(self, misc_data: Optional[dict] = None):
        self.misc_data = misc_data or {}
        self._load_thresholds()

    def _load_thresholds(self):
        self.max_single_trade_risk = self.misc_data.get("max_single_trade_risk", 0.05)
        self.max_daily_loss = self.misc_data.get("max_daily_loss", 0.15)
        self.allow_aggressive = self.misc_data.get("allow_aggressive_tier", False)

    def check_alignment(self, proposed_action: dict) -> AlignmentResult:
        concerns = []
        if proposed_action.get("risk_tier") == "aggressive" and not self.allow_aggressive:
            concerns.append("Aggressive tier requires explicit admin override")
        if proposed_action.get("single_trade_risk", 0) > self.max_single_trade_risk:
            concerns.append(f'Single trade risk exceeds {self.max_single_trade_risk:.1%} threshold')
        return AlignmentResult(
            is_aligned=len(concerns) == 0,
            concerns=concerns,
            approved_with_conditions=len(concerns) < 2
        )

    def to_botstate_dict(self) -> dict:
        return {v.name: {"priority": v.priority, "description": v.description} for v in self.VALUES}
