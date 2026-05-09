<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-05-09 | Updated: 2026-05-09 -->

# backend/domain

## Purpose
Core domain models for strategy evolution and genetic programming. The innermost layer — no dependencies on `backend/core/`, `backend/api/`, or any infrastructure. Contains the formal genome grammar and evolution engine.

## Subdirectories

| Directory | Purpose |
|-----------|---------|
| `genome/` | `StrategyGenome` entity and its chromosomes, fitness metrics, lineage tracking (see `genome/AGENTS.md`) |
| `evolution/` | Genetic algorithm engine — mutation, crossover, fitness evaluation, population seeding (see `evolution/AGENTS.md`) |

## For AI Agents

### Working In This Directory
- **This is the innermost domain layer** — it must not import from `backend/core/`, `backend/api/`, `backend/strategies/`, or any infrastructure module. Violations break the dependency hierarchy.
- All models are immutable Pydantic `BaseModel` subclasses — mutations create new instances via `.copy(update={...})`, never mutate in place.
- Fitness scores are normalized to `[0.0, 1.0]` — do not store raw metric values as fitness scores.
- The genome grammar defines the chromosome structure: `perception`, `cognition`, `execution`, `risk`, `meta` — do not add chromosomes without updating the `GenomeCompiler` in `backend/application/strategy/genome_compiler.py`.

### Testing Requirements
- Test genome immutability — mutations must return new instances
- Test fitness normalization constraints
- Test lineage parent-child relationships

## Dependencies

### Internal
- None — this is the innermost domain layer

### External
- `pydantic` — data validation and serialization
- `uuid` — unique genome ID generation
- `datetime` — timestamp management
