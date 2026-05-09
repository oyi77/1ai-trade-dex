<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-05-09 | Updated: 2026-05-09 -->

# backend/agents

## Purpose
Autonomous research agent — continuously evolves strategy parameters by running experiments, measuring outcomes, and applying mutations. Operates independently of the main trading loop.

## Subdirectories

| Directory | Purpose |
|-----------|---------|
| `autoresearch/` | Autonomous strategy parameter research and evolution |

## Key Files

| File | Description |
|------|-------------|
| `autoresearch/evolver.py` | `Evolver` — tunes strategy parameters within defined ranges, records outcomes, applies mutations based on performance |
| `autoresearch/__init__.py` | Package marker |

## For AI Agents

### Working In This Directory
- **The evolver operates on `StrategyConfig.params`** — it mutates parameter values within `TUNABLE_PARAM_RANGES` bounds. Do not add parameters to `TUNABLE_PARAM_RANGES` without verifying the strategy handles the full range safely.
- **Evolver writes to `StrategyOutcome` and `ExperimentRecord`** — these are separate from the main `Trade` and `Experiment` tables. Do not conflate them.
- The evolver is triggered by the AGI job scheduler, not by the main trading loop — it runs asynchronously and must not block trade execution.
- Parameter ranges in `TUNABLE_PARAM_RANGES` are hard bounds — the evolver will never set a parameter outside these ranges. Widen them only after validating the strategy handles edge values.

### Testing Requirements
- Test parameter mutation stays within `TUNABLE_PARAM_RANGES` bounds
- Test outcome recording with mock DB session
- Verify evolver does not modify `StrategyConfig.enabled` — it only modifies `params`

## Dependencies

### Internal
- `backend.models.database` — `SessionLocal`, `StrategyConfig`
- `backend.models.outcome_tables` — `StrategyOutcome`
- `backend.models.kg_models` — `ExperimentRecord`
- `backend.core.agi_types` — `ExperimentStatus`

### External
- `sqlalchemy` — ORM queries
