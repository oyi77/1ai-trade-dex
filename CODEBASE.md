# CODEBASE.md — PolyEdge (Prediction Market & DEX Bot)

> Auto-generated codebase memory for AI agents. Last updated: 2026-06-19.

## Purpose

Full-stack automated prediction market and perpetual DEX trading bot (PolyEdge) supporting 10+
platforms including Polymarket, Kalshi, SX.bet, Limitless, Azuro, Myriad, Hyperliquid, Ostium,
Aster DEX, and Lighter. Features 14 strategies, bounded AGI autonomy with evolutionary strategy
composition (DRAFT→SHADOW→PAPER→LIVE), and a React dashboard.

## Tech Stack

- **Backend:** Python 3.10+, FastAPI, SQLAlchemy, Alembic, APScheduler
- **Frontend:** React 18, TypeScript, Vite, TanStack Query, Tailwind CSS, Recharts
- **Trading:** ccxt, py-clob-client (Polymarket CLOB), web3, eth-account, hyperliquid-python-sdk, ostium-python-sdk, lighter-sdk
- **AI/LLM:** Anthropic, Groq, OpenAI
- **Data:** numpy, pandas, scipy, feedparser, websockets
- **Infra:** PostgreSQL (prod) / SQLite (dev), Redis, Docker, Prometheus
- **ML:** scikit-learn, DEAP (evolutionary algorithms), vectorbt, HuggingFace Hub

## Entry Points

| Entry | Command | Description |
|-------|---------|-------------|
| `main.py` | `python main.py` | Minimal launcher |
| `run.py` | `python run.py` | Full backend runner with config |
| `backend/api/main` | `uvicorn backend.api.main:app --reload --port 8100` | FastAPI server |
| `frontend/` | `cd frontend && npm run dev` | React dashboard (Vite) |
| `docker-compose.yml` | `docker-compose up -d` | Full stack (backend + frontend + DB) |

## Directory Structure

```
1ai-trade-dex/
├── main.py                  # Minimal launcher
├── run.py                   # Full runner with env config
├── requirements.txt         # Python dependencies
├── docker-compose.yml       # Full stack deployment
├── Dockerfile               # Backend container
├── Procfile                 # Railway/Heroku deploy
├── railway.json             # Railway config
├── alembic.ini              # DB migration config
├── .env.example             # 1200+ line env template
├── backend/                 # FastAPI backend
│   ├── api/                 # REST endpoints (main.py, routes)
│   ├── api_websockets/      # WebSocket handlers
│   ├── ai/                  # AI/LLM integration layer
│   ├── agi/                 # AGI autonomy framework
│   ├── bot/                 # Telegram bot integration
│   ├── clients/             # External API clients
│   ├── core/                # Core config, logging, state
│   ├── job_queue/           # Background job processing
│   ├── modules/             # Feature modules
│   ├── research/            # Market research pipelines
│   ├── strategies/          # 14 trading strategies
│   └── .sisyphus/           # Session state
├── frontend/                # React dashboard
│   ├── src/                 # Components, hooks, pages
│   ├── package.json         # React 18 + Vite + Tailwind
│   └── vite.config.ts
├── alembic/                 # SQLAlchemy migrations
├── migrations/              # Additional migrations
├── tests/                   # 40+ test files
│   ├── fixtures/
│   ├── load/
│   └── reliability/
├── scripts/                 # 70+ utility scripts
├── data/                    # Wallet cache, backtests, scanner cache
├── state/                   # Runtime state (cancel signals)
├── docs/                    # Architecture, runbooks, research, papers
├── deploy/                  # Systemd service files
├── polyedge-docs/           # Docusaurus documentation site
└── walkthrough/             # Remotion video walkthrough
```

## Key Files

| File | Purpose |
|------|---------|
| `run.py` | Main backend runner — loads .env, starts FastAPI |
| `backend/api/main.py` | FastAPI app — REST + WebSocket endpoints |
| `backend/strategies/` | 14 strategies: BTC momentum, oracle, copy trader, weather, AGI, etc. |
| `backend/agi/` | AGI autonomy: genome registry, evolution scheduler, promotion pipeline |
| `backend/core/` | Config loading, logging, shared state |
| `backend/clients/` | Platform clients (Polymarket CLOB, Kalshi, DEXes) |
| `frontend/src/` | React dashboard with real-time WebSocket updates |
| `alembic/env.py` | Database migration environment |
| `.env.example` | Comprehensive config (300+ variables) |

## Architecture

```
React Dashboard (TS/TanStack) ──REST/WS──▶ FastAPI Backend
                                              │
                                    ┌─────────┴─────────┐
                                    │    AGI Layer        │
                                    │  Genome Registry    │
                                    │  Evolution Engine   │
                                    └─────────┬─────────┘
                                              │
                              ┌────────────────┼────────────────┐
                              │                │                │
                       14 Strategies     Risk Manager    Order Executor
                              │                │                │
                    ┌─────────┴──────┐   Circuit Breakers  Settlement
                    │                │   Kelly Sizing       Engine
              Prediction Markets   Perp DEXes
              (Polymarket, Kalshi, (Hyperliquid,
               SX.bet, Limitless,  Ostium, Aster,
               Azuro, Myriad)      Lighter)
                                              │
                                    PostgreSQL / Redis / SQLite
```

## Run Commands

```bash
# Backend
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env  # configure API keys
uvicorn backend.api.main:app --reload --port 8100

# Frontend
cd frontend && npm install && npm run dev

# Docker (full stack)
docker-compose up -d

# Tests
pytest tests/ -v
pytest tests/test_clob.py -v

# DB migrations
alembic upgrade head
```

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `POLYMARKET_PRIVATE_KEY` | For Polymarket | Ethereum private key for CLOB auth |
| `POLYMARKET_API_KEY` | For Polymarket | CLOB API key |
| `KALSHI_API_KEY_ID` | For Kalshi | API key identifier |
| `KALSHI_PRIVATE_KEY` | For Kalshi | RSA private key (PEM) |
| `HYPERLIQUID_PRIVATE_KEY` | For Hyperliquid | DEX private key |
| `OSTIUM_PRIVATE_KEY` | For Ostium | DEX private key |
| `ANTHROPIC_API_KEY` | For AI | Anthropic API key |
| `OPENAI_API_KEY` | For AI | OpenAI API key |
| `GROQ_API_KEY` | For AI | Groq API key |
| `TELEGRAM_BOT_TOKEN` | For alerts | Telegram bot token |
| `DATABASE_URL` | Yes | PostgreSQL or SQLite connection string |
| `REDIS_URL` | Optional | Redis connection (falls back to SQLite) |
| `API_HOST` / `API_PORT` | Optional | FastAPI bind address (default localhost:8100) |
| `MIN_EDGE_PP` | Optional | Minimum edge threshold (default 5.0) |
| `KELLY_FRACTION` | Optional | Kelly criterion fraction (default 0.30) |
| `MAX_POSITION_FRACTION` | Optional | Max single position (default 0.08) |
| `DAILY_LOSS_LIMIT_PCT` | Optional | Daily drawdown limit (default 0.10) |
| `WEATHER_ENABLED` | Optional | Weather strategy toggle (default True) |
| `HFT_ENABLED` | Optional | HFT mode toggle (default True) |
