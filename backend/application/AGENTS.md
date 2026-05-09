<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-05-09 | Updated: 2026-05-09 -->

# backend/application

## Purpose
Application layer — orchestrates domain objects and core infrastructure to implement higher-level use cases. Sits between the domain layer (`backend/domain/`) and the API/core layers. Contains the genome compiler, AGI lifecycle management, meta-learning, and strategy execution orchestration.

## Subdirectories

| Directory | Purpose |
|-----------|---------|
| `strategy/` | Genome compiler and strategy execution orchestration |
| `agi/` | AGI lifecycle management — experiment promotion, necromancy, performance attribution |
| `meta/` | Meta-learning and regime-based population management |

## Key Files

| File | Description |
|------|-------------|
| `strategy/genome_compiler.py` | `GenomeCompiler` — translates a `StrategyGenome` into an executable `BaseStrategy` subclass at runtime |
| `strategy/shadow_runner.py` | Runs compiled genome strategies in shadow mode (no real orders) |
| `strategy/arbitrage/` | Arbitrage strategy execution helpers |
| `agi/lifecycle_manager.py` | `LifecycleManager` — manages genome stage transitions: DRAFT→SHADOW→PAPER→LIVE→BREEDING→LEGEND→GRAVEYARD |
| `agi/evolution_jobs.py` | Background jobs for genome evolution (mutation, crossover, fitness evaluation) |
| `agi/forensics_feedback.py` | Feeds trade forensics results back into genome fitness scoring |
| `agi/knowledge_graph.py` | Knowledge graph update logic for AGI learning |
| `agi/necromancer.py` | Weekly analysis of dead genomes — extracts high-risk gene patterns and legend insights |
| `agi/performance_attributor.py` | Attributes P&L to specific genome chromosomes |
| `agi/regime_population_manager.py` | Manages genome population composition based on market regime |
| `meta/regime_router.py` | Routes strategy execution based on detected market regime |

## For AI Agents

### Working In This Directory
- **`GenomeCompiler` bridges domain and execution** — it takes an immutable `StrategyGenome` from the domain layer and produces a live `BaseStrategy` instance. Changes to the genome chromosome structure require updating both `backend/domain/genome/models.py` and `genome_compiler.py`.
- **Lifecycle stages are distinct from experiment statuses** — `LifecycleManager` manages genome stages (DRAFT→GRAVEYARD); `backend/core/autonomous_promoter.py` manages experiment statuses (DRAFT→LIVE_PROMOTED→RETIRED). They are parallel but separate systems.
- **Necromancy runs weekly** — it is a background analysis job, not a real-time process. Do not call it in hot paths.
- Auto-kill conditions in `lifecycle_manager.py` are: >50% drawdown, <20% win rate after 30 trades, Sharpe <-0.5 after 20 trades. Do not relax these without an ADR.

### Testing Requirements
- Test `GenomeCompiler` produces a valid `BaseStrategy` subclass from a well-formed genome
- Test `LifecycleManager` stage transitions with valid and invalid promotion criteria
- Test necromancy report generation with mock graveyard data

### Common Patterns
- Compile a genome: `compiler = GenomeCompiler(); strategy_cls = compiler.compile(genome); strategy = strategy_cls()`
- Promote a genome: `manager = LifecycleManager(db); manager.transition(genome_id, to_stage="PAPER")`

## Dependencies

### Internal
- `backend.domain.genome.models` — `StrategyGenome`, chromosomes
- `backend.domain.evolution` — fitness calculation, evolution actions
- `backend.strategies.base` — `BaseStrategy`, `StrategyContext`, `CycleResult`
- `backend.core.event_bus` — event publishing
- `backend.models.database` — DB persistence

### External
- `pydantic` — data validation
