"""Pluggable evolution engine with DEAP and legacy backends.

ADR-010: Introduces an EvolutionBackend ABC with DEAP as the primary
implementation for NSGA-II multi-objective optimization, and the existing
genome system preserved as a legacy fallback.

Usage:
    backend = create_evolution_backend()  # reads EVOLUTION_BACKEND from config
    offspring = backend.evolve(population, fitness_fn)
"""

from __future__ import annotations

import random
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Callable
from uuid import uuid4

from loguru import logger

from backend.monitoring.agi_metrics import (
    record_evolution_stats,
    record_evolution_cycle,
)


# ---------------------------------------------------------------------------
# Data transfer objects
# ---------------------------------------------------------------------------

@dataclass
class PopulationStats:
    """Aggregate statistics for a population."""
    size: int = 0
    best_fitness: float = 0.0
    avg_fitness: float = 0.0
    worst_fitness: float = 0.0
    pareto_front_size: int = 0
    generation: int = 0


@dataclass
class Individual:
    """Wrapper around a genome for evolution operations.

    Attributes:
        genome_id: Unique identifier (matches StrategyGenome.genome_id).
        genes: Flat list of float genes mapped from chromosome parameters.
        fitness: Tuple of objective values (e.g., (sharpe, -drawdown)).
        metadata: Arbitrary metadata (archetype, strategy_name, etc.).
    """
    genome_id: str = field(default_factory=lambda: str(uuid4()))
    genes: list[float] = field(default_factory=list)
    fitness: tuple[float, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Abstract base class
# ---------------------------------------------------------------------------

class EvolutionBackend(ABC):
    """Abstract evolution backend interface.

    Implementations must support the full genetic algorithm lifecycle:
    initialization, evaluation, selection, crossover, mutation, and
    multi-generation evolution.
    """

    @abstractmethod
    def evolve(
        self,
        population: list[Individual],
        fitness_fn: Callable[[Individual], tuple[float, ...]],
        generations: int | None = None,
    ) -> list[Individual]:
        """Run a full evolution cycle and return the final population.

        Args:
            population: Initial population of individuals.
            fitness_fn: Function mapping Individual -> tuple of objective values.
            generations: Number of generations (backend default if None).

        Returns:
            Final population after evolution.
        """

    @abstractmethod
    def evaluate(
        self,
        population: list[Individual],
        fitness_fn: Callable[[Individual], tuple[float, ...]],
    ) -> list[Individual]:
        """Assign fitness values to each individual in-place and return them."""

    @abstractmethod
    def select(
        self,
        population: list[Individual],
        n: int,
        method: str = "tournament",
    ) -> list[Individual]:
        """Select *n* individuals from the population using the given method."""

    @abstractmethod
    def mutate(
        self,
        individual: Individual,
        rate: float = 0.2,
    ) -> Individual:
        """Apply mutation to an individual and return the mutated copy."""

    @abstractmethod
    def crossover(
        self,
        parent_a: Individual,
        parent_b: Individual,
    ) -> tuple[Individual, Individual]:
        """Produce two offspring from two parents via crossover."""

    @abstractmethod
    def get_population_stats(
        self,
        population: list[Individual],
    ) -> PopulationStats:
        """Compute aggregate statistics for the population."""

    @abstractmethod
    def get_pareto_front(
        self,
        population: list[Individual],
    ) -> list[Individual]:
        """Return the non-dominated (Pareto-optimal) individuals."""

    def export_genes_to_genome_dict(
        self,
        individual: Individual,
        gene_schema: dict[str, Any],
    ) -> dict[str, Any]:
        """Convert an Individual's flat gene list back to a chromosome dict.

        Args:
            individual: The individual whose genes to export.
            gene_schema: Mapping describing how genes map to chromosomes.

        Returns:
            Dict suitable for constructing a StrategyGenome.
        """
        raise NotImplementedError(
            f"{type(self).__name__} does not implement export_genes_to_genome_dict"
        )


# ---------------------------------------------------------------------------
# DEAP backend
# ---------------------------------------------------------------------------

class DEAPEvolutionBackend(EvolutionBackend):
    """DEAP-based evolution backend using NSGA-II multi-objective optimization.

    Maps StrategyGenome chromosomes to DEAP Individuals using a flat gene
    vector. Fitness is multi-objective: (Sharpe ratio, -max_drawdown).
    """

    def __init__(
        self,
        population_size: int = 100,
        crossover_prob: float = 0.7,
        mutation_prob: float = 0.2,
        tournament_size: int = 3,
        generations: int = 50,
        gene_bounds: list[tuple[float, float]] | None = None,
    ):
        self.population_size = population_size
        self.crossover_prob = crossover_prob
        self.mutation_prob = mutation_prob
        self.tournament_size = tournament_size
        self.generations = generations
        self.gene_bounds = gene_bounds or []

        # Lazy-initialize DEAP components to avoid import cost when unused
        self._toolbox: Any = None
        self._creator: Any = None
        self._base: Any = None

    def _ensure_deap(self) -> None:
        """Import and configure DEAP on first use."""
        if self._toolbox is not None:
            return

        try:
            from deap import base, creator, tools  # noqa: F401
        except ImportError:
            raise ImportError(
                "DEAP is required for the DEAP evolution backend. "
                "Install it with: pip install deap>=1.4.0"
            )

        self._base = base
        self._creator = creator
        self._tools = tools

        # Create fitness class: maximize Sharpe (weight=1.0), minimize drawdown (weight=-1.0)
        if not hasattr(creator, "FitnessMulti"):
            creator.create("FitnessMulti", base.Fitness, weights=(1.0, -1.0))
        if not hasattr(creator, "Individual"):
            creator.create("Individual", list, fitness=creator.FitnessMulti)

        toolbox = base.Toolbox()

        # Gene initialization: uniform random within bounds
        def _init_gene():
            if self.gene_bounds:
                return [random.uniform(lo, hi) for lo, hi in self.gene_bounds]
            return [random.random() for _ in range(20)]  # default 20 genes

        toolbox.register("individual", tools.initIterate, creator.Individual, _init_gene)
        toolbox.register("population", tools.initRepeat, list, toolbox.individual)

        # Genetic operators
        toolbox.register("mate", tools.cxSimulatedBinaryBounded,
                         low=[b[0] for b in self.gene_bounds] if self.gene_bounds else [0.0] * 20,
                         up=[b[1] for b in self.gene_bounds] if self.gene_bounds else [1.0] * 20,
                         eta=20.0)
        toolbox.register("mutate", tools.mutPolynomialBounded,
                         low=[b[0] for b in self.gene_bounds] if self.gene_bounds else [0.0] * 20,
                         up=[b[1] for b in self.gene_bounds] if self.gene_bounds else [1.0] * 20,
                         eta=20.0, indpb=1.0 / max(1, len(self.gene_bounds) or 20))
        toolbox.register("select", tools.selNSGA2)
        toolbox.register("select_tournament", tools.selTournament, tournsize=self.tournament_size)

        self._toolbox = toolbox

    def _individual_to_deap(self, ind: Individual) -> Any:
        """Convert our Individual to a DEAP individual."""
        self._ensure_deap()
        deap_ind = self._toolbox.individual()
        for i, gene in enumerate(ind.genes):
            if i < len(deap_ind):
                deap_ind[i] = gene
        deap_ind.fitness.values = ind.fitness if ind.fitness else (0.0, 0.0)
        # Attach metadata for round-tripping
        deap_ind._genome_id = ind.genome_id
        deap_ind._metadata = ind.metadata
        return deap_ind

    def _deap_to_individual(self, deap_ind: Any) -> Individual:
        """Convert a DEAP individual back to our Individual."""
        return Individual(
            genome_id=getattr(deap_ind, '_genome_id', str(uuid4())),
            genes=list(deap_ind),
            fitness=tuple(deap_ind.fitness.values) if deap_ind.fitness.valid else (),
            metadata=getattr(deap_ind, '_metadata', {}),
        )

    def evolve(
        self,
        population: list[Individual],
        fitness_fn: Callable[[Individual], tuple[float, ...]],
        generations: int | None = None,
    ) -> list[Individual]:
        """Run NSGA-II evolution for the specified number of generations."""
        t0 = time.monotonic()
        self._ensure_deap()
        n_gen = generations or self.generations

        # Convert to DEAP individuals
        deap_pop = [self._individual_to_deap(ind) for ind in population]

        # Evaluate initial population
        fitnesses = [fitness_fn(self._deap_to_individual(d)) for d in deap_pop]
        for ind, fit in zip(deap_pop, fitnesses):
            ind.fitness.values = fit

        for gen in range(n_gen):
            # Select offspring via tournament
            offspring = self._toolbox.select_tournament(deap_pop, len(deap_pop))
            offspring = [self._toolbox.clone(ind) for ind in offspring]

            # Crossover
            for i in range(0, len(offspring) - 1, 2):
                if random.random() < self.crossover_prob:
                    self._toolbox.mate(offspring[i], offspring[i + 1])
                    del offspring[i].fitness.values
                    del offspring[i + 1].fitness.values

            # Mutation
            for ind in offspring:
                if random.random() < self.mutation_prob:
                    self._toolbox.mutate(ind)
                    del ind.fitness.values

            # Evaluate individuals with invalid fitness
            invalid = [ind for ind in offspring if not ind.fitness.valid]
            fitnesses = [fitness_fn(self._deap_to_individual(d)) for d in invalid]
            for ind, fit in zip(invalid, fitnesses):
                ind.fitness.values = fit

            # NSGA-II selection for next generation
            deap_pop = self._toolbox.select(deap_pop + offspring, self.population_size)

            if (gen + 1) % 10 == 0:
                logger.debug(f"DEAP generation {gen + 1}/{n_gen} completed")

        result = [self._deap_to_individual(d) for d in deap_pop]

        # Record evolution metrics
        stats = self.get_population_stats(result)
        pareto = self.get_pareto_front(result)
        record_evolution_stats(
            population_size=stats.size,
            best_fitness=stats.best_fitness,
            avg_fitness=stats.avg_fitness,
            generation=n_gen,
            pareto_front_size=len(pareto),
        )
        record_evolution_cycle(time.monotonic() - t0)

        return result

    def evaluate(
        self,
        population: list[Individual],
        fitness_fn: Callable[[Individual], tuple[float, ...]],
    ) -> list[Individual]:
        """Evaluate fitness for all individuals."""
        for ind in population:
            ind.fitness = fitness_fn(ind)
        return population

    def select(
        self,
        population: list[Individual],
        n: int,
        method: str = "tournament",
    ) -> list[Individual]:
        """Select n individuals using the specified method."""
        self._ensure_deap()
        deap_pop = [self._individual_to_deap(ind) for ind in population]

        if method == "nsga2":
            selected = self._toolbox.select(deap_pop, min(n, len(deap_pop)))
        elif method == "tournament":
            selected = self._toolbox.select_tournament(deap_pop, min(n, len(deap_pop)))
        else:
            # Fallback: random selection
            selected = random.sample(deap_pop, min(n, len(deap_pop)))

        return [self._deap_to_individual(d) for d in selected]

    def mutate(
        self,
        individual: Individual,
        rate: float = 0.2,
    ) -> Individual:
        """Apply polynomial bounded mutation."""
        self._ensure_deap()
        deap_ind = self._individual_to_deap(individual)
        self._toolbox.mutate(deap_ind)
        return self._deap_to_individual(deap_ind)

    def crossover(
        self,
        parent_a: Individual,
        parent_b: Individual,
    ) -> tuple[Individual, Individual]:
        """Apply simulated binary crossover."""
        self._ensure_deap()
        da = self._individual_to_deap(parent_a)
        db = self._individual_to_deap(parent_b)
        self._toolbox.mate(da, db)
        return self._deap_to_individual(da), self._deap_to_individual(db)

    def get_population_stats(
        self,
        population: list[Individual],
    ) -> PopulationStats:
        """Compute aggregate statistics."""
        if not population:
            return PopulationStats()

        fitnesses = [ind.fitness[0] if ind.fitness else 0.0 for ind in population]
        pareto = self.get_pareto_front(population)

        return PopulationStats(
            size=len(population),
            best_fitness=max(fitnesses),
            avg_fitness=sum(fitnesses) / len(fitnesses),
            worst_fitness=min(fitnesses),
            pareto_front_size=len(pareto),
        )

    def get_pareto_front(
        self,
        population: list[Individual],
    ) -> list[Individual]:
        """Return non-dominated individuals (Pareto front)."""
        if not population:
            return []

        # Filter individuals with valid fitness
        valid = [ind for ind in population if ind.fitness and len(ind.fitness) >= 2]
        if not valid:
            return []

        front: list[Individual] = []
        for candidate in valid:
            dominated = False
            for other in valid:
                if _dominates(other.fitness, candidate.fitness):
                    dominated = True
                    break
            if not dominated:
                front.append(candidate)

        return front


def _dominates(
    a: tuple[float, ...],
    b: tuple[float, ...],
    weights: tuple[float, ...] | None = None,
) -> bool:
    """Return True if individual *a* dominates individual *b*.

    For weighted objectives: positive weight means maximize, negative means
    minimize. The fitness values are expected to already incorporate weights
    (e.g., drawdown stored as -drawdown for minimization).

    When weights are provided, raw fitness values are adjusted:
      effective = value * sign(weight)
    so that all objectives are maximized for dominance comparison.

    Without weights: standard Pareto dominance assuming all objectives
    are to be maximized.
    """
    if len(a) != len(b):
        return False
    better_in_any = False
    for i, (ai, bi) in enumerate(zip(a, b)):
        # If weights provided, adjust for direction
        if weights and i < len(weights):
            w = weights[i]
            # Negate if minimization (negative weight)
            if w < 0:
                ai, bi = -ai, -bi
        if ai < bi:
            return False
        if ai > bi:
            better_in_any = True
    return better_in_any


# ---------------------------------------------------------------------------
# Legacy backend (wraps existing genome system)
# ---------------------------------------------------------------------------

class LegacyGenomeBackend(EvolutionBackend):
    """Legacy evolution backend wrapping the existing mutation/crossover engines.

    Uses the same logic as evolution_jobs.py: random parent selection,
    single-objective fitness, custom mutation engine.
    """

    def __init__(self, mutation_rate: float = 0.10):
        self.mutation_rate = mutation_rate

    def evolve(
        self,
        population: list[Individual],
        fitness_fn: Callable[[Individual], tuple[float, ...]],
        generations: int | None = None,
    ) -> list[Individual]:
        """Run legacy-style evolution for the specified generations."""
        t0 = time.monotonic()
        n_gen = generations or 1

        # Evaluate initial population
        self.evaluate(population, fitness_fn)

        for gen in range(n_gen):
            # Sort by first fitness objective (descending)
            sorted_pop = sorted(
                population,
                key=lambda ind: ind.fitness[0] if ind.fitness else 0.0,
                reverse=True,
            )

            # Select elite half
            elite_count = max(1, len(sorted_pop) // 2)
            elites = sorted_pop[:elite_count]

            # Generate offspring via crossover and mutation
            offspring: list[Individual] = []
            target = max(1, int(len(population) * self.mutation_rate))

            while len(offspring) < target:
                # Pick two random elites for crossover
                p1, p2 = random.sample(elites, 2) if len(elites) >= 2 else (elites[0], elites[0])
                child_a, child_b = self.crossover(p1, p2)
                child_a = self.mutate(child_a, self.mutation_rate)
                offspring.append(child_a)
                if len(offspring) < target:
                    child_b = self.mutate(child_b, self.mutation_rate)
                    offspring.append(child_b)

            # Evaluate offspring
            self.evaluate(offspring, fitness_fn)

            # Merge: keep elites + offspring, trim to original size
            population = sorted_pop + offspring
            population.sort(
                key=lambda ind: ind.fitness[0] if ind.fitness else 0.0,
                reverse=True,
            )
            population = population[:len(sorted_pop)]

            logger.debug(
                f"Legacy generation {gen + 1}/{n_gen}: "
                f"best={population[0].fitness[0] if population[0].fitness else 0:.4f}"
            )

        # Record evolution metrics
        stats = self.get_population_stats(population)
        record_evolution_stats(
            population_size=stats.size,
            best_fitness=stats.best_fitness,
            avg_fitness=stats.avg_fitness,
            generation=n_gen,
        )
        record_evolution_cycle(time.monotonic() - t0)

        return population

    def evaluate(
        self,
        population: list[Individual],
        fitness_fn: Callable[[Individual], tuple[float, ...]],
    ) -> list[Individual]:
        """Evaluate fitness for all individuals."""
        for ind in population:
            ind.fitness = fitness_fn(ind)
        return population

    def select(
        self,
        population: list[Individual],
        n: int,
        method: str = "tournament",
    ) -> list[Individual]:
        """Select n individuals. Legacy uses truncation selection."""
        sorted_pop = sorted(
            population,
            key=lambda ind: ind.fitness[0] if ind.fitness else 0.0,
            reverse=True,
        )
        return sorted_pop[:n]

    def mutate(
        self,
        individual: Individual,
        rate: float = 0.2,
    ) -> Individual:
        """Apply Gaussian noise mutation to genes."""
        new_genes = list(individual.genes)
        for i in range(len(new_genes)):
            if random.random() < rate:
                new_genes[i] += random.gauss(0, 0.1)
                # Clamp to [0, 1] if bounds are available
                new_genes[i] = max(0.0, min(1.0, new_genes[i]))
        return Individual(
            genome_id=str(uuid4()),
            genes=new_genes,
            fitness=(),
            metadata=dict(individual.metadata),
        )

    def crossover(
        self,
        parent_a: Individual,
        parent_b: Individual,
    ) -> tuple[Individual, Individual]:
        """Uniform crossover: each gene randomly chosen from one parent."""
        genes_a = list(parent_a.genes)
        genes_b = list(parent_b.genes)
        # Pad shorter gene list
        max_len = max(len(genes_a), len(genes_b))
        genes_a.extend([0.0] * (max_len - len(genes_a)))
        genes_b.extend([0.0] * (max_len - len(genes_b)))

        child_a_genes: list[float] = []
        child_b_genes: list[float] = []
        for ga, gb in zip(genes_a, genes_b):
            if random.random() < 0.5:
                child_a_genes.append(ga)
                child_b_genes.append(gb)
            else:
                child_a_genes.append(gb)
                child_b_genes.append(ga)

        child_a = Individual(
            genome_id=str(uuid4()),
            genes=child_a_genes,
            fitness=(),
            metadata=dict(parent_a.metadata),
        )
        child_b = Individual(
            genome_id=str(uuid4()),
            genes=child_b_genes,
            fitness=(),
            metadata=dict(parent_b.metadata),
        )
        return child_a, child_b

    def get_population_stats(
        self,
        population: list[Individual],
    ) -> PopulationStats:
        """Compute aggregate statistics."""
        if not population:
            return PopulationStats()

        fitnesses = [ind.fitness[0] if ind.fitness else 0.0 for ind in population]
        return PopulationStats(
            size=len(population),
            best_fitness=max(fitnesses),
            avg_fitness=sum(fitnesses) / len(fitnesses),
            worst_fitness=min(fitnesses),
            pareto_front_size=0,  # Legacy doesn't compute Pareto front
        )

    def get_pareto_front(
        self,
        population: list[Individual],
    ) -> list[Individual]:
        """Legacy backend returns top individual as degenerate Pareto front."""
        if not population:
            return []
        best = max(population, key=lambda ind: ind.fitness[0] if ind.fitness else 0.0)
        return [best]


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def create_evolution_backend(
    backend_name: str | None = None,
    **kwargs: Any,
) -> EvolutionBackend:
    """Create an evolution backend based on configuration.

    Args:
        backend_name: "deap" or "legacy". Reads from config if None.
        **kwargs: Additional keyword arguments passed to the backend constructor.

    Returns:
        An EvolutionBackend instance.

    Raises:
        ValueError: If backend_name is not recognized.
    """
    if backend_name is None:
        from backend.config import settings
        backend_name = getattr(settings, "EVOLUTION_BACKEND", "legacy")

    backend_name = backend_name.lower().strip()

    if backend_name == "deap":
        from backend.config import settings
        return DEAPEvolutionBackend(
            population_size=kwargs.get("population_size", settings.DEAP_POPULATION_SIZE),
            crossover_prob=kwargs.get("crossover_prob", settings.DEAP_CROSSOVER_PROB),
            mutation_prob=kwargs.get("mutation_prob", settings.DEAP_MUTATION_PROB),
            tournament_size=kwargs.get("tournament_size", settings.DEAP_TOURNAMENT_SIZE),
            generations=kwargs.get("generations", settings.DEAP_GENERATIONS),
            gene_bounds=kwargs.get("gene_bounds"),
        )
    elif backend_name == "legacy":
        from backend.config import settings
        return LegacyGenomeBackend(
            mutation_rate=kwargs.get("mutation_rate", settings.AGI_MUTATION_RATE),
        )
    else:
        raise ValueError(
            f"Unknown evolution backend: {backend_name!r}. "
            f"Valid options: 'deap', 'legacy'"
        )
