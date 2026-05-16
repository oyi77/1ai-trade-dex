# ADR-010: Evolution Backend

**Status:** Accepted
**Date:** 2026-05-17

## Context

PolyEdge's genome evolution system (`genome_compiler.py`, `evolution_jobs.py`) uses a custom implementation with basic random mutation and single-point crossover. This system lacks:

- **Selection pressure** — parents are selected randomly, not by fitness
- **Multi-objective optimization** — trading requires optimizing Sharpe ratio AND minimizing drawdown simultaneously, but the current system collapses these into a single fitness score
- **Tournament selection** — no mechanism to prefer fitter individuals while maintaining diversity
- **Parallelism** — evolution runs sequentially, limiting population size

The gap analysis identified DEAP (Distributed Evolutionary Algorithms in Python) as the recommended replacement, offering NSGA-II multi-objective optimization, tournament selection, and built-in parallelism with 10+ years of academic maturity.

## Decision

Introduce an `EvolutionBackend` abstract base class with DEAP as the primary implementation and the existing genome system preserved as a legacy fallback.

### EvolutionBackend ABC

`backend/core/evolution_backend.py` defines:

```
EvolutionBackend       — abstract base class
    initialize(genome_schema, population_size) — seed initial population
    evaluate(population, fitness_fn)           — assign fitness scores
    select(population, method, n)              — select parents
    crossover(parent1, parent2)                — produce offspring
    mutate(individual, rate)                   — apply mutations
    evolve(generations)                        — run full evolution cycle
    get_pareto_front()                         — return non-dominated solutions
    export_genome(individual)                  — convert to StrategyGenome
```

### DEAP Backend

`backend/core/evolution_backends/deap_backend.py` implements `EvolutionBackend`:

- Maps existing `StrategyGenome` chromosomes to DEAP `Individual` objects using `creator.create("FitnessMulti", base.Fitness, weights=(1.0, -1.0))` for maximizing Sharpe and minimizing drawdown
- Uses `NSGAIIS` selection for multi-objective optimization
- Configurable crossover (uniform, two-point) and mutation (Gaussian, shuffle) operators
- Parallel evaluation via `multiprocessing.Pool`
- Pareto front extraction for trade-off analysis

### Legacy Backend

`backend/core/evolution_backends/legacy_backend.py` wraps the existing `genome_compiler.py` logic behind the `EvolutionBackend` interface. This ensures zero regression: switching back requires changing one config value.

### Integration

`evolution_jobs.py` is modified to accept the backend via configuration:

```
EVOLUTION_BACKEND=deap     → uses DeapBackend
EVOLUTION_BACKEND=legacy   → uses LegacyBackend (default)
```

The existing `StrategyGenome` dataclass and `genome_registry.py` persistence layer are unchanged — the backend only affects how genomes are produced, not how they are stored or executed.

### Genome Mapping

The mapping between `StrategyGenome` and DEAP individuals follows this schema:

| StrategyGenome Field | DEAP Individual Gene | Type |
|---|---|---|
| `signal_sources` | `genes[0:n]` | List of enabled source indices |
| `filter_params` | `genes[n:n+m]` | Dict of filter threshold floats |
| `position_sizer_params` | `genes[n+m:n+m+p]` | Dict of sizer config floats |
| `risk_rules` | `genes[n+m+p:]` | List of risk rule toggles |

The `genome_compiler.py` serialization format is preserved — DEAP individuals can be exported back to `StrategyGenome` at any time via `export_genome()`.

### Fitness Functions

Multi-objective fitness is defined as:

```
FitnessMulti:
    weights = (1.0, -1.0)
    objectives[0] = Sharpe ratio (maximize)
    objectives[1] = Maximum drawdown (minimize)
```

Additional objectives can be added later (e.g., win rate, profit factor) by extending the weight vector. NSGA-II handles arbitrary numbers of objectives.

### Configuration

```
EVOLUTION_BACKEND=deap|legacy      — select backend (default: legacy)
DEAP_POPULATION_SIZE=100           — individuals per generation
DEAP_CROSSOVER_PROB=0.7            — crossover probability
DEAP_MUTATION_PROB=0.2             — mutation probability
DEAP_TOURNAMENT_SIZE=3             — tournament selection size
DEAP_GENERATIONS=50                — generations per evolution cycle
DEAP_PARALLEL_WORKERS=4            — multiprocessing pool size
```

## Alternatives Considered

1. **PyGAD.** Rejected because it lacks NSGA-II multi-objective optimization. Trading requires simultaneous optimization of conflicting objectives (return vs. risk), which PyGAD cannot express.

2. **Optuna for hyperparameter optimization.** Considered as complementary (not competing). Optuna optimizes fixed-parameter spaces; DEAP optimizes variable-length genomes with crossover. Both can coexist — Optuna for hyperparameter tuning within a genome, DEAP for genome evolution.

3. **Extending the existing genome system.** Rejected because adding tournament selection, multi-objective fitness, and parallelism to a custom implementation would essentially rebuild DEAP without the testing and community support.

## Consequences

**Positive**
- NSGA-II enables proper multi-objective optimization (Sharpe vs. drawdown Pareto front)
- Tournament selection provides selection pressure while maintaining population diversity
- Built-in parallelism allows larger populations without proportional time increase
- The `EvolutionBackend` ABC allows swapping algorithms without touching downstream code
- Legacy backend ensures zero-risk rollback

**Negative**
- DEAP adds a dependency (MIT license, stable, but still external)
- Multi-objective fitness requires defining weight vectors — domain expertise needed to balance Sharpe vs. drawdown importance
- Parallel evaluation requires pickling genomes, adding serialization overhead
- NSGA-II produces a Pareto front, not a single "best" genome — downstream code must select from the front

## Rollback Plan

Set `EVOLUTION_BACKEND=legacy` to revert to the custom genome system. The `DeapBackend` implementation can be deleted without affecting any other module, as the interface boundary isolates the change to `evolution_jobs.py` only.
