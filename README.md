# PolyEdge — Prediction Market & DEX Trading Bot

A full-stack automated prediction market and perpetual DEX trading bot supporting **10+ platforms** (including Polymarket, Kalshi, SX.bet, Limitless, Azuro [Bookmaker.xyz, Predict.fun], Myriad, Hyperliquid, Ostium, Aster DEX, Lighter, and a Paper Trading simulation). Features 14 strategies with bounded AGI autonomy, evolutionary strategy composition, and a React dashboard.

[![DOI](https://zenodo-badge.example.com/10.5281/zenodo.16966978.svg)](https://doi.org/10.5281/zenodo.16966978)
![Python](https://img.shields.io/badge/python-3.10+-blue) ![React](https://img.shields.io/badge/react-18+-61DAFB)

## Quick Start

```bash
# Backend
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env  # configure API keys
uvicorn backend.api.main:app --reload --port 8100

# Frontend
cd frontend && npm install && npm run dev
```

- Backend: http://localhost:8100 | API docs: http://localhost:8100/docs
- Frontend: http://localhost:5173
- Docker: `docker-compose up -d`

## Features

- **14 Strategies** — BTC momentum, oracle, copy trader, market maker, cross-market arb, weather, AGI orchestrator, and more
- **AGI Autonomy** — Evolutionary strategy composition with DRAFT->SHADOW->PAPER->LIVE promotion pipeline
- **Multi-Platform** — Plug-and-play integrations for **5+ Prediction Markets** (Polymarket, Kalshi, SX.bet, Limitless, Myriad, Azuro) and **4+ Perpetuals DEXes** (Hyperliquid, Ostium, Aster, Lighter) via an auto-discovering plugin-based provider registry.
- **Risk Management** — Circuit breakers, Kelly sizing, position limits, portfolio concentration guards
- **React Dashboard** — TypeScript + TanStack Query with real-time WebSocket updates

## Architecture

```
Frontend (React/TS) -> REST API (FastAPI) -> AGI Layer -> 14 Strategies -> Risk Manager
                                               |                              |
                                          Genome Registry              Order Executor
                                          Evolution Scheduler          Settlement Engine
                                               |
                                          Data Sources: Polymarket CLOB/WS, Kalshi, SX.bet, Limitless, Myriad, Azuro, Hyperliquid, Ostium, Aster, Lighter, Coinbase, Binance, Open-Meteo
```

**Infrastructure:** PostgreSQL | Redis (fallback SQLite) | APScheduler | Prometheus | Docker

## Documentation

[API](docs/api.md) | [Config](docs/configuration.md) | [User Guide](docs/user-guide.md) | [AGI Framework](docs/architecture/adr-006-agi-autonomy-framework.md) | [Paper](docs/paper/paper.pdf) | [Pitch Deck](docs/pitchdeck/)

## License

MIT
