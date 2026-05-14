# PROJECT KNOWLEDGE BASE

**Generated:** 2026-05-14 20:53:49 UTC  
**Commit:** 0fa0dbb  
**Branch:** main

## OVERVIEW

**PolyEdge**: Automated prediction market trading bot (Polymarket + Kalshi). 187K LOC Python backend + 23K LOC TypeScript frontend. Combines AI-powered signals, 12+ trading strategies, evolutionary AGI composition, real-time market data, and React dashboard with bounded autonomy.

## STRUCTURE

```
polyedge/
├── backend/              # Core engine (137K LOC, 18+ subdirs)
│   ├── core/             # Kernel: executor, scheduler, settlement, risk
│   ├── api/              # FastAPI (189 endpoints, 2234 LOC)
│   ├── strategies/       # 12 trading strategies (alpha)
│   ├── modules/          # Signal modules (external feeds, infrastructure)
│   ├── models/           # SQLAlchemy ORM (2130 LOC)
│   ├── data/             # Market aggregation (Polymarket CLOB)
│   ├── application/      # AGI evolution, composition
│   ├── ai/               # Signal generation, ML
│   └── job_queue/, clients/, integrations/, ...
├── frontend/             # React dashboard (23K LOC)
│   └── src/
│       ├── components/   # 30+ React components
│       ├── pages/        # Page containers
│       ├── hooks/        # Custom React hooks
│       ├── api.ts        # Fetch client (1076 LOC)
│       └── test/, e2e/   # Vitest + Playwright
├── tests/                # pytest suite (24 files)
├── alembic/              # Database migrations
├── docs/                 # Research, audit reports
├── scripts/              # CLI utilities
└── Root: main.py, run.py, ARCHITECTURE.md
```

## WHERE TO LOOK

| Task | Location | Notes |
|------|----------|-------|
| **Strategy execution** | `backend/core/strategy_executor.py` (1529 LOC) | Bounded AGI autonomy; per-tier allocation limits |
| **Trading strategies** | `backend/strategies/` (8-12 files) | agi_orchestrator, btc_oracle, universal_scanner, ... |
| **Signal modules** | `backend/modules/` | External-feed infrastructure: weather_emos, whale_frontrun, copy_trader |
| **API routes** | `backend/api/main.py` (2234 LOC) + 10 routers | /signals, /trades, /strategies, /risk, /admin, ... |
| **Settlement** | `backend/core/settlement_helpers.py` (1344 LOC) | 2-phase: settle trades → reconcile bankroll (CRITICAL PATH) |
| **Scheduler** | `backend/core/scheduler.py` (1375 LOC) | Cron + event coordination; 15min AGI health checks |
| **Risk profiles** | `backend/core/risk_profiles.py` | 6 tiers: safe→crazy; RISK_TIER_MAX_ALLOCATION dict |
| **Database schema** | `backend/models/database.py` (2130 LOC) | SQLAlchemy; StrategyConfig, Trade, ShadowTrade, StrategyGenome |
| **Dashboard** | `frontend/src/pages/`, `frontend/src/components/` | React; polling via VITE_POLL_*_MS |
| **Market data** | `backend/data/polymarket_clob.py` (989 LOC) | Polymarket CLOB + Kalshi APIs |
| **AGI evolution** | `backend/application/agi/evolution_jobs.py` (906 LOC) | Genome composition, mutation, fitness cycles |
| **Notifications** | `backend/bot/telegram_bot.py` (858 LOC) | Alert system |

## CRITICAL RULES (THIS PROJECT)

### Settlement (SACRED)
- Settlement transaction MUST NOT abort due to non-critical hooks (analytics, learning). Stale live positions block new orders.
- If market resolution lags but wallet reconciliation proves position gone → use `closed_unresolved` state (release exposure, no win/loss claim).
- Always keep live exposure accurate in DB.

### Error Handling
- NEVER bare `except Exception: pass`. Always `logger.exception("descriptive message")`. Silent errors are #1 observability failure.

### Strategy Governance
- AGI auto-kills strategies with <30% win rate (health check every 15min: `AGI_HEALTH_CHECK_ENABLED`, `AGI_HEALTH_CHECK_INTERVAL_MINUTES`).
- Authoritative enabled/disabled state is `StrategyConfig` DB table, NOT code. Don't manually re-enable killed strategies.
- Strategies in `backend/modules/` are **infrastructure** (external signals), not alpha generators. Same governance rules apply.

### Frontend Polling
- Configurable intervals: `VITE_POLL_FAST_MS`, `VITE_POLL_NORMAL_MS`, `VITE_POLL_SLOW_MS`, `VITE_POLL_VERY_SLOW_MS`.
- See `frontend/src/polling.ts` for defaults.

### Health Checks
- Use **bounded dependency checks**: slow RPC calls degrade health, NOT hang requests (`/api/v1/health` uses tiered checks).

### Duplicate Trade Detection
- Alert if >3 trades on same market/minute.

## CONVENTIONS

- **Database migrations**: Alembic in `alembic/versions/`. Always provide down() for rollback.
- **Test organization**: pytest in `backend/tests/`, Vitest in `frontend/src/test/`, E2E in `frontend/e2e/`.
- **Monorepo layout**: Backend + frontend independent; shared types in `backend/models/` and `frontend/src/types.ts`.
- **Logging**: Use structured logging everywhere; include context (trade_id, strategy_id, etc.).

## KEY MODULES (by LOC & complexity)

| Module | Purpose | Files | LOC | Key Files |
|--------|---------|-------|-----|-----------|
| `backend/core` | Execution kernel | 10+ | 5.8K | executor (1529), scheduler (1375), settlement (1344) |
| `backend/api` | REST API layer | main + 10 routers | 8.2K | main.py (2234), settings.py (928), auth.py (734) |
| `backend/models` | Data layer, ORM | 1 | 2.1K | database.py (2130) |
| `backend/strategies` | Alpha generation | 8-12 | 6K+ | general_market_scanner (956), various strategy files |
| `backend/application` | Orchestration | 5+ | 1.8K | evolution_jobs.py (906) |
| `backend/data` | Market aggregation | 5+ | 1.2K | polymarket_clob.py (989) |
| `backend/ai` | Signal generation | 8+ | 800+ | ML pipelines, transformers |
| `backend/modules` | Signal infrastructure | 4+ | 2K+ | weather_emos (905), whale trackers, copy trader |
| `frontend` | React dashboard | 30+ comps + pages + hooks | 23K | api.ts (1076), Landing (680), LiveStream (604) |

## ANTI-PATTERNS (FORBIDDEN HERE)

- ❌ Bare `except Exception: pass` (silent errors)
- ❌ Manual `StrategyConfig.enabled` changes in code (AGI auto-kill is final)
- ❌ Blocking settlement for non-critical hooks
- ❌ Synchronous RPC calls in health checks (causes hangs)
- ❌ Duplicate trades without alerting (>3/min threshold)
- ❌ Unresolved positions without using `closed_unresolved` state
- ❌ FIXME/TODO in production code (resolve before merge)

## ENTRY POINTS

```bash
# Backend
python main.py                          # Live trading entry
python run.py                           # Alternative runner
cd backend && python -m backend         # Module runner

# Frontend
npm run dev                             # Vite dev server
npm run build                           # Production build

# Database
alembic upgrade head                    # Apply migrations
alembic revision --autogenerate -m "msg"  # Create migration

# Tests
pytest backend/tests/ -v                # Pytest suite
npm run test                            # Vitest + Playwright
```

## CONFIGURATION

- **Backend config**: `backend/config.py` (1776 LOC) — main settings
- **Backend HFT**: `backend/config_hft.py` — high-frequency trading overrides
- **Frontend polling**: `frontend/src/polling.ts` — VITE_POLL_* intervals
- **Database**: SQLite (dev); migrations in `alembic/versions/`
- **CI/CD**: `.github/workflows/` — GitHub Actions

## DEPLOYMENT

- **Docker**: `Dockerfile`, `docker-compose.yml`
- **Railway**: `railway.json`
- **PM2**: `ecosystem.config.js`
- **systemd**: `polyedge-api.service`
- **Environment**: `.env.example` (copy to `.env`)

## NOTES

- **Archived code**: `archive/` contains legacy/experimental branches; don't reference unless intentional.
- **Test failures**: Check `test_results.txt`, `playwright-console.txt`, `playwright-network.txt`.
- **Database**: `polyedge.db` (main), `trading_bot.db` (legacy), backups in `backups/`.
- **Research**: Papers and audit reports in `docs/`.
- **Broker APIs**: Polymarket CLOB + Kalshi direct integration.
