# BACKEND ENGINE
<!-- Parent: ../AGENTS.md -->

**Generated:** 2026-05-14 20:53:49 UTC

## OVERVIEW

Python FastAPI backend: execution kernel (core/), REST API (api/), 12 trading strategies, market data aggregation, AGI evolution. 137K LOC, 18+ subdirs.

## STRUCTURE

```
backend/
├── core/             # Kernel: executor, scheduler, settlement, risk
├── api/              # FastAPI + 10 routers (189 endpoints)
├── strategies/       # 12 alpha-generating strategies
├── modules/          # Signal modules (external feed infrastructure)
├── models/           # SQLAlchemy ORM (2130 LOC)
├── data/             # Market data aggregation
├── application/      # AGI evolution, composition
├── ai/               # Signal generation, ML
├── job_queue/        # Task scheduler backend
├── clients/          # API clients (Polymarket, Kalshi)
├── integrations/     # External integrations
├── domain/           # Domain models
├── bot/              # Telegram notifications
├── monitoring/       # Health checks, metrics
└── tests/            # pytest suite
```

## WHERE TO LOOK

| Module | Purpose | Key Files | LOC |
|--------|---------|-----------|-----|
| **core/** | Execution kernel | executor (1529), scheduler (1375), settlement (1344) | 5.8K |
| **api/** | REST API layer | main.py (2234), settings.py (928), auth.py (734) | 8.2K |
| **strategies/** | Alpha generators | 8-12 strategy files; agi_orchestrator, btc_oracle, ... | 6K+ |
| **models/** | SQLAlchemy ORM | database.py (2130) | 2.1K |
| **data/** | Market aggregation | polymarket_clob.py (989) | 1.2K |
| **application/** | Orchestration | evolution_jobs.py (906) | 1.8K |
| **modules/** | Signal infrastructure | weather_emos (905), whale trackers, copy_trader | 2K+ |
| **ai/** | Signal generation | ML pipelines | 800+ |
| **bot/** | Notifications | telegram_bot.py (858) | 900+ |

## CRITICAL RULES

### Settlement (Sacred Path)
- Settlement transaction NEVER aborts for non-critical hooks (analytics, learning). Stale positions block new orders.
- Use `closed_unresolved` state if market lags but wallet proves position gone.
- Reconciliation: settle trades → reconcile bankroll (2-phase, `core/settlement_helpers.py`).

### Error Handling
- NEVER bare `except Exception: pass`. Always `logger.exception("descriptive")`.
- Use structured logging (context: trade_id, strategy_id, etc.).

### Strategy Governance
- AGI auto-kills strategies with <30% win rate (health check every 15min).
- Disabled state lives in `StrategyConfig` DB table, NOT code.
- Module-resident strategies (`modules/`) are infrastructure, not alpha. Same governance.

### Health Checks
- Bounded dependency checks: slow RPC degrades health, doesn't hang.
- `/api/v1/health` uses tiered checks (bounded lookups).

## ENTRY POINTS

```bash
python main.py                          # Live trading
python run.py                           # Alternative runner
cd backend && python -m backend         # Module runner
```

## ANTI-PATTERNS

- ❌ Silent exception handling (`except: pass`)
- ❌ Manual `StrategyConfig.enabled` changes (AGI auto-kill is final)
- ❌ Blocking settlement for non-critical hooks
- ❌ Synchronous RPC in health checks
- ❌ FIXME/TODO in production code

## CONVENTIONS

- Database migrations: Alembic (`alembic/versions/`) with down() rollback
- Logging: structured, contextual, JSON-formatted
- Testing: pytest in `backend/tests/`
- Imports: type hints required (mypy compliance)
- Configuration: `backend/config.py` (1776 LOC) + overrides in `config_hft.py`

## DEPLOYMENT

Entry: `main.py` or `run.py`  
Config: `backend/config.py`, `backend/config_hft.py`  
Migrations: `alembic/versions/`  
Docker: `Dockerfile` (multi-stage), `docker-compose.yml`  
CI/CD: `.github/workflows/`
