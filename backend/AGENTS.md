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
| Directory | Purpose |
|-----------|---------|
| `core/` | Trading engine — execution, risk, settlement, AGI lifecycle, scheduler (see `core/AGENTS.md`) |
| `strategies/` | Alpha strategy implementations — BaseStrategy subclasses (see `strategies/AGENTS.md`) |
| `ai/` | LLM routing, debate engine, signal parsing, model integrations (see `ai/AGENTS.md`) |
| `api/` | FastAPI routers — auth, markets, trading, AGI, admin, WebSocket/SSE (see `api/AGENTS.md`) |
| `models/` | SQLAlchemy ORM models and session factory (see `models/AGENTS.md`) |
| `data/` | Market data providers, CLOB client, Gamma API, market universe scanner (see `data/AGENTS.md`) |
| `markets/` | Normalized market provider plugin system; Polymarket/Kalshi wrappers return `OrderStatus.REJECTED` for invalid live orders instead of raising raw `NotImplementedError`; paper limit orders stay open without mutating positions until filled |
| `domain/` | Core domain models — genome, evolution engine (see `domain/AGENTS.md`) |
| `modules/` | Infrastructure modules: data feeds, execution helpers, scanners, arbitrage (see `modules/AGENTS.md`) |
| `application/` | Application layer — genome compiler, AGI/meta/strategy orchestration (see `application/AGENTS.md`) |
| `services/` | External service integrations — MiroFish client and monitor (see `services/AGENTS.md`) |
| `repositories/` | Repository layer — DB CRUD abstractions (see `repositories/AGENTS.md`) |
| `agents/` | Autonomous research agent (see `agents/AGENTS.md`) |
| `infrastructure/` | Market stream infrastructure (see `infrastructure/AGENTS.md`) |
| `monitoring/` | Prometheus metrics, Grafana dashboards (see `monitoring/AGENTS.md`) |
| `db/` | Database session utilities and retry logic (see `db/AGENTS.md`) |
| `cache/` | Caching utilities |
| `clients/` | Low-level API clients |
| `integrations/` | Third-party integrations |
| `job_queue/` | Job queue abstractions (SQLite/Redis) |
| `mesh/` | Service mesh utilities |
| `research/` | Research and analysis utilities |
| `scripts/` | Backend-specific operational scripts |
| `sources/` | Data source connectors |
| `utils/` | Shared utility functions |
| `bot/` | Bot runner entrypoint |
| `api_websockets/` | WebSocket connection management |
| `alembic/` | Alembic migration env and version scripts |
| `tests/` | Backend unit and integration tests |

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
