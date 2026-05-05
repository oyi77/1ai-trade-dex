from backend.domain.genome.models import FitnessMetrics


def normalize(value: float, min_val: float, max_val: float) -> float:
    """Normalize a value to [0, 1] range."""
    if max_val == min_val:
        return 0.5  # Avoid division by zero
    return max(0.0, min(1.0, (value - min_val) / (max_val - min_val)))


def calculate_fitness(metrics: FitnessMetrics) -> float:
    """
    Calculate fitness score from 0.0 (worst) to 1.0 (best).
    Requires at least 20 trades for meaningful evaluation.
    """
    if metrics.total_trades < 20:
        return 0.0
    
    score = (
        (normalize(metrics.sharpe_ratio, -3, 3) * 0.30) +
        (metrics.win_rate * 0.20) +
        (normalize(metrics.profit_factor, 0, 5) * 0.15) +
        ((1.0 - metrics.max_drawdown_pct) * 0.15) +
        (normalize(metrics.alpha_per_trade, -1, 1) * 0.10) +
        (metrics.capital_rotation_efficiency * 0.10)
    )
    return max(0.0, min(1.0, score))