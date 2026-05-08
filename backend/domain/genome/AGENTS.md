<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-05-09 | Updated: 2026-05-09 -->

# backend/domain/genome

## Purpose

Core domain model for strategy evolution and genetic programming. Defines the StrategyGenome entity with its chromosomes, fitness metrics, and lineage tracking using a formal genome grammar.

## Key Files

| File | Description |
|------|-------------|
| `__init__.py` | Package marker for genome models |
| `models.py` | Pydantic models for strategy evolution - StrategyGenome, chromosomes, FitnessMetrics, LineageData, DeathCertificate |

## For AI Agents

### Working In This Directory
- All models are immutable Pydantic BaseModel subclasses
- StrategyGenome uses lineage tracking for parent-child relationships
- FitnessMetrics cache computed scores to avoid recomputation
- Chromosomes represent trading strategy components (perception, cognition, execution, risk, meta)
- DeathCertificate tracks strategy lifecycle and rehabilitation eligibility

### Testing Requirements
- Test genome immutability - mutations create new instances via `.copy()`
- Validate lineage parent-child relationships
- Test fitness metric normalization and constraints
- Verify chromosome model validation for trading strategy parameters

### Common Patterns
- Create new genomes with `StrategyGenome(**genome_data, genome_id=str(uuid4()))`
- Access chromosomes via `genome.chromosomes["perception|cognition|execution|risk|meta"]`
- Track fitness with `FitnessMetrics(sharpe_ratio=X, win_rate=Y, ...)`
- Manage lineage with `LineageData(parent_genome_ids=[], generation=1, creator="human|mutation|crossover|synthesis")`
- Handle strategy death with `DeathCertificate` for retired strategies

## Dependencies

### Internal
- None - this is the innermost domain layer

### External
- `pydantic` — Data validation and serialization
- `uuid` — Unique identifier generation
- `datetime` — Timestamp management
- `dataclasses` — Dataclass definitions for DeathCertificate