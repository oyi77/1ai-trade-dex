"""
Simplified Bayesian-style hyperparameter optimizer for PolyEdge Trading Bot.

Uses random search for initial exploration followed by Gaussian-perturbation
exploitation around the best-known point. No scipy dependency required.
"""
import random
from dataclasses import dataclass

from loguru import logger
@dataclass
class OptimizationResult:
    best_params: dict
    best_score: float
    history: list  # [{params, score}, ...]
    iterations: int


class BayesianOptimizer:
    """
    Simplified Bayesian-style optimizer.

    Phase 1: random starts to explore the parameter space.
    Phase 2: exploitation via Gaussian perturbation around the best point.
    """

    def __init__(self, parameter_space: dict):
        """
        Args:
            parameter_space: Mapping of param_name -> (min, max)
        """
        self.parameter_space = parameter_space

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def optimize(self, objective_fn, n_iterations: int = 50, n_random_starts: int = 10) -> OptimizationResult:
        """
        Run the optimizer.

        Args:
            objective_fn: Callable that accepts a dict of params and returns a float score.
                          Lower scores are better (minimization).
            n_iterations: Total number of evaluations.
            n_random_starts: How many of those evaluations use random sampling.

        Returns:
            OptimizationResult with best params, score, full history, and iteration count.
        """
        history: list[dict] = []
        best_params: dict = {}
        best_score: float = float("inf")

        # Phase 1: random exploration
        random_iters = min(n_random_starts, n_iterations)
        for _ in range(random_iters):
            params = self._sample_random()
            score = objective_fn(params)
            history.append({"params": dict(params), "score": score})
            if score < best_score:
                best_score = score
                best_params = dict(params)

        # Phase 2: exploitation with decreasing noise
        exploit_iters = n_iterations - random_iters
        for i in range(exploit_iters):
            # Noise decreases from 0.3 to 0.05 as iterations progress
            noise_scale = 0.3 * (1.0 - i / max(exploit_iters, 1)) + 0.05
            params = self._sample_near_best(best_params, noise_scale)
            score = objective_fn(params)
            history.append({"params": dict(params), "score": score})
            if score < best_score:
                best_score = score
                best_params = dict(params)

        logger.debug(
            "BayesianOptimizer: best_score=%.6f after %d iterations",
            best_score,
            n_iterations,
        )

        return OptimizationResult(
            best_params=best_params,
            best_score=best_score,
            history=history,
            iterations=n_iterations,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _sample_random(self) -> dict:
        """Draw a uniformly random point from the parameter space."""
        return {
            name: random.uniform(lo, hi)
            for name, (lo, hi) in self.parameter_space.items()
        }

    def _sample_near_best(self, best_params: dict, noise_scale: float) -> dict:
        """
        Gaussian perturbation around best_params, clipped to bounds.

        Args:
            best_params: Current best parameter dict.
            noise_scale: Fraction of the parameter range used as std dev.

        Returns:
            New parameter dict within the defined bounds.
        """
        new_params: dict = {}
        for name, (lo, hi) in self.parameter_space.items():
            param_range = hi - lo
            std = param_range * noise_scale
            value = random.gauss(best_params.get(name, (lo + hi) / 2.0), std)
            value = max(lo, min(hi, value))
            new_params[name] = value
        return new_params
