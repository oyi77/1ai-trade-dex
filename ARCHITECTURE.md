# PolyEdge Architecture

## Overview

PolyEdge is a full-stack automated prediction market trading bot targeting **Polymarket** and **Kalshi**. It combines AI-powered signal generation, multi-strategy execution, real-time market data aggregation, and a React dashboard for monitoring and control.

The system supports paper trading (shadow mode), live trading with risk controls, and comprehensive backtesting.

---

## System Architecture

```
┌──────────────────────────────────────────────────────────────────────┐
│                           FRONTEND                                    │
│  React 18 + TypeScript + Vite + TanStack Query + Tailwind            │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌───────────┐  │
│  │Dashboard │ │ Admin    │ │ Signals  │ │  Trades  │ │ GlobeView │  │
│  │Overview  │ │ Controls │ │  Table   │ │  Table   │ │  (3D Map) │  │
│  └──────────┘ └──────────┘ └──────────┘ └──────────┘ └───────────┘  │
└──────────────────────────────────────────────────────────────────────┘
                               │ REST API (polling via TanStack Query)
                               ▼
┌──────────────────────────────────────────────────────────────────────┐
│ API LAYER (FastAPI)                           │
│  backend/api/main.py — Lifespan-managed, CORS, Prometheus metrics    │
│  189 routes: /api/v1/{signals,trades,strategies,risk,admin,...}      │
└─────────────────────────────────────────────────────────────────────┘
                               │
          ┌────────────────────┼────────────────────┐
          ▼                    ▼                    ▼
┌──────────────┐    ┌──────────────────┐    ┌──────────────┐
│  ORCHESTRATOR │    │  STRATEGY ENGINE  │    │  RISK MANAGER │
│  core/        │    │  strategies/      │    │  core/        │
│  orchestrator │    │  strategy_executor│    │  risk_manager │
│  .py          │    │  .py              │    │  .py          │
└──────┬───────┘    └────────┬─────────┘    └──────┬───────┘
       │                     │                      │
       ▼                     ▼                      ▼
┌──────────────────────────────────────────────────────────────────────┐
│                      STRATEGY MODULES                                 │
│  ┌────────────┐ ┌────────────┐ ┌────────────┐ ┌────────────────────┐ │
│  │BTC Momentum│ │Weather EMOS│ │Copy Trader │ │Market Maker        │ │
│  │btc_momentum│ │weather_emos│ │copy_trader │ │market_maker        │ │
│  └────────────┘ └────────────┘ └────────────┘ └────────────────────┘ │
│  ┌────────────┐ ┌────────────┐ ┌────────────┐ ┌────────────────────┐ │
│  │BTC Oracle  │ │Kalshi Arb  │ │Bond Scanner│ │Whale PNL Tracker   │ │
│  │btc_oracle  │ │kalshi_arb  │ │bond_scanner│ │whale_pnl_tracker   │ │
│  └────────────┘ └────────────┘ └────────────┘ └────────────────────┘ │
│  ┌────────────────────────┐                                          │
│  │Realtime Scanner        │                                          │
│  │realtime_scanner        │                                          │
│  └────────────────────────┘                                          │
└──────────────────────────────────────────────────────────────────────┘
       │                     │                      │
       ▼                     ▼                      ▼
┌──────────────────────────────────────────────────────────────────────┐
│                      AI / SIGNAL LAYER                                │
│  ai/ensemble.py — Multi-provider AI ensemble (Claude, Groq, Custom)  │
│  ai/sentiment_analyzer.py — Market sentiment via LLM                 │
│  ai/bayesian_optimizer.py — Parameter optimization                   │
│  core/signals.py, base_signals.py — Signal generation pipeline       │
└──────────────────────────────────────────────────────────────────────┘
│                     │                      │
        ▼                     ▼                      ▼
┌──────────────────────────────────────────────────────────────────────┐
│                    AGI INTELLIGENCE LAYER                              │
│  ┌─────────────────┐ ┌─────────────────┐ ┌──────────────────────┐  │
│  │RegimeDetector    │ │KnowledgeGraph    │ │StrategyComposer      │  │
│  │(regime_detector) │ │(knowledge_graph) │ │(strategy_composer)   │  │
│  │Bull/Bear/Side/   │ │Entity-Relation   │ │Block-based strategy  │  │
│  │Volatile+Hysteresis│ │memory+rollback   │ │composition           │  │
│  └─────────────────┘ └─────────────────┘ └──────────────────────┘  │
│  ┌─────────────────┐ ┌─────────────────┐ ┌──────────────────────┐  │
│  │AGIGoalEngine     │ │DynamicPrompt    │ │SelfDebugger          │  │
│  │(agi_goal_engine) │ │Engine           │ │(self_debugger)        │  │
│  │Regime-aware      │ │(dynamic_prompt_  │ │API failure diagnosis  │  │
│  │objective switch  │ │ engine)          │ │& recovery             │  │
│  └─────────────────┘ └─────────────────┘ └──────────────────────┘  │
│  ┌─────────────────┐ ┌─────────────────┐ ┌──────────────────────┐  │
│  │RegimeAware      │ │GenomeCompiler   │ │EvolutionScheduler    │  │
│  │Allocator         │ │(genome_compiler)│ │(evolution_jobs)      │  │
│  │(strategy_alloc.) │ │Runtime genome→  │ │Shadow validation,    │  │
│  │Capital allocation │ │strategy compile │ │mutation/crossover,   │  │
│  └─────────────────┘ └─────────────────┘ │fitness feedback,      │  │
│                                        │ │diversity rebalance    │  │
│                                        └──────────────────────┘  │
└──────────────────────────────────────────────────────────────────────┘
        │                     │                      │
        ▼                     ▼                      ▼
┌──────────────────────────────────────────────────────────────────────┐
│                       DATA LAYER                                      │
│  ┌────────────┐ ┌────────────┐ ┌────────────┐ ┌────────────────────┐ │
│  │Polymarket  │ │Kalshi      │ │Crypto      │ │Weather             │ │
│  │CLOB Client │ │Client      │ │(Coinbase/  │ │(Open-Meteo GFS     │ │
│  │+ WebSocket │ │            │ │Kraken/     │ │ ensemble + NWS)    │ │
│  │(py-clob-   │ │(kalshi_    │ │Binance)    │ │                    │ │
│  │ client)    │ │ client.py) │ │(crypto.py) │ │(weather.py)        │ │
│  └────────────┘ └────────────┘ └────────────┘ └────────────────────┘ │
└──────────────────────────────────────────────────────────────────────┘
       │                     │                      │
       ▼                     ▼                      ▼
┌──────────────────────────────────────────────────────────────────────┐
│                   STORAGE / QUEUE / MONITORING                        │
│  ┌─────────┐  ┌──────────┐  ┌───────────┐  ┌──────────────────────┐ │
│  │ SQLite  │  │Redis Queue│  │APScheduler│  │Prometheus Metrics    │ │
│  │(primary)│  │(optional, │  │(cron jobs, │  │(monitoring/         │ │
│  │         │  │ falls back│  │ recurring  │  │ middleware.py)      │ │
│  │         │  │ to SQLite)│  │ scans)     │  │                    │ │
│  └─────────┘  └──────────┘  └───────────┘  └──────────────────────┘ │
└──────────────────────────────────────────────────────────────────────┘
       │
       ▼
┌──────────────────────────────────────────────────────────────────────┐
│                     NOTIFICATIONS                                     │
│  bot/notification_router.py → Telegram, Discord (email de-scoped)    │
└──────────────────────────────────────────────────────────────────────┘
```

---

## Directory Structure

```
polyedge/
├── main.py                    # Entry point — starts FastAPI + background workers
├── run.py                     # Alternate runner with env validation
├── requirements.txt           # Python dependencies
├── docker-compose.yml         # Multi-service (app + Redis)
├── Dockerfile                 # Backend container
├── ecosystem.config.js        # PM2 process manager (API + worker + scheduler)
├── railway.json               # Railway.app deployment
├── vercel.json                # Vercel frontend deployment
├── pytest.ini                 # Test runner config
├── .env.example               # Required environment variables
│
├── backend/
│   ├── api/                   # FastAPI routes and middleware
│   │   └── main.py            # App factory, lifespan, CORS, routes
│   ├── core/                  # Orchestration, risk, scheduling, signals
│   │   ├── orchestrator.py    # Central coordination of strategies
│   │   ├── bankroll_reconciliation.py # BotState financial cache reconciliation
│   │   ├── risk_manager.py    # Position limits, circuit breakers
│   │   ├── strategy_executor.py # Strategy lifecycle management
│   │   ├── settlement.py      # Trade settlement tracking
│   │   ├── calibration.py     # Brier score, signal accuracy
│   │   ├── circuit_breaker.py # Automatic trading halts
│   │   ├── scheduler.py       # APScheduler job definitions
│   │   ├── regime_detector.py # Market regime classification (bull/bear/sideways/volatile)
│   │   ├── knowledge_graph.py  # Persistent entity-relationship memory
│   │   ├── strategy_composer.py # Block-based strategy composition
│   │   ├── strategy_allocator.py # Regime-aware capital allocation
│   │   ├── dynamic_prompt_engine.py # Evolving AI prompts
│   │   ├── agi_goal_engine.py  # Regime-aware objective switching
│   │   ├── agi_orchestrator.py # Unified AGI control loop
│   │   ├── agi_types.py       # AGI data types and enums
│   │   ├── agi_jobs.py         # AGI background job definitions
│   │   ├── agi_promotion_pipeline.py # shadow→paper→live promotion
│   │   ├── self_debugger.py    # API failure diagnosis and recovery
│   │   ├── strategy_synthesizer.py # LLM-driven strategy code generation
│   │   ├── experiment_runner.py # Sandboxed strategy testing
│   │   ├── causal_reasoning.py # Why-did-X-happen analysis
│   │   └── llm_cost_tracker.py # LLM spending budget enforcement
│   ├── strategies/            # Trading strategy implementations
│   │   ├── base.py            # BaseStrategy + StrategyContext
│   │   ├── btc_momentum.py    # BTC 5-min microstructure
│   │   ├── weather_emos.py    # GFS ensemble weather
│   │   ├── copy_trader.py     # Whale copy trading
│   │   ├── market_maker.py    # Market making with inventory
│   │   ├── kalshi_arb.py      # Cross-platform arbitrage
│   │   ├── order_executor.py  # Order placement + management
│   │   └── registry.py        # Strategy registration
│   ├── ai/                    # AI signal providers
│   │   ├── ensemble.py        # Multi-provider ensemble
│   │   ├── claude.py          # Anthropic Claude provider
│   │   ├── groq.py            # Groq (Llama) provider
│   │   └── sentiment_analyzer.py
│   ├── data/                  # Market data clients
│   │   ├── polymarket_clob.py # Polymarket CLOB (py-clob-client)
│   │   ├── kalshi_client.py   # Kalshi REST API
│   │   ├── ws_client.py       # WebSocket market data
│   │   ├── crypto.py          # Coinbase/Kraken/Binance candles
│   │   └── weather.py         # Open-Meteo GFS ensemble
│   ├── bot/                   # Notifications (Telegram, Discord)
│   ├── models/                # SQLAlchemy models (Trade, Signal, etc.)
│   │   ├── database.py        # Core models (Trade, Signal, BotState, etc.)
│   │   ├── kg_models.py       # Knowledge graph models
│   │   └── genome_registry.py # Genome persistence models (GenomeRegistry, GenomePerformance, GenomeShadowTrade)
│   ├── repositories/           # Repository layer (data access)
│   │   └── genome_repository.py # Genome CRUD operations
│   ├── domain/                 # Domain logic (pure business rules)
│   │   └── evolution/
│   │       └── shadow_metrics.py # Per-genome shadow trade metrics
│   ├── application/            # Application services
│   │   ├── strategy/
│   │   │   ├── genome_compiler.py  # Runtime genome→strategy compilation
│   │   │   └── genome_strategy.py   # Genome strategy template (chromosome-mapped logic)
│   │   └── agi/
│   │       └── evolution_jobs.py    # Shadow validation, mutation/crossover, fitness feedback
│   ├── cache/                 # Response caching layer
│   ├── monitoring/            # Prometheus metrics + middleware
│   ├── queue/                 # Job queue (Redis or SQLite fallback)
│   └── tests/                 # Backend test suite (pytest)
│
├── frontend/
│   ├── src/
│   │   ├── components/        # React components
│   │   │   ├── dashboard/     # Dashboard tabs (Overview, Trades, Signals, etc.)
│   │   │   ├── admin/         # Admin tabs (Strategies, Risk, AI config, etc.)
│   │   │   ├── AGIControlPanel.tsx  # AGI emergency stop, status, goal override
│   │   │   ├── DecisionAuditLog.tsx # Paginated decision log with filters
│   │   │   ├── StrategyComposerUI.tsx # Drag-to-compose strategy blocks
│   │   │   ├── RegimeDisplay.tsx     # Regime icons, confidence gauge, history
│   │   │   ├── GlobeView.tsx         # 3D globe with city markers
│   │   │   └── ...                   # Other dashboard components
│   │   ├── pages/
│   │   │   ├── Dashboard.tsx         # Main dashboard
│   │   │   ├── Admin.tsx             # Admin panel
│   │   │   └── AGIControl.tsx        # Tabbed AGI control page
│   │   ├── api/
│   │   │   ├── api.ts                # Main API client
│   │   │   └── agi.ts                # AGI API client with typed interfaces
│   │   ├── hooks/             # TanStack Query hooks
│   │   └── test/              # Vitest unit tests
│   ├── e2e/                   # Playwright E2E tests
│   ├── vite.config.ts         # Vite build config
│   └── vitest.config.ts       # Test runner config
│
├── docs/                      # Project documentation
│   ├── how-it-works.md        # Strategy explanations
│   ├── api.md                 # API endpoint reference
│   ├── configuration.md       # Environment variables
│   ├── data-sources.md        # Data provider docs
│   ├── project-structure.md   # Codebase layout
│   └── architecture/          # ADRs (job queue, live equity source, etc.)
│
└── tests/                     # Root-level integration tests
```

---

## Core Data Flow

1. **Market Data Ingestion** — Data clients (`polymarket_clob.py`, `kalshi_client.py`, `crypto.py`, `weather.py`) fetch live market prices, orderbook depth, and external data (GFS ensemble forecasts, BTC candles)

2. **Strategy Execution** — The orchestrator triggers registered strategies on a schedule (APScheduler). Each strategy runs its signal generation logic using the latest market data.

3. **AI Signal Analysis** — For strategies that use AI, the ensemble layer queries multiple providers (Claude, Groq) and aggregates predictions with confidence scores.

4. **Risk Management** — Before any order, strategy/AI logic may propose a dynamic size, but the risk manager validates position limits, portfolio concentration, drawdown breakers, duplicate open positions, and shadow mode flags. See `docs/architecture/adr-004-bounded-autonomous-sizing.md`.

5. **Order Execution** — `order_executor.py` places orders via the Polymarket CLOB SDK or Kalshi API. Supports limit orders, market orders, and partial fills.

6. **Settlement Tracking** — `settlement.py` + `settlement_helpers.py` monitor open positions and reconcile outcomes. In live mode, settlement preserves the trade ledger and delegates financial cache updates to `bankroll_reconciliation.py`.

7. **AGI Intelligence Layer** — RegimeDetector classifies market conditions, KnowledgeGraph stores cross-session learning, AGIGoalEngine switches objectives based on regime. StrategyComposer creates new strategies from building blocks, CausalReasoner traces why trades succeeded or failed. All AGI actions are bounded by RiskManager gates and LLM cost limits.

8. **Dashboard Updates** — The React frontend polls the FastAPI backend via TanStack Query, rendering real-time signals, trades, strategy performance, risk metrics, and AGI status (regime, goals, decisions).

9. **Trade Attempt Observability** — Every standard strategy execution attempt that reaches `strategy_executor` is recorded in `TradeAttempt`, including requested size, risk-adjusted size, blocker reason, and execution outcome. The dashboard Control Room reads this ledger to explain no-trade states without rewriting historical `Trade` data.

---

## Financial State Source of Truth

`Trade` rows are the durable learning ledger and must not be deleted or reset to repair dashboard/risk cache drift. `BotState` is a derived cache.

- **Live mode**: `BotState.bankroll` and `BotState.total_pnl` are derived from external account equity: CLOB USDC cash balance plus Polymarket Data API open-position value. Local realized P&L/backfill rows are not authoritative for live equity.
- **Paper/testnet modes**: `BotState` remains ledger-derived from initial bankroll, realized P&L, and open exposure because these modes are simulated accounting environments.
- **Implementation**: `backend/core/bankroll_reconciliation.py` is the only intended writer for live financial cache fields. See `docs/architecture/adr-002-live-equity-source.md`.
- **Dashboard interpretation**: Overview separates live, paper, and testnet PnL and shows both top winners and worst losses. Positive live account-equity PnL can coexist with negative paper/testnet ledger PnL.

---

## Trading Strategies

| Strategy | Module | Description |
|----------|--------|-------------|
| BTC Momentum | `btc_momentum.py` | RSI + momentum + VWAP on 1m/5m/15m candles |
| BTC Oracle | `btc_oracle.py` | AI-assisted BTC price predictions |
| Weather EMOS | `weather_emos.py` | GFS 31-member ensemble temperature forecasting |
| Copy Trader | `copy_trader.py` | Mirrors whale trader positions |
| Market Maker | `market_maker.py` | Spread quoting with inventory management |
| Kalshi Arbitrage | `kalshi_arb.py` | Cross-platform Polymarket↔Kalshi price gaps |
| Bond Scanner | `bond_scanner.py` | Fixed-income market opportunities |
| Whale PNL Tracker | `whale_pnl_tracker.py` | Tracks top trader realized PNL |
| Realtime Scanner | `realtime_scanner.py` | Price velocity signal detection |

---

## AGI Intelligence Layer

The system includes a Level 5 TRUE-AGI intelligence layer for autonomous market analysis,
strategy composition, and self-debugging. All AGI actions operate within non-bypassable
RiskManager bounds (ADR-004, ADR-005). Live promotion requires manual approval unless
`AGI_AUTO_PROMOTE=true` (override).

### Core Modules

| Module | File | Description |
|--------|------|-------------|
| RegimeDetector | `core/regime_detector.py` | Real-time market regime classification (bull/bear/sideways/volatile) with 5% hysteresis buffer |
| KnowledgeGraph | `core/knowledge_graph.py` | Persistent entity-relationship memory with rollback and validation |
| StrategyComposer | `core/strategy_composer.py` | Block-based strategy composition from 5 building blocks (signal_source, filter, position_sizer, risk_rule, exit_rule) |
| DynamicPromptEngine | `core/dynamic_prompt_engine.py` | Evolves AI prompts based on outcome feedback to improve signal quality |
| AGIGoalEngine | `core/agi_goal_engine.py` | Regime-aware objective switching (maximize_pnl, preserve_capital, explore, reduce_risk) |
| SelfDebugger | `core/self_debugger.py` | API failure diagnosis and recovery (404, 503, timeout scenarios) |
| StrategySynthesizer | `core/strategy_synthesizer.py` | LLM-powered strategy synthesis with 4-gate validation (syntax→lint→backtest→sandbox); only validated strategies enter SHADOW |
| ExperimentRunner | `core/experiment_runner.py` | Sandboxed strategy testing (shadow/paper/live) with statistical promotion gates |
| CausalReasoner | `core/causal_reasoning.py` | Why-did-X-happen analysis tracing causation chains for trade outcomes |
| AGIOrchestrator | `core/agi_orchestrator.py` | Unified AGI control loop coordinating all modules |
| LLMCostTracker | `core/llm_cost_tracker.py` | LLM spending budget enforcement ($10/day cap, per-action limits) |
| AGIPromotionPipeline | `core/agi_promotion_pipeline.py` | shadow→paper→live promotion pipeline with manual approval gate |
| RegimeAwareAllocator | `core/strategy_allocator.py` | Regime-aware capital allocation across strategies (max 30% per strategy) |
| GenomeCompiler | `application/strategy/genome_compiler.py` | Runtime translation of StrategyGenome into executable BaseStrategy subclass |
| GenomeStrategy | `application/strategy/genome_strategy.py` | Genome strategy template — executes chromosome-mapped entry/exit/risk/execution logic at runtime |
| GenomeRegistry | `models/genome_registry.py` | ORM models for genome persistence — GenomeRegistry, GenomePerformance, GenomeShadowTrade |
| GenomeRepository | `repositories/genome_repository.py` | Repository layer — CRUD operations for genome persistence |
| EvolutionScheduler | `application/agi/evolution_jobs.py` | Shadow validation, fitness feedback, mutation/crossover, and diversity rebalance cycles |
| ShadowMetrics | `domain/evolution/shadow_metrics.py` | Per-genome shadow trade metrics (win rate, Sharpe, drawdown, fitness score) |

### Autonomous Lifecycle Daemons

These scheduler-run daemons implement the complete experiment lifecycle without human intervention:

| Daemon | File | Schedule | Role |
|--------|------|----------|------|
| **AutonomousPromoter** | `core/autonomous_promoter.py` | Every 6h (configurable) | Evaluates all experiments across DRAFT→SHADOW→PAPER→LIVE_PROMOTED→RETIRED. Applies promotion criteria. Kills underperforming strategies via health assessments. Auto-enables strategies upon promotion if `AGI_AUTO_ENABLE=true`. |
| **BankrollAllocator** | `core/bankroll_allocator.py` | Daily (configurable) | Computes capital allocation weights via `StrategyRanker.auto_allocate()`. Writes allocations to `BotState.misc_data["allocations"]` for observability. |
| **StrategyHealthMonitor** | `core/strategy_health.py` | Called on-demand by promoter & settlement | Computes health metrics (win rate, Sharpe, max drawdown, Brier score, PSI). Issues `killed` or `warned` status. Auto-disables killed strategies in `StrategyConfig`. |
| **TradeForensics** | `core/trade_forensics.py` | Called on every settlement loss | Analyzes losing trades, diagnoses root causes, aggregates pattern insights for AGI improvement loop. |
| **EvolutionScheduler** | `application/agi/evolution_jobs.py` | Configurable intervals | Runs shadow validation (recalculates per-genome fitness from settled ShadowTrades), mutation/crossover cycles, fitness refresh, and diversity rebalance. Promotes SHADOW→PAPER and PAPER→LIVE by metric gates; auto-kills terminal performers to GRAVEYARD. |

**Promotion thresholds:**
- SHADOW → PAPER: ≥100 trades, ≥7 days, ≥45% win rate, ≤25% drawdown
- PAPER → LIVE: ≥50 trades, ≥3 days, ≥50% win rate, Sharpe ≥0.5, ≤20% drawdown
- Kill thresholds (any mode): win rate <5%, OR Sharpe <−2.0 WITH drawdown >50%

**Health-based kill check runs on every cycle for all live and paper experiments.** If `assess()` returns `status="killed"`, experiment is immediately retired.

### Frontend Components

| Component | File | Description |
|-----------|------|-------------|
| AGIControlPanel | `components/AGIControlPanel.tsx` | Emergency stop, status display, goal override |
| DecisionAuditLog | `components/DecisionAuditLog.tsx` | Paginated decision log with regime/goal filters |
| StrategyComposerUI | `components/StrategyComposerUI.tsx` | Drag-to-compose strategy blocks interface |
| RegimeDisplay | `components/RegimeDisplay.tsx` | Regime icons, confidence gauge, goal status card, history timeline |
| AGIControl | `pages/AGIControl.tsx` | Tabbed AGI page with NavLink routing |
| AGI API | `api/agi.ts` | Typed API client for AGI endpoints |

### Safety Guardrails

- **SHADOW mode enforced**: All AGI-generated strategies start in shadow mode (`ACTIVE_MODES="paper"`)
- **RiskManager gates non-bypassable**: Even AGI-generated strategies must validate through risk gates (ADR-004, ADR-005)
- **Manual promotion gate**: Live trading requires explicit human approval (ADR-006)
- **LLM budget caps**: Hard $10/day limit on LLM spending for autonomous strategy generation
- **Experiment isolation**: Sandboxed strategies cannot touch production DB or wallet
- **Knowledge graph rollback**: Bad data can be rolled back without corrupting decisions

---

## Infrastructure

- **Database**: SQLite (primary), PostgreSQL-ready via SQLAlchemy ORM
- **Job Queue**: Redis (preferred) with automatic SQLite fallback
- **Scheduler**: APScheduler for recurring market scans and settlement checks
- **Caching**: In-memory + optional Redis for API response caching
- **Monitoring**: Prometheus metrics endpoint (`/metrics`) with request/response middleware

---

## Deployment

- **Docker**: `docker-compose.yml` runs app + Redis containers
- **Railway**: Backend deploys via `railway.json` (auto-detected Python buildpack)
- **Vercel**: Frontend deploys via `vercel.json` (Vite static build)
- **PM2**: `ecosystem.config.js` manages API server, queue worker, and scheduler processes
- **CI**: GitHub Actions (`.github/`) runs tests on push

---

## Key Configuration

All configuration via environment variables (see `.env.example`):

- `TRADING_MODE` — `paper` (default) or `live`
- `SHADOW_MODE` — `true` to log signals without executing trades
- `AI_PROVIDER` — `groq`, `claude`, or `omniroute`
- `JOB_WORKER_ENABLED` — Enable background job processing
- `REDIS_URL` — Optional; falls back to SQLite queue if absent
- Feature flags for individual strategies and data sources
