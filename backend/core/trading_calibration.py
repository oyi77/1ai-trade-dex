"""
Per-strategy Brier score tracker with online beta calibration.
Extends calibration_tracker.py pattern for trading predictions.
No new dependencies — uses stdlib math only.
"""
from typing import Optional, Dict, List, Tuple
from collections import defaultdict


class BetaDistribution:
    """Online beta distribution for probability calibration. No scipy needed."""
    def __init__(self, alpha: float = 1.0, beta: float = 1.0):
        self.alpha = alpha
        self.beta = beta

    def update(self, outcome: int) -> None:
        """Update with binary outcome (1=win, 0=loss)."""
        if outcome == 1:
            self.alpha += 1.0
        else:
            self.beta += 1.0

    def mean(self) -> float:
        return self.alpha / (self.alpha + self.beta)

    def calibrate(self, raw_prob: float) -> float:
        """Shrink raw probability toward beta posterior mean."""
        n = self.alpha + self.beta - 2  # effective sample count
        weight = min(n / max(n + 10, 1), 0.9)  # max 90% weight on data
        return weight * self.mean() + (1 - weight) * raw_prob


class TradingCalibration:
    """
    Per-strategy calibration tracker.
    Records predictions, computes Brier scores, maintains online beta calibration.
    """

    def __init__(self):
        # strategy -> list of (predicted_prob, actual_outcome)
        self._records: Dict[str, List[Tuple[float, int]]] = defaultdict(list)
        # strategy -> BetaDistribution
        self._betas: Dict[str, BetaDistribution] = defaultdict(BetaDistribution)

    def record(self, strategy: str, predicted_prob: float, actual_outcome: int) -> None:
        """
        Record a prediction outcome.
        predicted_prob: float in [0, 1]
        actual_outcome: 1 for win, 0 for loss
        """
        self._records[strategy].append((predicted_prob, actual_outcome))
        self._betas[strategy].update(actual_outcome)

    def brier_score(self, strategy: str) -> Optional[float]:
        """
        Compute Brier score for a strategy.
        Lower is better. Returns None if fewer than 5 records.
        """
        records = self._records.get(strategy, [])
        if len(records) < 5:
            return None
        return sum((p - o) ** 2 for p, o in records) / len(records)

    def calibrate_probability(self, strategy: str, raw_prob: float) -> float:
        """
        Return calibrated probability for a strategy.
        Falls back to raw_prob if insufficient data.
        """
        beta = self._betas.get(strategy)
        if beta is None:
            return raw_prob
        n = beta.alpha + beta.beta - 2
        if n < 10:
            return raw_prob  # cold start: trust raw
        return beta.calibrate(raw_prob)

    def win_rate(self, strategy: str) -> Optional[float]:
        """Return empirical win rate. None if no data."""
        records = self._records.get(strategy, [])
        if not records:
            return None
        return sum(o for _, o in records) / len(records)

    def sample_count(self, strategy: str) -> int:
        """Return number of recorded predictions for a strategy."""
        return len(self._records.get(strategy, []))

    def all_strategies(self) -> List[str]:
        return list(self._records.keys())

    def summary(self, strategy: str) -> Dict:
        """Return a summary dict for a strategy."""
        return {
            'strategy': strategy,
            'n': self.sample_count(strategy),
            'brier_score': self.brier_score(strategy),
            'win_rate': self.win_rate(strategy),
            'beta_mean': self._betas[strategy].mean() if strategy in self._betas else None,
        }
