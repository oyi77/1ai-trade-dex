# PolyEdge — Prediction Market Trading Bot

A full-stack automated prediction market trading bot targeting **Polymarket** and **Kalshi**. Combines AI-powered signal generation, 12 trading strategies with bounded AGI autonomy, evolutionary strategy composition, real-time market data aggregation, and a React dashboard for monitoring and control.

[![Research DOI](https://zenodo-badge.example.com/10.5281/zenodo.16966978.svg)](https://doi.org/10.5281/zenodo.16966978)

![Python](https://img.shields.io/badge/python-3.10+-blue) ![React](https://img.shields.io/badge/react-18+-61DAFB) ![TypeScript](https://img.shields.io/badge/typescript-5.0+-blue) ![License](https://img.shields.io/badge/license-MIT-green)

![Dashboard](docs/dashboard.png)

## Overview

### Trading Strategies (12 registered + AGI Orchestrator)

| Strategy | Description |
|----------|-------------|
| **AGI Meta Strategy** | Autonomous strategy composition with evolution |
| **BTC Momentum** | RSI + momentum + VWAP on 1m/5m/15m candles from Coinbase/Kraken/Binance |
| **BTC Oracle** | CoinGecko latency arbitrage on BTC price markets |
| **Bond Scanner** | Fixed-income prediction market opportunities |
| **CEX-PM Lead-Lag** | CEX price lead-lag signal for Polymarket markets |
| **Copy Trader** | Mirrors top whale trader positions from Polymarket leaderboard |
| **Cross Market Arb** | Cross-market arbitrage execution |
| **General Market Scanner** | General market scanning and opportunity detection |
| **Line Movement** | Betting line movement detection |
| **Market Maker** | Spread quoting with real-time inventory tracking |
| **Probability Arb** | Cross-market probability arbitrage detection |
| **Realtime Scanner** | Price velocity and momentum signal detection |
| **Universal Scanner** | Universal market scanning and opportunity detection |
| **AGI Orchestrator** | Meta-strategy composing and evolving other strategies autonomously |

### Key Features

- **Multi-Strategy Engine** — 12 strategies running in parallel with per-strategy risk isolation
- **Bounded AGI Autonomy** — Autonomous promotion pipeline (DRAFT→SHADOW→PAPER→LIVE) with deterministic safety gates
- **Evolutionary Composition** — AGI meta-strategy composes, mutates, and evolves trading strategies from a genome grammar; GenomeCompiler translates genomes into executable strategies at runtime; GenomeRegistry persists genome lineage, performance, and shadow trades
- **Shadow-Validation Fitness Feedback** — Shadow trades are settled against real market outcomes; per-genome fitness (win rate, Sharpe, drawdown) is recalculated from settled ShadowTrades, driving promotion and kill decisions
- **Evolution Scheduler** — Periodic cycles run mutation, crossover, fitness refresh, and diversity rebalance on the genome population; underperformers are auto-killed to GRAVEYARD
- **Genome Registry & Compiler** — `GenomeRegistry` ORM models persist genome lineage and performance; `GenomeCompiler` translates `StrategyGenome` chromosomes into executable `BaseStrategy` subclasses at runtime
- **MiroFish Dual-Debate** — External debate system validates trade decisions with automatic fallback to local engine
- **AI Ensemble** — Claude + Groq LLM providers for sentiment analysis and signal synthesis
- **Multi-Platform Trading** — Polymarket (CLOB SDK) and Kalshi (REST API) simultaneously
- **Edge Detection** — Identifies mispriced markets with configurable edge thresholds
- **Kelly Criterion Sizing** — Fractional Kelly position sizing with per-trade and portfolio caps
- **Signal Calibration** — Brier score tracking for prediction accuracy over time
- **Risk Management** — Circuit breakers, position limits, portfolio concentration guards
- **Shadow Mode** — Paper trading with virtual bankroll and equity curve tracking
- **Unified State Sync** — Automatic blockchain reconciliation imports external trades and verifies settlements
- **Trade Forensics** — Per-loss diagnosis and pattern analysis for continuous improvement
- **Professional Dashboard** — React + TypeScript + TanStack Query with real-time updates
- **Job Queue** — Redis-backed (falls back to SQLite) for background strategy execution
- **Monitoring** — Prometheus metrics endpoint with request/response middleware

### AGI Autonomy

PolyEdge implements a bounded AGI autonomy framework with deterministic safety gates:

- **Autonomous Promotion Pipeline** (`backend/core/autonomous_promoter.py`) — Auto-promotes experiments through DRAFT→SHADOW→PAPER→LIVE lifecycle stages with health checks and automatic retirement of killed strategies
- **Evolutionary Strategy Composition** (`backend/strategies/agi_meta_strategy.py`) — AGI meta-strategy composes and evolves trading strategies from a formal genome grammar with crossover and mutation
- **Shadow-Validation Fitness Loop** (`backend/application/agi/evolution_jobs.py`) — Recalculates per-genome fitness from settled ShadowTrades; promotes SHADOW→PAPER and PAPER→LIVE by metric gates; auto-kills terminal performers to GRAVEYARD
- **Evolution Scheduler** (`backend/application/agi/evolution_jobs.py`) — Periodic mutation, crossover, fitness refresh, and diversity rebalance cycles on the genome population
- **Genome Registry & Compiler** (`backend/models/genome_registry.py`, `backend/application/strategy/genome_compiler.py`) — ORM persistence for genome lineage/performance/shadow-trades; runtime compilation of `StrategyGenome` chromosomes into executable `BaseStrategy` subclasses
- **Bankroll Allocation** (`backend/core/bankroll_allocator.py`) — Daily capital allocation via StrategyRanker with health-weighted distribution
- **Trade Forensics** (`backend/core/trade_forensics.py`) — Per-loss root cause diagnosis and pattern aggregation for continuous improvement
- **MiroFish Dual-Debate** — External debate system validates every trade decision; automatic fallback to local debate engine when unavailable

Controlled via feature flags: `AGI_AUTO_PROMOTE`, `AGI_AUTO_ENABLE`, `AGI_STRATEGY_HEALTH_ENABLED`, `AGI_BANKROLL_ALLOCATION_ENABLED`

## Quick Start

### 1. Backend Setup

```bash
# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Copy environment template and configure
cp .env.example .env
# Edit .env with your API keys (see docs/configuration.md)

# Run the backend
uvicorn backend.api.main:app --reload --port 8100
```

Backend will be at: http://localhost:8100
API docs at: http://localhost:8100/docs

### 2. Frontend Setup

```bash
cd frontend

# Install dependencies
npm install

# Run the frontend
npm run dev
```

Frontend will be at: http://localhost:5173

### 3. Docker (Alternative)

```bash
docker-compose up -d
```

Starts the backend API + Redis. See `docker-compose.yml` for configuration.

## Architecture

```
┌──────────────────────────────────────────────────────────────────────┐
│                           FRONTEND                                    │
│  React 18 + TypeScript + TanStack Query + Tailwind + Vite            │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌───────────┐  │
│  │Dashboard │ │ Admin    │ │ Signals  │ │  Trades  │ │ GlobeView │  │
│  │Overview  │ │ Controls │ │  Table   │ │  Table   │ │  (3D Map) │  │
│  └──────────┘ └──────────┘ └──────────┘ └──────────┘ └───────────┘  │
└──────────────────────────────────────────────────────────────────────┘
                               │ REST API
                               ▼
┌──────────────────────────────────────────────────────────────────────┐
│                 AGI AUTONOMY LAYER                                    │
│  ┌───────────────┐ ┌──────────────┐ ┌────────────────┐ ┌───────────┐ │
│  │ Autonomous     │ │  Bankroll    │ │  Trade        │ │ Evolution  │ │
│  │ Promoter       │ │  Allocator   │ │  Forensics    │ │ Scheduler  │ │
│  │ DRAFT→SHADOW   │ │  StrategyRkr │ │  Root Cause   │ │ Mutation   │ │
│  │ →PAPER→LIVE    │ │  Daily Alloc  │ │  Diagnosis    │ │ Crossover  │ │
│  └───────────────┘ └──────────────┘ └────────────────┘ │ Fitness    │ │
│  ┌───────────────┐ ┌──────────────┐                    │ Rebalance  │ │
│  │ Genome         │ │ Shadow-      │                    └───────────┘ │
│  │ Registry &     │ │ Validation   │                                  │
│  │ Compiler       │ │ Fitness Loop │                                  │
│  └───────────────┘ └──────────────┘                                  │
│  ┌───────────────────────────────────────────────────────────────────┐│
│  │ MiroFish Dual-Debate │ Deterministic Safety Gates │ Health Checks ││
│  └───────────────────────────────────────────────────────────────────┘│
└──────────────────────────────────────────────────────────────────────┘
                               │
                               ▼
┌──────────────────────────────────────────────────────────────────────┐
│                    BACKEND (FastAPI + Python)                         │
│  ┌───────────┐ ┌───────────┐ ┌───────────┐ ┌───────────────────────┐ │
│  │Orchestrator│ │ 14 Trading│ │   Risk    │ │ AI Ensemble           │ │
│  │           │ │ Strategies │ │  Manager  │ │ (Claude + Groq)       │ │
│  └───────────┘ └───────────┘ └───────────┘ └───────────────────────┘ │
│  ┌───────────┐ ┌───────────┐ ┌───────────┐ ┌───────────────────────┐ │
│  │  Order    │ │Settlement │ │  Signal   │ │ Job Queue             │ │
│  │ Executor  │ │  Engine   │ │Calibration│ │ (Redis / PostgreSQL)      │ │
│  └───────────┘ └───────────┘ └───────────┘ └───────────────────────┘ │
└──────────────────────────────────────────────────────────────────────┘
                               │
                               ▼
┌──────────────────────────────────────────────────────────────────────┐
│                        DATA SOURCES                                   │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌────────────┐ │
│  │Polymarket│ │ Kalshi   │ │Coinbase/ │ │Open-Meteo│ │  NWS API   │ │
│  │CLOB SDK  │ │REST API  │ │Kraken/   │ │GFS       │ │            │ │
│  │+ WebSocket│ │         │ │Binance   │ │Ensemble  │ │            │ │
│  └──────────┘ └──────────┘ └──────────┘ └──────────┘ └────────────┘ │
└──────────────────────────────────────────────────────────────────────┘
                               │
                               ▼
┌──────────────────────────────────────────────────────────────────────┐
│  INFRASTRUCTURE: PostgreSQL DB │ Redis Queue │ APScheduler │ Prometheus  │
│  DEPLOY: Docker Compose │ Railway (backend) │ Vercel (frontend)     │
│  NOTIFY: Telegram │ Discord                                          │
└──────────────────────────────────────────────────────────────────────┘
```

## Research

A 33-page peer-reviewed research paper documenting the bounded AGI autonomy framework, evolutionary strategy composition, and dual-debate validation system is available:

- **Paper**: [`docs/paper/paper.pdf`](docs/paper/paper.pdf) — 33 pages, 15 references, 7,361 words
- **Supplementary Materials**: [`docs/paper/supplementary/supplementary.pdf`](docs/paper/supplementary/supplementary.pdf) — 8 pages of proofs, genome grammar, extended data, and code listings
- **Abstract Video**: [`docs/paper/supplementary_video.mp4`](docs/paper/supplementary_video.mp4) — 50-second 1080p H.264 overview
- **Pitch Deck**: [`docs/pitchdeck/`](docs/pitchdeck/) — 10-slide interactive HTML + PDF presentation
- **Documentation Site**: [polyedge.aitradepulse.com/docs/](https://polyedge.aitradepulse.com/docs/)
- **DOI**: [10.5281/zenodo.16966978](https://doi.org/10.5281/zenodo.16966978)

## Documentation

- **[User Guide](docs/user-guide.md)** - Beginner-friendly dashboard walkthrough
- **[How It Works](docs/how-it-works.md)** - Detailed explanation of BTC and weather strategies
- **[MiroFish Integration](docs/mirofish-integration.md)** - External debate system setup and API reference
- **[API Reference](docs/api.md)** - Complete API endpoint documentation
- **[Configuration](docs/configuration.md)** - All settings and environment variables
- **[Data Sources](docs/data-sources.md)** - Description of all data providers
- **[Project Structure](docs/project-structure.md)** - Codebase organization
- **[Job Queue Architecture](docs/architecture/adr-001-job-queue.md)** - Phase 1/2 queue design
- **[AGI Autonomy Framework](docs/architecture/adr-006-agi-autonomy-framework.md)** - Promotion gates, safety boundaries, human-in-the-loop override

## License

MIT - do whatever you want with it.
