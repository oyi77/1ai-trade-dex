"""AGIOrchestrator status/result value objects."""

from __future__ import annotations

from typing import Any

from backend.core.agi_types import MarketRegime, AGIGoal


class AGIStatus:
    def __init__(
        self,
        regime: MarketRegime,
        goal: AGIGoal,
        allocations: dict[str, float] | None = None,
        health: str = "healthy",
        emergency_stop: bool = False,
    ):
        self.regime = regime
        self.goal = goal
        self.allocations = allocations or {}
        self.health = health
        self.emergency_stop = emergency_stop

    def to_dict(self) -> dict[str, Any]:
        return {
            "regime": self.regime.value,
            "goal": self.goal.value,
            "allocations": self.allocations,
            "health": self.health,
            "emergency_stop": self.emergency_stop,
        }



class AGICycleResult:
    def __init__(
        self,
        regime: MarketRegime,
        goal: AGIGoal,
        actions_taken: int = 0,
        errors: list[str] | None = None,
    ):
        self.regime = regime
        self.goal = goal
        self.actions_taken = actions_taken
        self.errors = errors or []

    def to_dict(self) -> dict[str, Any]:
        return {
            "regime": self.regime.value,
            "goal": self.goal.value,
            "actions_taken": self.actions_taken,
            "errors": self.errors,
        }


