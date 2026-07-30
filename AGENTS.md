# AGENTS.md — 1ai-trade-dex

## MANDATORY PROCESS (8 Steps — No Skipping)

Every task follows this sequence. No exceptions.

1. **AUDIT** — Read existing code. Understand current state.
2. **THINK** — Understand WHY. Intent vs literal.
3. **BRAINSTORM** — ≥3 approaches. Score options.
4. **PLAN** — Decompose. Risks. Rollback plan.
5. **EXECUTE** — Build. TDD when possible.
6. **TEST** — Run all tests. Break it first.
7. **VERIFY** — Prove with literal output.
8. **REVIEW** — Read your own diff before committing.

Full details: `~/.1ai/core/PROCESS.md` (auto-injected by hooks)

## This repo
Automated prediction market and perpetual DEX trading bot — 10+ platforms, 14 strategies, AGI evolution, React dashboard.

Stack: Python (FastAPI, SQLAlchemy, APScheduler) + TypeScript (React, Vite, TanStack Query)
Domain: Prediction market trading, DEX arbitrage, automated strategy execution

## Rules — thin loader, no submodule
Rules are NOT vendored into this repo. This repo does NOT need a rules submodule.
`AGENTS.md` is only the repo-local loader: domain, commands, conventions, and pointers to `~/.1ai`.

Engineering rules are enforced by machine-level loaders when `setup-dev.sh` has been run:
- Claude Code: SessionStart hook injects `~/.1ai/core/RULES.md`
- OpenCode: plugin injects `~/.1ai/core/RULES.md`
- OMP: wrapper appends `~/.1ai/core/RULES.md` to launch sessions

Primary rules file:
```bash
cat ~/.1ai/core/RULES.md
```

Pre-ship gate:
```bash
cat ~/.1ai/core/GATE.md
```

If `~/.1ai` or auto-load is missing, run:
```bash
bash ~/.1ai/scripts/setup-dev.sh
```

Do NOT add the rules repo as a git submodule. Update rules centrally, then run/sync the thin `AGENTS.md` template.

## Hard rules
1. Read code before writing code.
2. No completion claim without literal receipt.
3. Compile/test/use like a real user before claiming work is ready.
4. Task must match this repo domain.
5. Run GATE.md before commit/PR.

## Repo-specific conventions
- Backend: Python/FastAPI under `backend/`
- Frontend: React/TypeScript under `frontend/`
- Models: SQLAlchemy in `backend/models/database.py` — 2763 lines, single-file schema
- Config: Pydantic-settings in `backend/config.py` — all externalized to `.env`
- Tests: pytest — `backend/tests/` (unit) and `tests/` (integration)
- Strategies: `backend/strategies/` — each strategy is a self-contained module
- Providers: plugin-based auto-discovery in provider registry
- Database: Alembic migrations in `alembic/`, SQLite default, PostgreSQL in production

## Module map (post-2026-07-30 refactor)
Key packages and their split structure:

| Domain | Package | Modules |
|--------|---------|---------|
| Config | `backend/config/` | `mixins/api_urls.py`, `mixins/strategy.py`, `mixins/risk.py`, `mixins/agi.py` |
| Settlement | `backend/core/settlement/` | `settlement/helpers.py`, `settlement/btc_settle.py`, `settlement/settlement_core.py`, `settlement/learning.py`, `settlement/bot_state.py` |
| Settlement helpers | `backend/core/settlement/` | `resolution.py`, `calculate_pnl.py`, `weather.py`, `process.py`, `reconcile.py` |
| AGI | `backend/application/agi/` | `genome_helpers.py`, `evolution_cycles.py`, `scheduler_jobs.py` |
| Strategy promotion | `backend/core/` | `autonomous_promoter/criteria.py`, `autonomous_promoter/workflow.py`, `autonomous_promoter/review.py`, `autonomous_promoter/job.py` |
| Knowledge graph | `backend/core/` | `knowledge_graph/entity.py`, `knowledge_graph/query.py`, `knowledge_graph/snapshot.py`, `knowledge_graph/graph_api.py`, `knowledge_graph/analysis.py` |
| Polymarket CLOB | `backend/data/` | `polymarket_clob/models.py`, `polymarket_clob/helpers.py`, `polymarket_clob/client.py`, `polymarket_clob/factory.py` |
| Risk | `backend/core/risk/` | `models.py`, `validators/allocation.py`, `validators/calibration.py`, `validators/concentration.py`, `validators/drawdown.py`, `validators/edge.py`, `validators/sidelock.py` |
| Strategy executor | `backend/core/` | `strategy_executor/` (7 modules) |
| System router | `backend/api/system/` | 3 sub-routers (agi, events, risk) |

**Module naming**: Private functions preserve their names in extracted modules. Mixin classes assembled via MI in `__init__.py`.

## Commands
- Backend dev: `uvicorn backend.api.main:app --reload --port 8100`
- Frontend dev: `cd frontend && npm run dev`
- Test (all): `pytest`
- Test (backend): `pytest backend/tests/`
- Test (frontend): `cd frontend && npm run test`
- Build: `cd frontend && npm run build`
- Docker: `docker-compose up -d`
- DB migrate: `alembic upgrade head`
