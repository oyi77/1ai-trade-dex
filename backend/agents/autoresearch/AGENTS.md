<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-05-07 | Updated: 2026-05-10 -->

# autoresearch

## Purpose
Autonomous research and strategy discovery agent. Evolves strategy parameters through self-improving search, exploring the tunable parameter space to discover better configurations.

## Key Files

| File | Description |
|------|-------------|
| `__init__.py` | Package marker |
| `evolver.py` | Self-improving strategy parameter evolver — mutates tunable parameters within defined ranges, evaluates fitness, and promotes better configurations |

## Subdirectories

None.

## For AI Agents

### Working In This Directory
- The evolver uses `TUNABLE_PARAM_RANGES` to constrain parameter mutations
- Results are persisted to `StrategyConfig` in the database
- Fitness is evaluated via `StrategyOutcome` and `ExperimentRecord`

### Testing Requirements
- Run: `pytest backend/tests/ -v -k evolver`

### Common Patterns
- Parameter ranges defined as class-level dict
- Fitness evaluation uses historical trade performance
- Promoted configurations are upserted into `StrategyConfig`

## Dependencies

### Internal
- `backend.models.database` — StrategyConfig, ExperimentRecord
- `backend.models.outcome_tables` — StrategyOutcome
- `backend.models.kg_models` — Knowledge graph models
- `backend.core.agi_types` — ExperimentStatus enum

### External
- `sqlalchemy` — ORM for database access
- `random` — Parameter mutation randomness

<!-- MANUAL: -->