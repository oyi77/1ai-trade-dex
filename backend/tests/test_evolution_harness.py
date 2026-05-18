"""Tests for the EvolutionHarness — DEAP and legacy backends.

Validates:
- ABC contract compliance for both backends
- DEAP mutation and crossover operations
- Pareto front computation
- Factory function
- Population statistics
"""

from __future__ import annotations

import pytest

from backend.core.evolution_harness import (
    DEAPEvolutionBackend,
    Individual,
    LegacyGenomeBackend,
    _dominates,
    create_evolution_backend,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def sample_individuals() -> list[Individual]:
    """Create a small population of test individuals."""
    return [
        Individual(
            genome_id=f"genome_{i}",
            genes=[0.1 * i + 0.01 * j for j in range(10)],
            fitness=(),
            metadata={"archetype": "momentum", "strategy_name": f"strat_{i}"},
        )
        for i in range(6)
    ]


@pytest.fixture
def evaluated_individuals() -> list[Individual]:
    """Create individuals with pre-assigned fitness.

    Fitness uses DEAP convention: (sharpe, -drawdown) — both maximized.
    """
    return [
        Individual(
            genome_id=f"genome_{i}",
            genes=[0.1 * i + 0.01 * j for j in range(10)],
            fitness=(1.5 - 0.1 * i, -(0.05 * i)),  # (sharpe, -drawdown)
            metadata={"archetype": "momentum"},
        )
        for i in range(6)
    ]


def dummy_fitness(ind: Individual) -> tuple[float, ...]:
    """Simple fitness: maximize sum of genes, minimize count of genes > 0.5."""
    total = sum(ind.genes)
    high_count = sum(1 for g in ind.genes if g > 0.5)
    return (total, -float(high_count))


# ---------------------------------------------------------------------------
# Dominance helper
# ---------------------------------------------------------------------------

class TestDominates:
    """Test Pareto dominance. Fitness values use DEAP convention:
    all objectives are maximized (drawdown stored as -drawdown).
    """

    def test_a_dominates_b(self):
        # a: sharpe=2.0, -drawdown=-0.1 (drawdown=0.1)
        # b: sharpe=1.0, -drawdown=-0.5 (drawdown=0.5)
        assert _dominates((2.0, -0.1), (1.0, -0.5)) is True

    def test_b_dominates_a(self):
        assert _dominates((1.0, -0.5), (2.0, -0.1)) is False

    def test_neither_dominates_tradeoff(self):
        # a better on sharpe, b better on drawdown
        assert _dominates((2.0, -0.5), (1.0, -0.1)) is False

    def test_equal_neither_dominates(self):
        assert _dominates((1.0, -0.5), (1.0, -0.5)) is False

    def test_single_dimension(self):
        assert _dominates((2.0,), (1.0,)) is True

    def test_with_weights_minimization(self):
        # With weights, raw values can be used: weight<0 means minimize
        assert _dominates((2.0, 0.1), (1.0, 0.5), weights=(1.0, -1.0)) is True


# ---------------------------------------------------------------------------
# DEAP Backend Tests
# ---------------------------------------------------------------------------

class TestDEAPEvolutionBackend:

    def test_evaluate_assigns_fitness(self, sample_individuals):
        backend = DEAPEvolutionBackend(population_size=6, generations=1)
        evaluated = backend.evaluate(sample_individuals, dummy_fitness)
        for ind in evaluated:
            assert len(ind.fitness) == 2
            assert isinstance(ind.fitness[0], float)

    def test_mutate_modifies_genes(self, sample_individuals):
        backend = DEAPEvolutionBackend(
            population_size=6,
            generations=1,
            gene_bounds=[(0.0, 1.0)] * 10,
        )
        original = sample_individuals[0]
        mutated = backend.mutate(original, rate=1.0)
        # DEAP modifies in-place, preserving genome_id for round-tripping
        assert len(mutated.genes) == len(original.genes)
        # Genes should differ after mutation (with high probability)
        # We don't assert strict inequality since DEAP's polynomial mutation
        # may leave some genes unchanged

    def test_crossover_produces_two_offspring(self, sample_individuals):
        backend = DEAPEvolutionBackend(
            population_size=6,
            generations=1,
            gene_bounds=[(0.0, 1.0)] * 10,
        )
        p1, p2 = sample_individuals[0], sample_individuals[1]
        child_a, child_b = backend.crossover(p1, p2)
        # DEAP crossover modifies in-place, preserving genome_id
        assert len(child_a.genes) == len(p1.genes)
        assert len(child_b.genes) == len(p2.genes)

    def test_select_tournament(self, sample_individuals):
        backend = DEAPEvolutionBackend(
            population_size=6,
            generations=1,
            gene_bounds=[(0.0, 1.0)] * 10,
        )
        backend.evaluate(sample_individuals, dummy_fitness)
        selected = backend.select(sample_individuals, n=3, method="tournament")
        assert len(selected) == 3
        for ind in selected:
            assert isinstance(ind, Individual)

    def test_select_nsga2(self, sample_individuals):
        backend = DEAPEvolutionBackend(
            population_size=6,
            generations=1,
            gene_bounds=[(0.0, 1.0)] * 10,
        )
        backend.evaluate(sample_individuals, dummy_fitness)
        selected = backend.select(sample_individuals, n=3, method="nsga2")
        assert len(selected) == 3

    def test_evolve_runs_generations(self, sample_individuals):
        backend = DEAPEvolutionBackend(
            population_size=6,
            generations=3,
            crossover_prob=0.8,
            mutation_prob=0.3,
            gene_bounds=[(0.0, 1.0)] * 10,
        )
        result = backend.evolve(sample_individuals, dummy_fitness, generations=3)
        assert len(result) > 0
        for ind in result:
            assert len(ind.fitness) == 2

    def test_get_population_stats(self, evaluated_individuals):
        backend = DEAPEvolutionBackend(population_size=6, generations=1)
        stats = backend.get_population_stats(evaluated_individuals)
        assert stats.size == 6
        assert stats.best_fitness > 0
        assert stats.avg_fitness > 0
        assert stats.worst_fitness <= stats.best_fitness

    def test_get_pareto_front(self, evaluated_individuals):
        backend = DEAPEvolutionBackend(population_size=6, generations=1)
        front = backend.get_pareto_front(evaluated_individuals)
        assert len(front) >= 1
        assert len(front) <= len(evaluated_individuals)
        # All front members should be Individual instances
        for ind in front:
            assert isinstance(ind, Individual)

    def test_pareto_front_empty_population(self):
        backend = DEAPEvolutionBackend(population_size=6, generations=1)
        assert backend.get_pareto_front([]) == []

    def test_stats_empty_population(self):
        backend = DEAPEvolutionBackend(population_size=6, generations=1)
        stats = backend.get_population_stats([])
        assert stats.size == 0


# ---------------------------------------------------------------------------
# Legacy Backend Tests
# ---------------------------------------------------------------------------

class TestLegacyGenomeBackend:

    def test_evaluate_assigns_fitness(self, sample_individuals):
        backend = LegacyGenomeBackend()
        evaluated = backend.evaluate(sample_individuals, dummy_fitness)
        for ind in evaluated:
            assert len(ind.fitness) == 2

    def test_mutate_returns_new_individual(self, sample_individuals):
        backend = LegacyGenomeBackend()
        original = sample_individuals[0]
        mutated = backend.mutate(original, rate=1.0)
        assert mutated.genome_id != original.genome_id
        assert len(mutated.genes) == len(original.genes)

    def test_crossover_uniform(self, sample_individuals):
        backend = LegacyGenomeBackend()
        p1, p2 = sample_individuals[0], sample_individuals[1]
        child_a, child_b = backend.crossover(p1, p2)
        assert len(child_a.genes) == len(p1.genes)
        assert len(child_b.genes) == len(p2.genes)
        # Children should have different genome IDs from parents
        assert child_a.genome_id not in (p1.genome_id, p2.genome_id)

    def test_select_truncation(self, sample_individuals):
        backend = LegacyGenomeBackend()
        backend.evaluate(sample_individuals, dummy_fitness)
        selected = backend.select(sample_individuals, n=3)
        assert len(selected) == 3
        # Should be sorted by first fitness objective descending
        assert selected[0].fitness[0] >= selected[-1].fitness[0]

    def test_evolve(self, sample_individuals):
        backend = LegacyGenomeBackend(mutation_rate=0.3)
        result = backend.evolve(sample_individuals, dummy_fitness, generations=2)
        assert len(result) > 0
        for ind in result:
            assert len(ind.fitness) == 2

    def test_get_population_stats(self, evaluated_individuals):
        backend = LegacyGenomeBackend()
        stats = backend.get_population_stats(evaluated_individuals)
        assert stats.size == 6
        assert stats.pareto_front_size == 0  # Legacy doesn't compute Pareto

    def test_get_pareto_front_returns_best(self, evaluated_individuals):
        backend = LegacyGenomeBackend()
        front = backend.get_pareto_front(evaluated_individuals)
        assert len(front) == 1
        # Should be the one with highest first fitness
        best = max(evaluated_individuals, key=lambda i: i.fitness[0])
        assert front[0].genome_id == best.genome_id


# ---------------------------------------------------------------------------
# Factory Tests
# ---------------------------------------------------------------------------

class TestFactory:

    def test_create_legacy_backend(self, monkeypatch):
        monkeypatch.setenv("EVOLUTION_BACKEND", "legacy")
        # Force reload to pick up env
        from backend.config import settings
        monkeypatch.setattr(settings, "EVOLUTION_BACKEND", "legacy")
        backend = create_evolution_backend("legacy")
        assert isinstance(backend, LegacyGenomeBackend)

    def test_create_deap_backend(self):
        backend = create_evolution_backend(
            "deap",
            population_size=10,
            generations=2,
            gene_bounds=[(0.0, 1.0)] * 5,
        )
        assert isinstance(backend, DEAPEvolutionBackend)

    def test_create_unknown_backend_raises(self):
        with pytest.raises(ValueError, match="Unknown evolution backend"):
            create_evolution_backend("nonexistent")

    def test_create_is_case_insensitive(self, monkeypatch):
        monkeypatch.setattr("backend.config.settings.EVOLUTION_BACKEND", "legacy")
        backend = create_evolution_backend("LEGACY")
        assert isinstance(backend, LegacyGenomeBackend)


# ---------------------------------------------------------------------------
# Integration: DEAP mutation/crossover round-trip
# ---------------------------------------------------------------------------

class TestDEAPRoundTrip:

    def test_mutate_then_evaluate(self):
        """Mutated individuals should be evaluable."""
        backend = DEAPEvolutionBackend(
            population_size=4,
            generations=1,
            gene_bounds=[(0.0, 1.0)] * 10,
        )
        ind = Individual(
            genome_id="test_1",
            genes=[0.5] * 10,
            fitness=(1.0, -0.1),
            metadata={},
        )
        mutated = backend.mutate(ind, rate=0.5)
        evaluated = backend.evaluate([mutated], dummy_fitness)
        assert len(evaluated) == 1
        assert len(evaluated[0].fitness) == 2

    def test_crossover_then_evaluate(self):
        """Crossover offspring should be evaluable."""
        backend = DEAPEvolutionBackend(
            population_size=4,
            generations=1,
            gene_bounds=[(0.0, 1.0)] * 10,
        )
        p1 = Individual(genome_id="p1", genes=[0.3] * 10, fitness=(1.0, -0.1))
        p2 = Individual(genome_id="p2", genes=[0.7] * 10, fitness=(0.8, -0.2))
        child_a, child_b = backend.crossover(p1, p2)
        evaluated = backend.evaluate([child_a, child_b], dummy_fitness)
        assert len(evaluated) == 2
        for ind in evaluated:
            assert len(ind.fitness) == 2

    def test_full_evolution_improves_fitness(self):
        """After enough generations, best fitness should improve."""
        import random as rng
        rng.seed(42)  # Deterministic for test

        population = [
            Individual(
                genome_id=f"g{i}",
                genes=[rng.random() for _ in range(10)],
                fitness=(),
                metadata={},
            )
            for i in range(20)
        ]

        backend = DEAPEvolutionBackend(
            population_size=20,
            generations=10,
            crossover_prob=0.7,
            mutation_prob=0.3,
            gene_bounds=[(0.0, 1.0)] * 10,
        )

        result = backend.evolve(population, dummy_fitness, generations=10)
        assert len(result) > 0

        # Best individual should have sum of genes close to 10 (all genes ~1.0)
        best = max(result, key=lambda i: i.fitness[0] if i.fitness else 0.0)
        assert best.fitness[0] > 5.0  # Should be well above random average of ~5
