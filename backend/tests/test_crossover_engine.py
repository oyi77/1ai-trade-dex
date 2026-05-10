import pytest
from unittest.mock import patch
from backend.domain.evolution.crossover_engine import crossover_genomes
from backend.domain.genome.models import (
    StrategyGenome, PerceptionChromosome, CognitionChromosome,
    EntryLogic, EntryCondition, ExitLogic, MarketSelector,
    ExecutionChromosome, RiskChromosome, MetaChromosome, FitnessMetrics
)


def create_test_genome(name: str, archetype: str, sharpe_ratio: float = 1.5) -> StrategyGenome:
    """Helper to create a test genome with fitness metrics."""
    perception = PerceptionChromosome()
    cognition = CognitionChromosome(
        entry_logic=EntryLogic(
            trigger_type='threshold_cross',
            conditions=[EntryCondition(indicator='rsi', operator='>', value=70.0)]
        ),
        exit_logic=ExitLogic(trigger_type='profit_target', profit_target_pct=0.1),
        market_selector=MarketSelector()
    )
    execution = ExecutionChromosome()
    risk = RiskChromosome()
    meta = MetaChromosome()

    fitness = FitnessMetrics(
        sharpe_ratio=sharpe_ratio,
        win_rate=0.6,
        profit_factor=1.8,
        max_drawdown_pct=0.15,
        alpha_per_trade=0.05,
        capital_rotation_efficiency=0.7,
        total_trades=100
    )

    return StrategyGenome(
        strategy_name=name,
        archetype=archetype,
        chromosomes={
            'perception': perception,
            'cognition': cognition,
            'execution': execution,
            'risk': risk,
            'meta': meta
        },
        fitness_metrics=fitness
    )


def test_crossover_elite_requirement():
    """Test that crossover requires ELITE parents (sharpe > 0.5)."""
    parent_a = create_test_genome("Parent A", "test", sharpe_ratio=0.6)
    parent_b = create_test_genome("Parent B", "test", sharpe_ratio=0.4)  # Not ELITE

    with pytest.raises(ValueError, match="Parent B not ELITE"):
        crossover_genomes(parent_a, parent_b, "neutral")


def test_crossover_basic():
    """Test basic crossover functionality."""
    parent_a = create_test_genome("Parent A", "test", sharpe_ratio=0.8)
    parent_b = create_test_genome("Parent B", "test", sharpe_ratio=0.9)

    child = crossover_genomes(parent_a, parent_b, "neutral")

    # Verify child properties
    assert child.stage == "DRAFT"
    assert child.archetype == "crossover"
    assert child.lineage.creator == "crossover"
    assert parent_a.genome_id in child.lineage.parent_genome_ids
    assert parent_b.genome_id in child.lineage.parent_genome_ids
    assert child.lineage.generation == max(parent_a.lineage.generation, parent_b.lineage.generation) + 1
    assert "cross_" in child.strategy_name


def test_crossover_volatile_regime():
    """Test crossover in volatile regime (prefers lower drawdown parent for risk)."""
    parent_a = create_test_genome("Parent A", "test", sharpe_ratio=0.8)
    parent_a.fitness_metrics.max_drawdown_pct = 0.10  # Lower drawdown

    parent_b = create_test_genome("Parent B", "test", sharpe_ratio=0.8)
    parent_b.fitness_metrics.max_drawdown_pct = 0.20  # Higher drawdown

    # Mock mutation to avoid non-deterministic field changes overriding crossover selection
    with patch("backend.domain.evolution.crossover_engine.mutate_genome", side_effect=lambda g, *a, **kw: (g, [])):
        child = crossover_genomes(parent_a, parent_b, "volatile")

    # In volatile regime, parent with lower drawdown should contribute risk chromosome
    assert child.chromosomes["risk"].position_sizing_model == parent_a.chromosomes["risk"].position_sizing_model


def test_crossover_trending_regime():
    """Test crossover in trending regime (prefers higher alpha parent for cognition)."""
    parent_a = create_test_genome("Parent A", "test", sharpe_ratio=0.8)
    parent_a.fitness_metrics.alpha_per_trade = 0.10  # Higher alpha

    parent_b = create_test_genome("Parent B", "test", sharpe_ratio=0.8)
    parent_b.fitness_metrics.alpha_per_trade = 0.05  # Lower alpha

    child = crossover_genomes(parent_a, parent_b, "trending")

    # In trending regime, parent with higher alpha should contribute cognition chromosome
    assert child.chromosomes["cognition"].entry_logic.trigger_type == parent_a.chromosomes["cognition"].entry_logic.trigger_type


def test_crossover_mean_reverting_regime():
    """Test crossover in mean-reverting regime (prefers higher win rate for execution)."""
    parent_a = create_test_genome("Parent A", "test", sharpe_ratio=0.8)
    parent_a.fitness_metrics.win_rate = 0.7  # Higher win rate

    parent_b = create_test_genome("Parent B", "test", sharpe_ratio=0.8)
    parent_b.fitness_metrics.win_rate = 0.5  # Lower win rate

    child = crossover_genomes(parent_a, parent_b, "mean_reverting")

    # In mean-reverting regime, parent with higher win rate should contribute execution chromosome
    assert child.chromosomes["execution"].order_type == parent_a.chromosomes["execution"].order_type


def test_crossover_mutation_applied():
    """Test that crossover applies light mutation to child."""
    parent_a = create_test_genome("Parent A", "test", sharpe_ratio=0.8)
    parent_b = create_test_genome("Parent B", "test", sharpe_ratio=0.8)

    child = crossover_genomes(parent_a, parent_b, "neutral")

    # Child should have DRAFT stage (result of mutation)
    assert child.stage == "DRAFT"
    # Child should have different genome ID from both parents
    assert child.genome_id != parent_a.genome_id
    assert child.genome_id != parent_b.genome_id
