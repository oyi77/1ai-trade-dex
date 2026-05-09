<!-- Parent: ../../AGENTS.md -->
<!-- Generated: 2026-05-07 | Updated: 2026-05-10 -->

# agi

## Purpose
AGI autonomy layer for the application tier. Contains the knowledge graph, lifecycle manager, evolution jobs, performance attribution, forensics feedback, necromancy analysis, and regime population management — the meta-learning and evolutionary components that drive autonomous strategy improvement.

## Key Files

| File | Description |
|------|-------------|
| `__init__.py` | Package marker |
| `knowledge_graph.py` | Knowledge Graph operations — graph queries for strategy evolution, gene performance, and market relationships |
| `lifecycle_manager.py` | Strategy Genome lifecycle state machine — manages DRAFT→SHADOW→PAPER→LIVE→BREEDING→LEGEND→GRAVEYARD transitions |
| `evolution_jobs.py` | APScheduler jobs for fitness evaluation, mutation cycles, crossover cycles, necromancy analysis, and regime rebalancing |
| `forensics_feedback.py` | Applies trade failure insights from TradeForensics back to StrategyConfig — closes the G3 feedback loop |
| `performance_attributor.py` | Scores chromosome contributions to trade outcomes — extends TradeForensics with chromosome-level attribution |
| `necromancer.py` | Weekly analysis of graveyard genomes — identifies high-risk genes and legend patterns from dead experiments |
| `regime_population_manager.py` | Dynamically adjusts strategy allocations based on detected market regime (trending, volatile, calm) |

## Subdirectories

None.

## For AI Agents

### Working In This Directory
- These modules are part of the AGI autonomy layer — they run automatically based on feature flags
- `AGI_AUTO_PROMOTE`, `AGI_AUTO_ENABLE`, `AGI_STRATEGY_HEALTH_ENABLED`, `AGI_BANKROLL_ALLOCATION_ENABLED` control activation
- Lifecycle stage transitions are governed by `docs/architecture/adr-006-agi-autonomy-framework.md`
- The knowledge graph is stored in SQLite via `ExperimentRecord` and related models

### Testing Requirements
- Run: `pytest backend/tests/ -v -k agi`

### Common Patterns
- Jobs are registered in `backend.core.agi_jobs` and run on APScheduler intervals
- All state transitions are logged and auditable
- Fitness evaluation uses Brier score, Sharpe ratio, and drawdown metrics

## Dependencies

### Internal
- `backend.models.database` — StrategyConfig, ExperimentRecord, StrategyOutcome
- `backend.core.agi_types` — ExperimentStatus, MarketRegime enums
- `backend.core.trade_forensics` — Loss pattern analysis
- `backend.config` — Settings and feature flags

### External
- `sqlalchemy` — ORM
- `apscheduler` — Job scheduling

<!-- MANUAL: -->