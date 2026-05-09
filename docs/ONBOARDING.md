# PolyEdge Onboarding Guide

> **Last updated**: 2026-05-04 · **Git**: `d1df035c` · **Analyzed files**: 1,053

## Quick Start

```bash
# 1. Backend setup
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env  # Edit with your API keys

# 2. Frontend setup
cd frontend && npm install && npm run dev

# 3. Docker alternative
docker-compose up -d
```

**Backend**: http://localhost:8000 · **API docs**: http://localhost:8000/docs · **Frontend**: http://localhost:5173

---

## Project Overview

**PolyEdge** is a full-stack automated prediction market trading bot targeting **Polymarket** and **Kalshi**. It combines AI-powered signal generation, 9 trading strategies, real-time market data aggregation, and a React dashboard for monitoring and control.

| Aspect | Details |
|--------|---------|
| **Languages** | Python 3.10+, TypeScript 5.0+, JavaScript, SQL, Shell, YAML, Dockerfile |
| **Frameworks** | FastAPI, React 18, SQLAlchemy 2.0, Pydantic 2, Alembic, TanStack Query, Vite, TailwindCSS |
| **AI** | Claude (Anthropic), Groq, MiroFish (external dual-debate) |
| **Markets** | Polymarket (CLOB SDK), Kalshi (REST API) |
| **Infra** | Docker Compose, Redis/SQLite queue, APScheduler, Prometheus metrics |

---

## Architecture

PolyEdge follows a **layered architecture** with clear separation of concerns:

```
┌─────────────────────────────────────────────────────┐
│  Frontend (React + TypeScript + Tailwind + Vite)     │
│  Dashboard · Admin · Signals · Trades · 3D Globe      │
├─────────────────────────────────────────────────────┤
│  API Layer (FastAPI + WebSockets)                    │
│  Auth · Trading · Admin · Dashboard · Brain Stream   │
├─────────────────────────────────────────────────────┤
│  Core Engine                                         │
│  Orchestrator · Risk Manager · Settlement · Backtest │
├─────────────────────────────────────────────────────┤
│  AI & Strategies                                     │
│  Claude/Groq · Debate Engine · 9 Strategies          │
├─────────────────────────────────────────────────────┤
│  Data Sources                                        │
│  Polymarket CLOB · Kalshi · Coinbase/Binance · NWS    │
├─────────────────────────────────────────────────────┤
│  Infrastructure                                      │
│  SQLite/Redis · APScheduler · Docker · PM2 · Railway  │
└─────────────────────────────────────────────────────┘
```

### Architecture Layers (17 total)

| Layer | Description | Key Files |
|-------|-------------|-----------|
| **Infrastructure & Deployment** | Docker, CI/CD, deployment configs | `Dockerfile`, `docker-compose.yml`, `railway.json`, `ecosystem.config.js` |
| **Database & Migrations** | SQLAlchemy ORM, Alembic migrations | `backend/models/`, `alembic/versions/` |
| **Core Trading Engine** | Orchestrator, risk, settlement, backtesting | `backend/core/orchestrator.py`, `backend/core/risk_manager.py`, `backend/core/settlement.py` |
| **AI & Signal Generation** | Claude, Groq, debate engine, signal parsing | `backend/ai/claude.py`, `backend/ai/groq.py`, `backend/ai/debate_engine.py` |
| **Trading Strategies** | 9 parallel strategies with risk isolation | `backend/strategies/btc_momentum.py`, `backend/strategies/weather_emos.py`, `backend/strategies/copy_trader.py` |
| **API & WebSocket Layer** | FastAPI routes, auth, middleware | `backend/api/auth.py`, `backend/api/trading.py`, `backend/api/dashboard.py` |
| **Data Sources & Clients** | Polymarket, Kalshi, crypto feeds, weather | `backend/data/polymarket_clob.py`, `backend/data/kalshi_client.py`, `backend/data/crypto.py` |
| **Notifications & Bot** | Telegram, Discord, alert routing | `backend/bot/telegram_bot.py`, `backend/bot/notification_router.py` |
| **Cache, Queue & Scheduling** | Redis/SQLite queue, scheduler, workers | `backend/job_queue/redis_queue.py`, `backend/job_queue/sqlite_queue.py` |
| **Configuration** | Settings, feature flags, risk profiles | `backend/config.py`, `backend/config_extensions.py`, `backend/config_hft.py` |
| **Frontend Core** | App entry, routing, API client, auth | `frontend/src/App.tsx`, `frontend/src/api.ts` |
| **Frontend Pages & Components** | Dashboard, admin, trading views | `frontend/src/pages/`, `frontend/src/components/` |
| **Frontend Infrastructure** | Vite, Tailwind, TypeScript config | `frontend/vite.config.ts`, `frontend/tailwind.config.js` |

---

## Key Concepts

### Trading Modes

| Mode | Description | Circuit Breakers |
|------|-------------|-----------------|
| **Shadow** | Observe-only, no DB trades, in-memory `ShadowTrade` objects | N/A (never reaches `validate_trade`) |
| **Paper** | Simulated trading with virtual bankroll | **Disabled** — runs infinitely for backtesting |
| **Testnet** | Test network with real execution | Enabled |
| **Live** | Real money trading | Enabled |

### Circuit Breaker System

Per-mode breaker toggles in `config.py`:

```python
DRAWDOWN_BREAKER_ENABLED_PER_MODE = {"paper": False, "testnet": True, "live": True}
DAILY_LOSS_LIMIT_ENABLED_PER_MODE = {"paper": False, "testnet": True, "live": True}
```

Key method: `RiskManager._breaker_enabled_for_mode(breaker, mode)` — checks config before enforcing.

### Signal Flow

1. **Data Ingestion** → Market data from CLOB, Kalshi, crypto exchanges, weather APIs
2. **AI Analysis** → Claude/Groq generate signals with confidence scores
3. **Debate Engine** → Bull/Bear/Judge RA-CR protocol validates signals
4. **Risk Gates** → `validate_trade()` checks edge, confidence, position limits, circuit breakers
5. **Execution** → Order executor places trades via CLOB SDK or Kalshi API
6. **Settlement** → `settlement.py` reconciles positions, calculates P&L, updates DB

### AGI Autonomy Pipeline

Experiments flow through stages: **DRAFT → SHADOW → PAPER → LIVE_TRIAL → LIVE_PROMOTED** (with demotion loop back to PAPER)

- `autonomous_promoter.py` — Auto-promotes experiments through stages with health checks and automatic retirement
- `agi_health_check.py` — Validates strategy health before promotion; auto-kills strategies with <30% win rate after sufficient trades
- `agi_goal_engine.py` — Maps market regimes to trading goals
- `auto_improve.py` — Refines strategy parameters based on feedback; per-strategy rollback dict with independent rollback windows
- `strategy_synthesizer.py` — LLM-powered strategy synthesis with 4-gate validation (syntax → lint → backtest → sandbox); only validated strategies enter SHADOW
- `genome_compiler.py` — Runtime translation of `StrategyGenome` into executable `BaseStrategy` subclass
- `genome_strategy.py` — Genome strategy template executing chromosome-mapped entry/exit/risk/execution logic
- `evolution_jobs.py` — `shadow_validation_job` (canonical shadow-trade feedback loop: recalculates per-genome fitness from settled `ShadowTrade`, syncs `GenomePerformance`, promotes SHADOW→PAPER and PAPER→LIVE_TRIAL by metric gates, auto-kills terminal performers to GRAVEYARD)
- `agi_jobs.py` — AGI scheduled jobs including `model_calibration_check_job` (Brier drift → retrain trigger)
- `fronttest_validator.py` — Paper-trial gate; crazy-tier strategies skip 14-day minimum via `_get_strategy_risk_tier()`
- `trade_forensics.py` — Per-loss root cause diagnosis and pattern aggregation
- `forensics_integration.py` — Forensics→improvement pipeline; broken strategies get parameter overhaul; `_has_active_experiment()` excludes RETIRED

See `docs/architecture/adr-006-agi-autonomy-framework.md` for the full AGI autonomy governance specification.

---

## Guided Tour

### Step 1: Project Overview
Read the README and architecture docs:
- `README.md` — Project overview, quick start, feature list
- `ARCHITECTURE.md` — High-level system architecture
- `docs/SYSTEM_FLOW.md` — Comprehensive system flow with 22 Mermaid diagrams

### Step 2: Application Entry Point
- `main.py` — Starts FastAPI server and background workers
- `run.py` — Alternate entry with environment validation
- `backend/__main__.py` — Python module entry point

### Step 3: Configuration & Settings
- `backend/config.py` — All settings, feature flags, per-mode breaker toggles
- `backend/config_extensions.py` — Extended configuration with AI, AGI, and risk feature flags
- `backend/config_hft.py` — HFT-specific parameters
- `.env.example` — Required environment variables

### Step 4: Core Trading Engine
- `backend/core/orchestrator.py` — Top-level coordinator — wires CLOB, Telegram, scheduler, strategies
- `backend/core/risk_manager.py` — Trade validation, circuit breakers, position limits, Kelly sizing
- `backend/core/settlement.py` — Position reconciliation, P&L calculation, blockchain verification
- `backend/core/auto_trader.py` — Pending trade approval and execution pipeline

### Step 5: AI Ensemble & Signal Generation
- `backend/ai/claude.py` — Deep signal analysis via Anthropic Claude
- `backend/ai/groq.py` — Fast market classification via Groq
- `backend/ai/debate_engine.py` — Multi-agent Bull/Bear/Judge debate system
- `backend/ai/signal_parser.py` — Parses AI output into structured signals
- `backend/ai/mirofish_client.py` — External dual-debate system with fallback

### Step 6: Trading Strategies
- `backend/strategies/btc_momentum.py` — RSI + momentum + VWAP on 1m/5m/15m candles
- `backend/strategies/weather_emos.py` — 31-member GFS ensemble temperature forecasting
- `backend/strategies/copy_trader.py` — Mirrors top whale positions from Polymarket leaderboard

### Step 7: API & WebSocket Layer
- `backend/api/auth.py` — Cookie + Bearer authentication, CSRF protection
- `backend/api/trading.py` — Trade submission and approval endpoints
- `backend/api/dashboard.py` — Real-time dashboard data aggregation

### Step 8: Data Sources
- `backend/data/polymarket_clob.py` — Polymarket CLOB SDK for order execution
- `backend/data/kalshi_client.py` — Kalshi REST API with RSA-PSS auth
- `backend/data/crypto.py` — Coinbase/Binance price feeds

### Step 9: Database & Models
- `backend/models/database.py` — SQLAlchemy ORM models (Trade, BotState, Signal, etc.)
- `alembic/versions/` — Schema migration history

### Step 10: AGI Autonomy & Evolution
- `backend/core/autonomous_promoter.py` — Experiment lifecycle management (DRAFT→SHADOW→PAPER→LIVE_TRIAL→LIVE_PROMOTED) with demotion loop
- `backend/core/strategy_synthesizer.py` — LLM-powered strategy synthesis with 4-gate validation (syntax → lint → backtest → sandbox)
- `backend/application/strategy/genome_compiler.py` — Runtime translation of `StrategyGenome` into executable `BaseStrategy` subclass
- `backend/application/strategy/genome_strategy.py` — Genome strategy template executing chromosome-mapped entry/exit/risk/execution logic
- `backend/application/agi/evolution_jobs.py` — `shadow_validation_job` (shadow-trade fitness feedback loop, stage gates, GRAVEYARD auto-kill)
- `backend/core/agi_jobs.py` — AGI scheduled jobs including `model_calibration_check_job` (Brier drift → retrain trigger)
- `backend/core/agi_goal_engine.py` — Market regime → trading goal mapping
- `backend/core/auto_improve.py` — Strategy parameter refinement with per-strategy rollback
- `backend/core/fronttest_validator.py` — Paper-trial gate with risk-tier-aware minimum duration
- `backend/core/trade_forensics.py` — Post-loss analysis, root cause diagnosis
- `backend/core/forensics_integration.py` — Forensics→improvement pipeline with parameter overhaul
- `backend/models/genome_registry.py` — ORM models for genome persistence (GenomeRegistry, GenomePerformance, GenomeShadowTrade)
- `backend/repositories/genome_repository.py` — Repository layer for genome CRUD operations
- `docs/architecture/adr-006-agi-autonomy-framework.md` — Full AGI autonomy governance specification

### Step 11: Risk Management & Circuit Breakers
- `backend/core/risk_manager.py` — Per-mode breaker toggles, position limits, concentration guards
- `backend/core/risk_profiles.py` — 4 presets (safe/normal/aggressive/extreme), `apply_profile()`
- `backend/core/trade_forensics.py` — Post-loss analysis, root cause diagnosis

### Step 12: Frontend Dashboard
- `frontend/src/App.tsx` — Main app with routing and layout
- `frontend/src/api.ts` — API client with admin interceptor and CSRF
- `frontend/src/utils/auth.ts` — Cookie-based auth utilities
- `frontend/src/polling.ts` — Configurable polling intervals

### Step 13: Infrastructure & Deployment
- `Dockerfile` + `docker-compose.yml` — Multi-service container setup
- `railway.json` — Railway.app backend deployment
- `frontend/vercel.json` — Vercel frontend deployment
- `ecosystem.config.js` — PM2 process manager config

---

## File Map

### Backend Core Files (most important)

| File | Lines | Complexity | Purpose |
|------|-------|-----------|---------|
| `backend/core/orchestrator.py` | ~400 | Complex | Top-level strategy coordinator |
| `backend/core/risk_manager.py` | ~350 | Complex | Trade validation, circuit breakers |
| `backend/core/settlement.py` | ~500 | Complex | Position reconciliation |
| `backend/api/system.py` | ~2078 | Very Complex | Admin dashboard, bulk operations |
| `backend/api/auth.py` | ~716 | Very Complex | Cookie + Bearer auth, CSRF |
| `backend/api/settings.py` | ~892 | Very Complex | Settings CRUD, dynamic config |
| `backend/ai/debate_engine.py` | ~622 | Very Complex | Multi-agent RA-CR debate |
| `backend/ai/proposal_generator.py` | ~741 | Very Complex | Strategy improvement proposals |
| `backend/ai/self_review.py` | ~591 | Very Complex | Attribution engine, postmortems |

### Frontend Key Files

| File | Purpose |
|------|---------|
| `frontend/src/App.tsx` | Main routing and layout |
| `frontend/src/api.ts` | API client with admin interceptor |
| `frontend/src/pages/DashboardPage.tsx` | Main dashboard view |
| `frontend/src/components/EquityChart.tsx` | P&L chart component |
| `frontend/src/components/BrainGraph.tsx` | AI decision flow visualization |

---

## Complexity Hotspots ⚠️

Areas new developers should approach carefully:

| File | Why |
|------|-----|
| `backend/api/system.py` | 2078 lines — monolithic admin API, many concerns mixed |
| `backend/api/settings.py` | 892 lines — dynamic config with Pydantic model rebuilding |
| `backend/api/auth.py` | 716 lines — dual auth (cookie + Bearer), CSRF, session management |
| `backend/api/backtest.py` | 618 lines — complex backtesting API with multiple strategies |
| `backend/ai/proposal_generator.py` | 741 lines — strategy improvement generation with impact analysis |
| `backend/core/orchestrator.py` | ~400 lines — wires everything together, high coupling |
| `backend/core/settlement.py` | ~500 lines — money-handling logic, requires extreme care |
| `backend/data/polymarket_clob.py` | ~800+ lines — CLOB SDK integration with order signing |
| `backend/strategies/weather_emos.py` | Very Complex — 31-member ensemble with EMOS calibration |
| `backend/strategies/general_market_scanner.py` | Very Complex — scans all markets with AI analysis |

---

## Testing

```bash
# Backend tests
pytest                                    # All tests
pytest backend/tests/test_risk_manager.py # Risk manager only
pytest backend/tests/test_debate_engine.py # AI debate only
pytest tests/                              # Integration tests

# Frontend tests
cd frontend && npm test                    # Unit tests
cd frontend && npx playwright test          # E2E tests

# Important: Never run live trading tests without SHADOW_MODE=true
```

---

## Common Patterns

### Adding a New Strategy

1. Create `backend/strategies/my_strategy.py` extending `BaseStrategy`
2. Register in `backend/config.py` strategy registry
3. Add strategy settings to `Settings` class
4. Add tests in `backend/tests/test_my_strategy.py`
5. Update `docs/` documentation

### Adding a New API Endpoint

1. Create `backend/api/my_endpoint.py` with FastAPI router
2. Register in `backend/api/main.py` app include
3. Add auth dependency with `Depends(get_current_user)`
4. Add rate limiting if needed
5. Add frontend API client in `frontend/src/api.ts`

### Modifying Risk Rules

1. Edit `backend/config.py` — per-mode breaker toggles
2. Edit `backend/core/risk_manager.py` — `validate_trade()` method
3. Add tests in `backend/tests/test_risk_manager.py`
4. Update `IMPLEMENTATION_GAPS.md` if gap is resolved

---

## Key Documentation

| Document | Location |
|----------|----------|
| Architecture Overview | `ARCHITECTURE.md` |
| System Flow (22 diagrams) | `docs/SYSTEM_FLOW.md` |
| API Reference | `docs/api.md` |
| Polymarket Setup Guide | `POLYMARKET_SETUP.md` |
| Implementation Gaps Tracker | `IMPLEMENTATION_GAPS.md` |
| How It Works | `docs/how-it-works.md` |
| MiroFish Integration | `docs/mirofish-integration.md` |
| ADR: Job Queue | `docs/architecture/adr-001-job-queue.md` |
| ADR: Live Equity Source | `docs/architecture/adr-002-live-equity-source.md` |
| ADR: Trade Attempt Observability | `docs/architecture/adr-003-trade-attempt-observability.md` |
| ADR: Bounded Autonomous Sizing | `docs/architecture/adr-004-bounded-autonomous-sizing.md` |
| ADR: AGI Autonomy Framework | `docs/architecture/adr-006-agi-autonomy-framework.md` |

---

## Environment Variables

Key variables (see `.env.example` for full list):

| Variable | Purpose | Default |
|----------|---------|---------|
| `SHADOW_MODE` | Observe-only mode (no trades) | `false` |
| `JOB_WORKER_ENABLED` | Enable background job processing | `true` |
| `AGI_AUTO_PROMOTE` | Auto-promote experiments through stages | `false` |
| `AGI_AUTO_ENABLE` | Auto-enable promoted strategies | `false` |
| `AGI_STRATEGY_HEALTH_ENABLED` | Enable health-based strategy checks | `false` |
| `AGI_BANKROLL_ALLOCATION_ENABLED` | Enable daily bankroll rebalancing | `false` |
| `DRAWDOWN_BREAKER_ENABLED_PER_MODE` | Per-mode drawdown breaker | `{"paper": false, "testnet": true, "live": true}` |
| `DAILY_LOSS_LIMIT_ENABLED_PER_MODE` | Per-mode daily loss limit | `{"paper": false, "testnet": true, "live": true}` |
| `CLOB_API_URL` | Polymarket CLOB endpoint | `https://clob.polymarket.com` |
| `DATA_API_URL` | Polymarket Data API endpoint | `https://data-api.polymarket.com` |
| `GAMMA_API_URL` | Polymarket Gamma API endpoint | `https://gamma-api.polymarket.com` |

---

*Generated from knowledge graph with 3,356 nodes, 4,518 edges across 1,053 files. Interactive visualization available via `/understand-dashboard`.*