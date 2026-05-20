"""Trading Accuracy Evaluation Suite.

Evaluates strategy prediction accuracy, calibration, and Brier scores
against historical settled trades.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from loguru import logger


@dataclass
class AccuracyResult:
    """Result of a trading accuracy evaluation."""

    strategy: str
    total_predictions: int = 0
    correct_predictions: int = 0
    accuracy: float = 0.0
    brier_score: float = 0.0
    calibration_error: float = 0.0
    passed: bool = False
    threshold_accuracy: float = 0.50
    threshold_brier: float = 0.30

    def to_dict(self) -> dict:
        return {
            "strategy": self.strategy,
            "total_predictions": self.total_predictions,
            "correct_predictions": self.correct_predictions,
            "accuracy": round(self.accuracy, 4),
            "brier_score": round(self.brier_score, 4),
            "calibration_error": round(self.calibration_error, 4),
            "passed": self.passed,
        }


class TradingAccuracySuite:
    """Evaluates trading prediction accuracy across strategies."""

    def __init__(
        self,
        min_trades: int = 20,
        accuracy_threshold: float = 0.50,
        brier_threshold: float = 0.30,
    ):
        self.min_trades = min_trades
        self.accuracy_threshold = accuracy_threshold
        self.brier_threshold = brier_threshold

    def evaluate(
        self,
        strategy: str,
        lookback_days: int = 30,
        trading_mode: str = "live",
    ) -> AccuracyResult:
        """Evaluate accuracy for a single strategy."""
        result = AccuracyResult(
            strategy=strategy,
            threshold_accuracy=self.accuracy_threshold,
            threshold_brier=self.brier_threshold,
        )

        try:
            from backend.models.outcome_tables import StrategyOutcome
            from backend.models.database import SessionLocal

            db = SessionLocal()
            try:
                cutoff = datetime.now(timezone.utc) - timedelta(days=lookback_days)
                outcomes = (
                    db.query(StrategyOutcome)
                    .filter(
                        StrategyOutcome.strategy == strategy,
                        StrategyOutcome.trading_mode == trading_mode,
                        StrategyOutcome.settled_at >= cutoff,
                        StrategyOutcome.result.in_(["win", "loss"]),
                    )
                    .all()
                )

                result.total_predictions = len(outcomes)
                if result.total_predictions < self.min_trades:
                    return result

                result.correct_predictions = sum(
                    1 for o in outcomes if o.result == "win"
                )
                result.accuracy = result.correct_predictions / result.total_predictions

                # Brier score
                pairs = [
                    (o.model_probability, 1 if o.result == "win" else 0)
                    for o in outcomes
                    if o.model_probability is not None
                ]
                if pairs:
                    result.brier_score = sum((p - a) ** 2 for p, a in pairs) / len(
                        pairs
                    )

                # Expected Calibration Error (ECE)
                result.calibration_error = self._ece(outcomes)

                result.passed = (
                    result.accuracy >= self.accuracy_threshold
                    and result.brier_score <= self.brier_threshold
                )

            finally:
                db.close()

        except Exception as e:
            logger.error("[TradingAccuracySuite] Failed for '%s': %s", strategy, e)

        return result

    def evaluate_all(
        self, lookback_days: int = 30, trading_mode: str = "live"
    ) -> list[AccuracyResult]:
        """Evaluate all active strategies."""
        results = []
        try:
            from backend.models.database import SessionLocal, StrategyConfig

            db = SessionLocal()
            try:
                active = (
                    db.query(StrategyConfig)
                    .filter(StrategyConfig.enabled.is_(True))
                    .all()
                )
                for cfg in active:
                    results.append(
                        self.evaluate(cfg.strategy_name, lookback_days, trading_mode)
                    )
            finally:
                db.close()
        except Exception as e:
            logger.error("[TradingAccuracySuite] evaluate_all failed: %s", e)
        return results

    def _ece(self, outcomes, n_bins: int = 10) -> float:
        """Expected Calibration Error."""
        bins: dict[int, list[tuple[float, int]]] = {}
        for o in outcomes:
            if o.model_probability is None:
                continue
            bucket = min(int(o.model_probability * n_bins), n_bins - 1)
            actual = 1 if o.result == "win" else 0
            bins.setdefault(bucket, []).append((o.model_probability, actual))

        if not bins:
            return 0.0

        total = sum(len(v) for v in bins.values())
        ece = 0.0
        for bucket, pairs in bins.items():
            mean_pred = sum(p for p, _ in pairs) / len(pairs)
            mean_actual = sum(a for _, a in pairs) / len(pairs)
            ece += (len(pairs) / total) * abs(mean_pred - mean_actual)

        return ece
