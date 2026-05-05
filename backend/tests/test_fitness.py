import pytest
from backend.domain.evolution.fitness import calculate_fitness, normalize
from backend.domain.genome.models import FitnessMetrics


def test_normalize_function():
    """Test normalize helper function."""
    assert normalize(0.5, 0, 1) == 0.5
    assert normalize(0, 0, 1) == 0.0
    assert normalize(1, 0, 1) == 1.0
    assert normalize(2, 0, 1) == 1.0  # Clamped to max
    assert normalize(-1, 0, 1) == 0.0  # Clamped to min
    assert normalize(0.5, -1, 1) == 0.75


def test_calculate_fitness_insufficient_trades():
    """Test fitness with insufficient trades returns 0."""
    metrics = FitnessMetrics(
        sharpe_ratio=2.0,
        win_rate=0.7,
        total_trades=19  # Less than 20
    )
    fitness = calculate_fitness(metrics)
    assert fitness == 0.0


def test_calculate_fitness_minimum_trades():
    """Test fitness with exactly 20 trades."""
    metrics = FitnessMetrics(
        sharpe_ratio=1.0,
        win_rate=0.6,
        profit_factor=1.5,
        max_drawdown_pct=0.2,
        alpha_per_trade=0.0,
        capital_rotation_efficiency=0.5,
        total_trades=20
    )
    fitness = calculate_fitness(metrics)
    assert fitness > 0.0
    assert fitness <= 1.0


def test_calculate_fitness_perfect_metrics():
    """Test fitness with perfect metrics."""
    metrics = FitnessMetrics(
        sharpe_ratio=3.0,      # Max normalized to 1.0
        win_rate=1.0,          # Max
        profit_factor=5.0,     # Max normalized to 1.0
        max_drawdown_pct=0.0,  # Min (1.0 - 0.0 = 1.0)
        alpha_per_trade=1.0,    # Max normalized to 1.0
        capital_rotation_efficiency=1.0,
        total_trades=100
    )
    fitness = calculate_fitness(metrics)
    assert fitness == 1.0


def test_calculate_fitness_poor_metrics():
    """Test fitness with poor metrics."""
    metrics = FitnessMetrics(
        sharpe_ratio=-3.0,     # Min normalized to 0.0
        win_rate=0.0,          # Min
        profit_factor=0.0,     # Min normalized to 0.0
        max_drawdown_pct=1.0,  # Max (1.0 - 1.0 = 0.0)
        alpha_per_trade=-1.0,   # Min normalized to 0.0
        capital_rotation_efficiency=0.0,
        total_trades=100
    )
    fitness = calculate_fitness(metrics)
    assert fitness == 0.0


def test_calculate_fitness_balanced_metrics():
    """Test fitness with balanced metrics."""
    metrics = FitnessMetrics(
        sharpe_ratio=1.5,      # Normalized: (1.5+3)/(3+3) = 0.75
        win_rate=0.6,          # 0.6
        profit_factor=2.0,     # Normalized: 2.0/5 = 0.4
        max_drawdown_pct=0.25,  # 1.0 - 0.25 = 0.75
        alpha_per_trade=0.1,    # Normalized: (0.1+1)/(1+1) = 0.55
        capital_rotation_efficiency=0.6,
        total_trades=100
    )
    fitness = calculate_fitness(metrics)
    
    # Calculate expected score
    expected = (
        (0.75 * 0.30) + (0.6 * 0.20) + (0.4 * 0.15) + 
        (0.75 * 0.15) + (0.55 * 0.10) + (0.6 * 0.10)
    )
    
    assert abs(fitness - expected) < 0.01


def test_calculate_fitness_edge_cases():
    """Test fitness with edge case values."""
    # Test with zero sharpe but good other metrics
    metrics1 = FitnessMetrics(
        sharpe_ratio=0.0,
        win_rate=0.8,
        profit_factor=2.0,
        max_drawdown_pct=0.1,
        alpha_per_trade=0.1,
        capital_rotation_efficiency=0.8,
        total_trades=100
    )
    fitness1 = calculate_fitness(metrics1)
    assert 0.0 < fitness1 < 1.0
    
    # Test with negative sharpe
    metrics2 = FitnessMetrics(
        sharpe_ratio=-1.0,
        win_rate=0.5,
        profit_factor=1.0,
        max_drawdown_pct=0.3,
        alpha_per_trade=0.0,
        capital_rotation_efficiency=0.5,
        total_trades=100
    )
    fitness2 = calculate_fitness(metrics2)
    assert 0.0 < fitness2 < 0.5


def test_fitness_clamping():
    """Test that fitness is properly clamped between 0.0 and 1.0."""
    # Test upper bound clamping
    metrics_high = FitnessMetrics(
        sharpe_ratio=10.0,  # Way above max
        win_rate=2.0,       # Above max
        profit_factor=10.0, # Way above max
        max_drawdown_pct=-1.0,  # Negative (1.0 - (-1.0) = 2.0)
        alpha_per_trade=2.0,    # Above max
        capital_rotation_efficiency=2.0,  # Above max
        total_trades=100
    )
    fitness_high = calculate_fitness(metrics_high)
    assert fitness_high == 1.0  # Should be clamped
    
    # Test lower bound clamping
    metrics_low = FitnessMetrics(
        sharpe_ratio=-10.0,  # Way below min
        win_rate=-1.0,      # Below min
        profit_factor=-1.0, # Below min
        max_drawdown_pct=2.0,   # Above max (1.0 - 2.0 = -1.0)
        alpha_per_trade=-2.0,  # Below min
        capital_rotation_efficiency=-1.0,  # Below min
        total_trades=100
    )
    fitness_low = calculate_fitness(metrics_low)
    assert fitness_low == 0.0  # Should be clamped