from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session

from backend.core.agi_types import AGIGoal, MarketRegime, DecisionAuditEntry
from backend.models.kg_models import Base, DecisionAuditLog


REGIME_GOAL_MAP = {
    MarketRegime.BULL: AGIGoal.MAXIMIZE_PNL,
    MarketRegime.BEAR: AGIGoal.PRESERVE_CAPITAL,
    MarketRegime.SIDEWAYS: AGIGoal.GROW_ALLOCATION,
    MarketRegime.SIDEWAYS_VOLATILE: AGIGoal.REDUCE_EXPOSURE,
    MarketRegime.CRISIS: AGIGoal.PRESERVE_CAPITAL,
    MarketRegime.UNKNOWN: AGIGoal.PRESERVE_CAPITAL,
}


class GoalPerformance:
    def __init__(self, goal: AGIGoal, trades: int = 0, wins: int = 0, pnl: float = 0.0):
        self.goal = goal
        self.trades = trades
        self.wins = wins
        self.pnl = pnl
        self.win_rate = wins / trades if trades > 0 else 0.0


class DiagnosisResult:
    def __init__(self, error_type: str, recoverable: bool, suggestion: str, context: dict[str, Any] | None = None):
        self.error_type = error_type
        self.recoverable = recoverable
        self.suggestion = suggestion
        self.context = context or {}


class RecoveryResult:
    def __init__(self, success: bool, action_taken: str, attempts: int = 1):
        self.success = success
        self.action_taken = action_taken
        self.attempts = attempts


class AGIGoalEngine:
    def __init__(self, session: Optional[Session] = None, db_url: str = "sqlite:///:memory:"):
        self._current_goal = None
        self._goal_reason = None
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

    def get_current_goal(self, regime: MarketRegime) -> AGIGoal:
        if self._current_goal is not None:
            return self._current_goal
        return REGIME_GOAL_MAP.get(regime, AGIGoal.PRESERVE_CAPITAL)

    def set_goal(self, goal: AGIGoal, reason: str) -> DecisionAuditEntry:
        old_goal = self._current_goal
        self._current_goal = goal
        self._goal_reason = reason

        audit = DecisionAuditLog(
            timestamp=datetime.now(timezone.utc),
            agent_name="AGIGoalEngine",
            decision_type="goal_change",
            input_data={"old_goal": old_goal.value if old_goal else None, "new_goal": goal.value, "reason": reason},
            output_data={"status": "success"},
            confidence=1.0,
            reasoning=f"Goal changed from {old_goal} to {goal}: {reason}",
        )
        self._session.add(audit)
        self._session.commit()

        return DecisionAuditEntry(
            timestamp=audit.timestamp,
            regime=regime if isinstance((regime := getattr(self, '_last_regime', None)), MarketRegime) else MarketRegime.UNKNOWN,
            goal=goal,
            strategy="",
            signal={},
            reasoning=f"Goal set to {goal.value}: {reason}",
            outcome="success",
        )

    def evaluate_goal_performance(self, goal: AGIGoal, trades: list[dict[str, Any]]) -> GoalPerformance:
        total = len(trades)
        wins = sum(1 for t in trades if t.get("result") == "win")
        pnl = sum(t.get("pnl", 0.0) for t in trades)
        return GoalPerformance(goal=goal, trades=total, wins=wins, pnl=pnl)

    def handle_regime_change(self, transition: dict[str, Any]) -> AGIGoal:
        _from_regime = transition.get("from_regime")
        to_regime = transition.get("to_regime")
        if isinstance(to_regime, str):
            try:
                to_regime = MarketRegime(to_regime)
            except ValueError:
                to_regime = MarketRegime.UNKNOWN
        if isinstance(to_regime, MarketRegime):
            self._last_regime = to_regime
            new_goal = REGIME_GOAL_MAP.get(to_regime, AGIGoal.PRESERVE_CAPITAL)
            self.set_goal(new_goal, f"Regime changed to {to_regime.value}")
            return new_goal
        return self.get_current_goal(MarketRegime.UNKNOWN)
