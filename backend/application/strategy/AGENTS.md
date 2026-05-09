<!-- Parent: ../../AGENTS.md -->
<!-- Generated: 2026-05-07 | Updated: 2026-05-10 -->

# strategy

## Purpose
Application-layer strategy execution wrappers. Contains shadow trade tracking for strategy validation and arbitrage-specific monitors.

## Key Files

| File | Description |
|------|-------------|
| `__init__.py` | Package marker (empty) |
| `shadow_runner.py` | DB-backed ShadowRunner — persists shadow trades across restarts for long-running strategy validation; replaces in-memory ShadowRunner (deprecated) |
| `genome_compiler.py` | GenomeCompiler — translates StrategyGenome into executable BaseStrategy subclass at runtime |

## Subdirectories

| Directory | Purpose |
|-----------|---------|
| `arbitrage/` | Pair cost arbitrage monitor (see `arbitrage/AGENTS.md`) |

## For AI Agents

### Working In This Directory
- `ShadowRunner` writes to `ShadowTrade` ORM table with genome linkage
- Shadow trades track hypothetical performance without real execution
- Performance metrics match `ShadowPerformance` dataclass from `backend.core.shadow_mode`

### Testing Requirements
- Run: `pytest backend/tests/ -v -k shadow`

### Common Patterns
- DB-backed persistence for all shadow trades
- Genome linkage via `GenomeRegistry` table
- Stats computed from trade history on demand

## Dependencies

### Internal
- `backend.models.database` — ShadowTrade, GenomeRegistry, SessionLocal
- `backend.core.shadow_mode` — ShadowPerformance dataclass
- `backend.config` — Settings

### External
- `sqlalchemy` — ORM

<!-- MANUAL: -->