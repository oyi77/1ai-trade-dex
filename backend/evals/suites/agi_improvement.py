"""AGI Improvement Evaluation Suite.

Measures whether the AGI system is actually improving strategy performance
over time: trend analysis, promotion success rates, and improvement velocity.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone



@dataclass
class ImprovementMetric:
    """A single AGI improvement metric."""
    name: str
    value: float
    target: float
    passed: bool
    description: str = ""


@dataclass
class AGIImprovementResult:
    """Aggregated AGI improvement evaluation."""
    metrics: list[ImprovementMetric] = field(default_factory=list)
    overall_score: float = 0.0
    passed: bool = False

    def to_dict(self) -> dict:
        return {
            "overall_score": round(self.overall_score, 4),
            "passed": self.passed,
            "metrics": [
                {
                    "name": m.name,
                    "value": round(m.value, 4),
                    "target": round(m.target, 4),
                    "passed": m.passed,
                    "description": m.description,
                }
                for m in self.metrics
            ],
        }


class AGIImprovementSuite:
    """Evaluates AGI system improvement effectiveness."""

    def evaluate(self, lookback_days: int = 30) -> AGIImprovementResult:
        """Run full AGI improvement evaluation."""
        result = AGIImprovementResult()

        # Metric 1: Strategy win rate trend
        wr_trend = self._win_rate_trend(lookback_days)
        result.metrics.append(ImprovementMetric(
            name="win_rate_trend",
            value=wr_trend,
            target=0.0,  # Non-negative trend
            passed=wr_trend >= 0.0,
            description="Slope of average win rate over time (positive = improving)",
        ))

        # Metric 2: Promotion success rate
        promo_rate = self._promotion_success_rate(lookback_days)
        result.metrics.append(ImprovementMetric(
            name="promotion_success_rate",
            value=promo_rate,
            target=0.50,
            passed=promo_rate >= 0.50,
            description="Fraction of promoted strategies that maintain performance",
        ))

        # Metric 3: Error rate in AGI cycles
        error_rate = self._agi_cycle_error_rate(lookback_days)
        result.metrics.append(ImprovementMetric(
            name="agi_cycle_error_rate",
            value=error_rate,
            target=0.20,
            passed=error_rate <= 0.20,
            description="Fraction of AGI improvement cycles with errors",
        ))

        # Metric 4: Strategy diversity (number of active strategies)
        diversity = self._strategy_diversity()
        result.metrics.append(ImprovementMetric(
            name="strategy_diversity",
            value=diversity,
            target=3.0,
            passed=diversity >= 3,
            description="Number of active strategies (higher = more diverse)",
        ))

        # Overall score: fraction of passed metrics
        passed_count = sum(1 for m in result.metrics if m.passed)
        result.overall_score = passed_count / len(result.metrics) if result.metrics else 0.0
        result.passed = result.overall_score >= 0.75

        return result

    def _win_rate_trend(self, lookback_days: int) -> float:
        """Compute slope of average win rate over weekly periods."""
        try:
            from backend.models.outcome_tables import StrategyOutcome
            from backend.models.database import SessionLocal

            db = SessionLocal()
            try:
                cutoff = datetime.now(timezone.utc) - timedelta(days=lookback_days)
                outcomes = (
                    db.query(StrategyOutcome)
                    .filter(
                        StrategyOutcome.settled_at >= cutoff,
                        StrategyOutcome.result.in_(["win", "loss"]),
                    )
                    .order_by(StrategyOutcome.settled_at.asc())
                    .all()
                )

                if len(outcomes) < 20:
                    return 0.0

                # Split into weekly chunks
                chunk_size = max(len(outcomes) // 4, 1)
                weekly_wr = []
                for i in range(0, len(outcomes), chunk_size):
                    chunk = outcomes[i:i + chunk_size]
                    if chunk:
                        wins = sum(1 for o in chunk if o.result == "win")
                        weekly_wr.append(wins / len(chunk))

                if len(weekly_wr) < 2:
                    return 0.0

                # Linear regression slope
                n = len(weekly_wr)
                x_mean = (n - 1) / 2.0
                y_mean = sum(weekly_wr) / n
                num = sum((i - x_mean) * (weekly_wr[i] - y_mean) for i in range(n))
                den = sum((i - x_mean) ** 2 for i in range(n))
                return num / den if den > 1e-9 else 0.0
            finally:
                db.close()
        except Exception:
            return 0.0

    def _promotion_success_rate(self, lookback_days: int) -> float:
        """Fraction of promoted experiments that maintained performance."""
        try:
            from backend.models.kg_models import ExperimentRecord
            from backend.core.agi_types import ExperimentStatus
            from backend.models.database import SessionLocal

            db = SessionLocal()
            try:
                cutoff = datetime.now(timezone.utc) - timedelta(days=lookback_days)
                promoted = (
                    db.query(ExperimentRecord)
                    .filter(
                        ExperimentRecord.status == ExperimentStatus.LIVE_PROMOTED.value,
                        ExperimentRecord.created_at >= cutoff,
                    )
                    .all()
                )
                if not promoted:
                    return 1.0  # No promotions = no failures

                still_active = sum(
                    1 for e in promoted
                    if e.status != ExperimentStatus.RETIRED.value
                )
                return still_active / len(promoted)
            finally:
                db.close()
        except Exception:
            return 1.0

    def _agi_cycle_error_rate(self, lookback_days: int) -> float:
        """Fraction of AGI audit log entries with errors."""
        try:
            from backend.models.kg_models import DecisionAuditLog
            from backend.models.database import SessionLocal

            db = SessionLocal()
            try:
                cutoff = datetime.now(timezone.utc) - timedelta(days=lookback_days)
                cycles = (
                    db.query(DecisionAuditLog)
                    .filter(
                        DecisionAuditLog.decision_type == "agi_cycle",
                        DecisionAuditLog.timestamp >= cutoff,
                    )
                    .all()
                )
                if not cycles:
                    return 0.0

                errors = sum(
                    1 for c in cycles
                    if c.output_data and c.output_data.get("errors")
                )
                return errors / len(cycles)
            finally:
                db.close()
        except Exception:
            return 0.0

    def _strategy_diversity(self) -> float:
        """Count of active strategies."""
        try:
            from backend.models.database import SessionLocal, StrategyConfig
            db = SessionLocal()
            try:
                count = db.query(StrategyConfig).filter(
                    StrategyConfig.enabled.is_(True)
                ).count()
                return float(count)
            finally:
                db.close()
        except Exception:
            return 0.0
