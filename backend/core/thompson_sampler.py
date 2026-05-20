"""
Thompson sampling capital allocator.
Uses per-strategy Beta(alpha, beta) distributions.
Prior: Beta(1, 1) = uniform.
Updates: alpha += 1 on win, beta += 1 on loss.
No new dependencies — uses stdlib random.betavariate().
"""

import json
import random
from pathlib import Path
from typing import Dict, List, Tuple
from collections import defaultdict

from loguru import logger


class ThompsonSampler:
    """
    Per-strategy Thompson sampling allocator.
    Maintains Beta(alpha, beta) posteriors per strategy.
    Samples to rank strategies; allocates capital proportionally.
    """

    def __init__(self, min_capital: float = 1.0):
        """
        min_capital: minimum dollar amount to allocate to any active strategy.
        """
        self.min_capital = min_capital
        # strategy -> (alpha, beta)
        self._posteriors: Dict[str, Tuple[float, float]] = defaultdict(
            lambda: (1.0, 1.0)
        )

    def update(self, strategy: str, won: bool) -> None:
        """Update posterior after a trade outcome."""
        alpha, beta = self._posteriors[strategy]
        if won:
            self._posteriors[strategy] = (alpha + 1.0, beta)
        else:
            self._posteriors[strategy] = (alpha, beta + 1.0)

    def sample(self, strategy: str) -> float:
        """Draw a sample from the strategy's Beta posterior."""
        alpha, beta = self._posteriors[strategy]
        return random.betavariate(alpha, beta)

    def allocate(self, strategies: List[str], total_capital: float) -> Dict[str, float]:
        """
        Allocate total_capital across strategies using Thompson sampling.
        Returns dict of strategy -> dollar amount.
        Guarantees min_capital per strategy if total allows.
        Strategies with 0 capital get 0 (not forced to min).
        """
        if not strategies or total_capital <= 0:
            return {s: 0.0 for s in strategies}

        # Draw samples
        samples = {s: self.sample(s) for s in strategies}
        total_sample = sum(samples.values())

        if total_sample == 0:
            # Uniform fallback
            per = total_capital / len(strategies)
            return {s: per for s in strategies}

        # Proportional allocation
        raw = {s: (v / total_sample) * total_capital for s, v in samples.items()}

        # Apply minimum capital constraint
        # If any strategy gets less than min_capital, redistribute
        below_min = [s for s in strategies if raw[s] < self.min_capital]
        above_min = [s for s in strategies if raw[s] >= self.min_capital]

        if below_min and above_min:
            # Give min_capital to below-min strategies, redistribute remainder
            reserved = self.min_capital * len(below_min)
            remaining = total_capital - reserved
            if remaining > 0:
                above_total = sum(raw[s] for s in above_min)
                for s in above_min:
                    raw[s] = (
                        (raw[s] / above_total) * remaining
                        if above_total > 0
                        else remaining / len(above_min)
                    )
            for s in below_min:
                raw[s] = self.min_capital

        return raw

    def win_probability(self, strategy: str) -> float:
        """Return posterior mean win probability for a strategy."""
        alpha, beta = self._posteriors[strategy]
        return alpha / (alpha + beta)

    def sample_count(self, strategy: str) -> int:
        """Return effective number of trades recorded (alpha + beta - 2)."""
        alpha, beta = self._posteriors[strategy]
        return max(0, int(alpha + beta - 2))

    def all_strategies(self) -> List[str]:
        return list(self._posteriors.keys())

    def summary(self) -> Dict[str, Dict]:
        return {
            s: {
                "alpha": a,
                "beta": b,
                "win_prob": a / (a + b),
                "n": max(0, int(a + b - 2)),
            }
            for s, (a, b) in self._posteriors.items()
        }

    def save(self, path: str = "thompson_state.json") -> None:
        try:
            data = {s: [a, b] for s, (a, b) in self._posteriors.items()}
            Path(path).write_text(json.dumps(data, indent=2))
        except Exception as e:
            logger.error(f"Failed to save Thompson state: {e}")

    def load(self, path: str = "thompson_state.json") -> None:
        try:
            p = Path(path)
            if not p.exists():
                return
            data = json.loads(p.read_text())
            for strategy, (alpha, beta) in data.items():
                self._posteriors[strategy] = (float(alpha), float(beta))
            logger.info(f"Loaded Thompson state: {len(data)} strategies from {path}")
        except Exception as e:
            logger.error(f"Failed to load Thompson state: {e}")
