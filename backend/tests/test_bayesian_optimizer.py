"""Tests for backend/ai/bayesian_optimizer.py — simplified Bayesian optimizer."""

from backend.ai.bayesian_optimizer import BayesianOptimizer, OptimizationResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _quadratic(params: dict) -> float:
    """x^2 — minimum at x=0."""
    return params["x"] ** 2


def _multivar_quadratic(params: dict) -> float:
    """x^2 + y^2 — minimum at (0, 0)."""
    return params["x"] ** 2 + params["y"] ** 2


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_optimize_finds_minimum():
    """Optimizer should converge near x=0 for the x^2 objective."""
    opt = BayesianOptimizer(parameter_space={"x": (-5.0, 5.0)})
    result = opt.optimize(_quadratic, n_iterations=60, n_random_starts=15)

    assert isinstance(result, OptimizationResult)
    # Best score should be small (near 0)
    assert result.best_score < 1.0
    # Best x should be close to 0
    assert abs(result.best_params["x"]) < 1.5


def test_respects_bounds():
    """All sampled parameter values must stay within the declared bounds."""
    space = {"x": (-2.0, 3.0), "y": (0.5, 4.5)}
    opt = BayesianOptimizer(parameter_space=space)

    collected: list[dict] = []

    def recording_fn(params: dict) -> float:
        collected.append(dict(params))
        return _multivar_quadratic(params)

    opt.optimize(recording_fn, n_iterations=40, n_random_starts=10)

    for params in collected:
        assert -2.0 <= params["x"] <= 3.0, f"x={params['x']} out of bounds"
        assert 0.5 <= params["y"] <= 4.5, f"y={params['y']} out of bounds"


def test_history_tracked():
    """History list must contain exactly n_iterations entries."""
    opt = BayesianOptimizer(parameter_space={"x": (0.0, 1.0)})
    n = 25
    result = opt.optimize(lambda p: p["x"], n_iterations=n, n_random_starts=5)

    assert result.iterations == n
    assert len(result.history) == n

    for entry in result.history:
        assert "params" in entry
        assert "score" in entry
