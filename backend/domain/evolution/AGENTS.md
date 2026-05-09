<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-05-09 | Updated: 2026-05-09 -->

# backend/domain/evolution

## Purpose

Genetic algorithm engine for strategy evolution and composition. Implements mutation, crossover, fitness evaluation, and population seeding operations to evolve trading strategies from a formal genome grammar.

## Key Files

| File | Description |
|------|-------------|
| `__init__.py` | Package marker - evolution engines for mutation, crossover, fitness calculation, and population seeding |
| `evolution_action.py` | `EvolutionAction` dataclass for tracking evolution events - mutation, crossover, selection, fitness_eval, promotion, auto_kill, necromancy with event publishing |
| `crossover_engine.py` | Two-point crossover for genome chromosomes with elitism - breeds ELITE strategies with regime-weighted chromosome selection |
| `mutation_engine.py` | Adaptive mutation engine with market regime awareness - hyperparameter tweaks, indicator swaps, timeframe shifts, risk model changes, and chromosome additions |
| `seed.py` | Initial population generator - creates 9 DRAFT archetypes with randomized chromosomes and diversity injection |
| `fitness.py` | Composite fitness scoring function - combines Sharpe ratio, win rate, profit factor, drawdown, alpha per trade, and capital rotation efficiency |
| `shadow_metrics.py` | Shared settled-shadow-trade metric calculator used by stage-gating and shadow performance feedback loops |

## Subdirectories

| Directory | Purpose |
|-----------|---------|
| `genome/` | Core domain models: StrategyGenome and its chromosomes |

## For AI Agents

### Working In This Directory
- All operations create new genome instances (immutability pattern)
- Fitness scores normalized to [0.0, 1.0] range for comparison
- Adaptive mutation rates based on strategy performance (losing strategies mutate more)
- Market regime-aware evolution with weighted chromosome selection
- Event tracking for all evolution actions via EvolutionAction dataclass

### Testing Requirements
- Unit tests for crossover eligibility validation
- Test mutation rate adaptation based on fitness scores
- Verify fitness calculation requires minimum 20 trades
- Test regime-weighted chromosome selection logic
- Validate lineage tracking for parent-child relationships

### Common Patterns
- Use `crossover_genomes(parent_a, parent_b, market_regime)` for breeding strategies
- Apply mutations via `mutate_genome(genome, market_regime, fitness_score)`
- Calculate fitness with `calculate_fitness(metrics)` from normalized components
- Generate initial population with `seed_initial_population()` for 9 founding archetypes
- Use `compute_shadow_metrics(settled_trades)` for canonical win rate / Sharpe / drawdown calculations from shadow outcomes
- All evolution actions tracked as events for auditability

## Dependencies

### Internal
- `backend.domain.genome.models` — StrategyGenome and chromosome dataclasses
- `backend.domain.evolution.mutation_engine` — Mutation application functions

### External
- `pydantic` — Data validation and serialization
- `random` — Genetic algorithm randomization
- `copy` — Deep copying for genome manipulation
- `uuid` — Unique genome ID generation
