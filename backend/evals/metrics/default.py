"""Default concrete implementation of AGIScoreMetric."""

from backend.evals.metrics import AGIScoreMetric


class DefaultScoreMetric(AGIScoreMetric):
    """Default scoring metric that computes pass rate from results."""

    def score(self, results: dict) -> float:
        """Return pass rate as score."""
        passed = sum(1 for v in results.values() if v)
        total = len(results)
        return passed / total if total > 0 else 0.0

    def thresholds(self) -> dict:
        return {"pass": 0.8, "warn": 0.6, "fail": 0.0}
