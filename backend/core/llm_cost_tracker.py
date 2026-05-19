"""LLM Cost Tracker — tracks LLM spending with hard caps per cycle."""
import os
from datetime import datetime, timezone, timedelta
from typing import Optional
from dataclasses import dataclass

from backend.models.database import SessionLocal
from backend.models.kg_models import LLMCostRecord as LLMCostRecordDB

from loguru import logger


DAILY_BUDGET_DEFAULT = 10.0
COST_LIMITS = {
    "strategy_generation": 0.50,
    "prompt_evolution": 0.10,
    "causal_analysis": 0.05,
    "signal_analysis": 0.02,
    "regime_detection": 0.01,
}


@dataclass
class LLMCostRecord:
    timestamp: datetime
    model: str
    token_count: int
    cost_usd: float
    purpose: str
    budget_remaining: float


@dataclass
class BudgetStatus:
    daily_budget: float
    spent_today: float
    remaining: float
    call_count: int
    period_start: datetime
    can_spend: bool


class LLMCostTracker:
    """LLM cost tracking — not yet fully wired in production."""
    def __init__(self, daily_budget: Optional[float] = None):
        logger.warning("[LLMCostTracker] Not implemented — LLM costs not tracked")
        self.daily_budget = daily_budget or float(os.environ.get("LLM_DAILY_BUDGET", DAILY_BUDGET_DEFAULT))
        self.calls: list[LLMCostRecord] = []
        self._period_start = datetime.now(timezone.utc).replace(
            hour=0, minute=0, second=0, microsecond=0
        )

    def record_call(self, model: str, token_count: int, cost_usd: float, purpose: str) -> None:
        if not self.can_spend(cost_usd):
            raise BudgetExceededError(
                f"Budget exceeded: ${cost_usd:.4f} would exceed daily limit of ${self.daily_budget:.2f}"
            )
        remaining = self.daily_budget - self._spent_today() - cost_usd
        record = LLMCostRecord(
            timestamp=datetime.now(timezone.utc),
            model=model,
            token_count=token_count,
            cost_usd=cost_usd,
            purpose=purpose,
            budget_remaining=remaining,
        )
        self.calls.append(record)
        db = SessionLocal()
        try:
            db_record = LLMCostRecordDB(
                timestamp=record.timestamp,
                model=model,
                token_count=token_count,
                cost_usd=cost_usd,
                purpose=purpose,
                budget_remaining=remaining,
                date_key=datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            )
            db.add(db_record)
            db.commit()
        except Exception:
            logger.exception("[LLMCostTracker] Failed to persist cost record to database")
        finally:
            db.close()

    def can_spend(self, estimated_cost: float) -> bool:
        if estimated_cost <= 0:
            return True
        spent = self._spent_today()
        return (spent + estimated_cost) <= self.daily_budget

    def get_budget_status(self) -> BudgetStatus:
        spent = self._spent_today()
        return BudgetStatus(
            daily_budget=self.daily_budget,
            spent_today=spent,
            remaining=self.daily_budget - spent,
            call_count=len(self._today_calls()),
            period_start=self._period_start,
            can_spend=self.can_spend(0.01),
        )

    def get_cost_by_purpose(self, purpose: str, days: int = 1) -> float:
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        return sum(
            r.cost_usd for r in self.calls
            if r.purpose == purpose and r.timestamp >= cutoff
        )

    def reset_daily_budget(self) -> None:
        self._period_start = datetime.now(timezone.utc).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        self.calls = [c for c in self.calls if c.timestamp < self._period_start]

    def _spent_today(self) -> float:
        return sum(r.cost_usd for r in self._today_calls())

    def _today_calls(self) -> list[LLMCostRecord]:
        return [c for c in self.calls if c.timestamp >= self._period_start]


class BudgetExceededError(Exception):
    pass
