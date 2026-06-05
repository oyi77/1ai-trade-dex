"""AGI Promotion Pipeline — extends experiment runner with AGI-specific promotion gates.

Key constraint from ADR-006: AGI-generated strategies CANNOT self-promote to live.
Live promotion always requires manual_approval=True.
"""

from datetime import datetime, timezone
from typing import Optional
from dataclasses import dataclass, field

from loguru import logger

from backend.core.experiment_runner import ExperimentRunner
from backend.models.kg_models import ExperimentRecord


@dataclass
class PromotionResult:
    experiment_id: str
    from_status: str
    to_status: str
    success: bool
    reason: str
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class AGIPromotionPipeline:
    MIN_TRADES_SHADOW = 100
    MIN_DAYS_SHADOW = 7
    MIN_WIN_RATE_SHADOW = 0.45
    MAX_DRAWDOWN_SHADOW = 0.25

    MIN_TRADES_PAPER = 50
    MIN_DAYS_PAPER = 3
    MIN_WIN_RATE_PAPER = 0.50

    def __init__(self, runner: Optional[ExperimentRunner] = None):
        self.runner = runner or ExperimentRunner()
        self._promotion_log: list[PromotionResult] = []

    def submit_experiment(self, experiment_id: str) -> PromotionResult:
        experiment = self._find_experiment(experiment_id)
        if experiment is None:
            return PromotionResult(
                experiment_id=experiment_id,
                from_status="unknown",
                to_status="unknown",
                success=False,
                reason=f"Experiment {experiment_id} not found",
            )
        return PromotionResult(
            experiment_id=experiment_id,
            from_status="draft",
            to_status="shadow",
            success=True,
            reason="Experiment submitted to shadow mode",
        )

    def evaluate_experiment(self, experiment_id: str) -> PromotionResult:
        evaluation = self.runner.evaluate_experiment(experiment_id)
        if evaluation is None:
            return PromotionResult(
                experiment_id=experiment_id,
                from_status="unknown",
                to_status="unknown",
                success=False,
                reason="Evaluation failed",
            )
        return PromotionResult(
            experiment_id=experiment_id,
            from_status="shadow",
            to_status="paper_eligible" if evaluation.meets_criteria else "shadow",
            success=evaluation.meets_criteria,
            reason=(
                "Meets shadow→paper criteria"
                if evaluation.meets_criteria
                else "Does not meet criteria"
            ),
        )

    def promote_to_paper(self, experiment_id: str) -> PromotionResult:
        result = self.runner.promote_experiment(experiment_id)
        promotion = PromotionResult(
            experiment_id=experiment_id,
            from_status="shadow",
            to_status="paper",
            success=result.promoted,
            reason=result.message,
        )
        self._promotion_log.append(promotion)
        return promotion

    def promote_to_live(
        self, experiment_id: str, manual_approval: bool = False
    ) -> PromotionResult:
        if not manual_approval:
            return PromotionResult(
                experiment_id=experiment_id,
                from_status="paper",
                to_status="paper",
                success=False,
                reason="AGI-generated strategies require manual approval for live promotion (ADR-006)",
            )
        gate_result = self._check_live_profitability_gate(experiment_id)
        if gate_result is not None and not gate_result.passed:
            return PromotionResult(
                experiment_id=experiment_id,
                from_status="paper",
                to_status="paper",
                success=False,
                reason="Profitability gate failed: " + "; ".join(gate_result.reasons),
            )
        result = self.runner.promote_experiment(experiment_id)
        promotion = PromotionResult(
            experiment_id=experiment_id,
            from_status="paper",
            to_status="live",
            success=result.promoted,
            reason=(
                "Manually approved for live promotion"
                if result.promoted
                else result.message
            ),
        )
        self._promotion_log.append(promotion)
        return promotion

    def retire_experiment(
        self, experiment_id: str, reason: str = ""
    ) -> PromotionResult:
        self.runner.retire_experiment(experiment_id, reason)
        promotion = PromotionResult(
            experiment_id=experiment_id,
            from_status="active",
            to_status="retired",
            success=True,
            reason=reason or "Experiment retired",
        )
        self._promotion_log.append(promotion)
        return promotion

    def get_promotion_log(self) -> list[PromotionResult]:
        return list(self._promotion_log)

    def _find_experiment(self, experiment_id: str):
        try:
            session = self.runner._session
            experiment = (
                session.query(ExperimentRecord)
                .filter_by(name=experiment_id, status="shadow")
                .first()
            )
            if not experiment:
                experiment = ExperimentRecord(
                    name=experiment_id,
                    strategy_composition={"name": experiment_id},
                    status="shadow",
                )
                session.add(experiment)
                session.commit()
            return experiment
        except Exception:
            logger.exception(
                f"AGIPromotionPipeline: failed to find experiment {experiment_id}"
            )
            return None

    def _check_live_profitability_gate(self, experiment_id: str):
        try:
            experiment = (
                self.runner._session.query(ExperimentRecord)
                .filter_by(id=int(experiment_id))
                .first()
            )
            if experiment is None or not experiment.strategy_name:
                return None
            from backend.core.profitability_gates import evaluate_strategy_paper_gate

            return evaluate_strategy_paper_gate(
                self.runner._session,
                strategy_name=experiment.strategy_name,
                min_trades=self.MIN_TRADES_PAPER,
            )
        except Exception:
            logger.exception(
                f"AGIPromotionPipeline: profitability gate failed for experiment {experiment_id}"
            )
            return None
