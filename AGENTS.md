<!-- Generated: 2026-04-10 | Updated: 2026-05-09 -->

# polyedge

## Purpose
Polyedge is a full-stack automated prediction market trading bot targeting Polymarket and Kalshi. It combines AI-powered signal generation, multi-strategy execution, real-time market data aggregation, and a React dashboard for monitoring and control. The system supports paper trading (shadow mode), live trading with risk controls, and comprehensive backtesting.

## Key Files

| File | Description |
|------|-------------|
| `main.py` | Application entry point — starts FastAPI server and background workers |
| `run.py` | Alternate runner with environment validation |
| `requirements.txt` | Python package dependencies |
| `docker-compose.yml` | Multi-service container setup (app + Redis) |
| `Dockerfile` | Backend container build |
| `ecosystem.config.js` | PM2 process manager configuration for production (removed mirofish-mock process) |
| `railway.json` | Railway.app deployment configuration |
| `vercel.json` | Vercel edge configuration for frontend |
| `pytest.ini` | Test runner configuration |
| `.env.example` | Required environment variable template |
| `ARCHITECTURE.md` | High-level system architecture overview |
| `README.md` | Project overview and setup guide |
| `POLYMARKET_SETUP.md` | Polymarket API credential setup guide |
| `IMPLEMENTATION_GAPS.md` | Known gaps and incomplete features |
| `test_backtest_data.py` | Root-level backtest data validation tests |
| `backend/core/autonomous_promoter.py` | Experiment lifecycle daemon — auto-promotes DRAFT→SHADOW→PAPER→LIVE, auto-retires killed experiments, health-based kill checks |
| `backend/core/bankroll_allocator.py` | Daily capital allocator — computes allocations via `StrategyRanker`, persists to `BotState.misc_data` |
| `backend/core/trade_forensics.py` | Per-loss trade analysis — diagnoses root causes, aggregates pattern insights |
| `backend/data/market_universe.py` | MarketUniverseScanner — universal market discovery across platforms using DataProvider ABC with configurable TTL cache |
| `backend/models/genome_registry.py` | ORM models for genome persistence — GenomeRegistry, GenomePerformance, GenomeShadowTrade |
| `backend/repositories/genome_repository.py` | Repository layer — CRUD operations for genome persistence |
| `backend/application/strategy/genome_compiler.py` | GenomeCompiler — runtime translation of StrategyGenome into executable BaseStrategy subclass |
| `docs/architecture/adr-006-agi-autonomy-framework.md` | AGI autonomy governance — promotion gates, safety boundaries, human-in-the-loop override |

## Subdirectories

| Directory | Purpose |
|-----------|---------|
| `backend/` | Python FastAPI backend — trading engine, strategies, data feeds, AI (see `backend/AGENTS.md`) |
| `frontend/` | React/TypeScript dashboard — monitoring UI, admin controls (see `frontend/AGENTS.md`) |
| `docs/` | Architecture docs, API reference, how-it-works guides (see `docs/AGENTS.md`) |
| `tests/` | Integration tests at project root level (see `tests/AGENTS.md`) |
| `scripts/` | Operational scripts: seed, verify, backup, health-check, migration (see `scripts/AGENTS.md`) |
| `.github/` | GitHub Actions CI workflow |
| `alembic/` | Database migration framework (standard Alembic setup) |
| `backend/modules/` | Infra modules (NOT alpha strategies): data feeds, execution helpers, arbitrage, scanners (see `backend/modules/AGENTS.md`) |

## For AI Agents

### Working In This Directory
- **MANDATORY: Documentation Sync** — Every code change MUST be accompanied by updating all affected documentation. This includes: AGENTS.md files (root + relevant subdirectory), API docs (`docs/api.md`), ADRs (`docs/architecture/`) for architectural decisions, `IMPLEMENTATION_GAPS.md` for newly discovered gaps, `.env.example` for new environment variables. Do NOT skip docs updates. If you add/rename/remove a file, update the Key Files table in the nearest AGENTS.md. If you add a new endpoint, update `docs/api.md`. If you change behavior, update the relevant doc.
- Never commit `.env` — it contains live API keys and wallet credentials
- Environment variables are documented in `.env.example`; always keep that in sync
- **Database schema changes require an Alembic migration**: `alembic revision --autogenerate -m "description"` then `alembic upgrade head`. Never modify existing migration files.
- Production deploys to Railway (backend) + Vercel (frontend) — check `railway.json` and `vercel.json`
- Docusaurus docs deploy inside the Vercel frontend under `/docs/`; document URLs are emitted as `.html` files and Vercel rewrites extensionless `/docs/*` routes to those files before the Vite catch-all so docs pages do not render the dashboard shell.
- PM2 manages three processes in production: `polyedge-api` (FastAPI server), `polyedge-bot` (background worker + scheduler), `polyedge-frontend` (Vite dev server) — process names are `polyedge-*`, not just `polyedge`
- Live `BotState.bankroll`/`total_pnl` are derived caches from CLOB USDC cash + Polymarket Data API open-position value; do not recompute live equity from local ledger/backfill P&L (see `docs/architecture/adr-002-live-equity-source.md`)
- Paper/testnet PnL may be negative, but available simulated bankroll/balance must never be negative; settlement, reconciliation, and stats/dashboard output floor depleted simulated bankroll at `$0.00` while preserving learning trades and PnL history.
- Trade execution observability uses the `TradeAttempt` ledger and dashboard Control Room; do not replace it with log scraping or mutate historical `Trade` rows to explain rejected attempts (see `docs/architecture/adr-003-trade-attempt-observability.md`)
- Autonomous trade sizing is bounded: strategy/AI code may propose dynamic sizes, but deterministic `RiskManager` mandates and minimum-order gates remain non-bypassable (see `docs/architecture/adr-004-bounded-autonomous-sizing.md`)

### Testing Requirements
- Backend tests: `pytest` from project root (uses `pytest.ini`)
- Frontend tests: `cd frontend && npm test`
- E2E tests: `cd frontend && npx playwright test`
- Do not run live trading tests without `SHADOW_MODE=true`

### Common Patterns
- `.env` feature flags control system behavior (e.g., `JOB_WORKER_ENABLED`, `SHADOW_MODE`, `AGI_AUTO_PROMOTE`, `AGI_AUTO_ENABLE`, `AGI_STRATEGY_HEALTH_ENABLED`, `AGI_BANKROLL_ALLOCATION_ENABLED`)
- All external API base URLs are configurable via env vars (see `GAMMA_API_URL`, `DATA_API_URL`, `CLOB_API_URL`, etc. in `backend/config.py`)
- Frontend polling intervals are configurable via `VITE_POLL_FAST_MS`, `VITE_POLL_NORMAL_MS`, `VITE_POLL_SLOW_MS`, `VITE_POLL_VERY_SLOW_MS` (see `frontend/src/polling.ts`)
- Realtime SSE/WS auth uses admin cookie sessions (`admin_session`) with optional legacy `token=ADMIN_API_KEY` fallback; frontend should not append CSRF/localStorage secrets to SSE/WS URLs
- All sensitive operations guarded by circuit breakers and risk limits
- Redis optional — falls back to SQLite queue when unavailable
- `backend/modules/` is for infrastructure modules (data feeds, execution helpers, arbitrage, scanners) — NOT alpha strategies. Alpha strategies go in `backend/strategies/`.
- **Strategy Governance**: AGI health check (`AGI_HEALTH_CHECK_ENABLED`, every 15 min via `AGI_HEALTH_CHECK_INTERVAL_MINUTES`) auto-kills strategies with <30% win rate after sufficient trades. Killed strategies are disabled in `StrategyConfig` and should NOT be manually re-enabled. The authoritative enabled/disabled state is always the `StrategyConfig` table in the DB — the list below is a snapshot. Active (`backend/strategies/`): `agi_orchestrator`, `btc_oracle` (52.1% WR, +$161 PnL), `universal_scanner`, `bond_scanner`, `cex_pm_leadlag`, `cross_market_arb`, `line_movement_detector`, `market_maker`. Active (`backend/modules/`, module-resident): `copy_trader`, `weather_emos`, `whale_frontrun`, `whale_pnl_tracker`. Disabled: `general_scanner` (10% WR, auto-killed), `btc_momentum` (deprecated), `realtime_scanner`, `probability_arb`. Module-resident strategies live in `backend/modules/` because they source signals from external feeds (leaderboard mirroring, on-chain data, weather APIs) rather than generating independent alpha from market analysis — they are infrastructure, not alpha strategies, but they are registered and governed the same way.
- **Trade Attribution**: `auto_trader` (`backend/core/auto_trader.py`) is an execution router, NOT a strategy. It routes pending signals through risk validation. Trade attribution uses `Signal.track_name` to preserve the originating strategy name. Historical trades attributed to "auto_trader" actually came from various signal sources routed through the auto-execute path.

## Dependencies

### External
- `FastAPI` + `uvicorn` — Python web framework
- `React 18` + `TypeScript` + `Vite` — Frontend
- `SQLite` / `Redis` — Storage and job queue
- `SQLAlchemy 2.0` + `Alembic` — ORM and migrations
- Polymarket CLOB API, Kalshi API — Market data and order execution
- Anthropic Claude API — AI signal analysis
- Groq API — Fast LLM inference
- `MiroFish` — External dual debate system for trade decisions

<!-- MANUAL: -->
