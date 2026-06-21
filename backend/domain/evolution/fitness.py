from backend.domain.genome.models import FitnessMetrics


def normalize(value: float, min_val: float, max_val: float) -> float:
    """Normalize a value to [0, 1] range."""
    if max_val == min_val:
        return 0.5  # Avoid division by zero
    return max(0.0, min(1.0, (value - min_val) / (max_val - min_val)))


def calculate_fitness(metrics: FitnessMetrics) -> float:
    """
    Calculate fitness score from 0.0 (worst) to 1.0 (best).

    Requires at least 20 trades for meaningful evaluation. Newly created
    genomes (total_trades = 0) return a provisional score based on
    profit_factor and win_rate, allowing them to enter DRAFT pool.
    """
    if metrics.total_trades == 0:
        # Provisional score for brand-new genomes that haven't been tested yet.
        # Allows them to enter the evolution pool; they won't pass promotion gates
        # without settled trades but they can be bred/mutated.
        provisional = (
            normalize(metrics.profit_factor, 0, 5) * 0.40
            + metrics.win_rate * 0.30
            + (1.0 - metrics.max_drawdown_pct) * 0.30
        )
        return max(0.0, min(1.0, provisional))

    if metrics.total_trades < 20:
        return 0.0

    score = (
        (normalize(metrics.sharpe_ratio, -3, 3) * 0.25)
        + (metrics.win_rate * 0.15)
        + (normalize(metrics.profit_factor, 0, 5) * 0.10)
        + ((1.0 - metrics.max_drawdown_pct) * 0.15)
        + (normalize(metrics.alpha_per_trade, -1, 1) * 0.10)
        + (metrics.capital_rotation_efficiency * 0.05)
        # NEW: Regime consistency — penalize strategies with high Sharpe variance
        # across regimes. If only profitable in one regime, fitness is fragile.
        + (getattr(metrics, 'regime_consistency', 0.5) * 0.10)
        # NEW: Recency-weighted performance — last 10 trades count 2x more
        # than aggregate. Prevents stale strategies from coasting on old wins.
        + (getattr(metrics, 'recent_win_rate', metrics.win_rate) * 0.10)
    )
    return max(0.0, min(1.0, score))
