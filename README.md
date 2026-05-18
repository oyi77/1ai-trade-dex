# PolyEdge — Prediction Market Trading Bot

A full-stack automated prediction market trading bot for **Polymarket** and **Kalshi**. 14 strategies with bounded AGI autonomy, evolutionary strategy composition, and a React dashboard.

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
- **Multi-Platform** — Polymarket CLOB SDK + Kalshi REST API simultaneously
- **Risk Management** — Circuit breakers, Kelly sizing, position limits, portfolio concentration guards
- **React Dashboard** — TypeScript + TanStack Query with real-time WebSocket updates

## Architecture

```
Frontend (React/TS) -> REST API (FastAPI) -> AGI Layer -> 14 Strategies -> Risk Manager
                                               |                              |
                                          Genome Registry              Order Executor
                                          Evolution Scheduler          Settlement Engine
                                               |
                                          Data Sources: Polymarket CLOB/WS, Kalshi, Coinbase, Binance, Open-Meteo
```

**Infrastructure:** PostgreSQL | Redis (fallback SQLite) | APScheduler | Prometheus | Docker

## Documentation

[API](docs/api.md) | [Config](docs/configuration.md) | [User Guide](docs/user-guide.md) | [AGI Framework](docs/architecture/adr-006-agi-autonomy-framework.md) | [Paper](docs/paper/paper.pdf) | [Pitch Deck](docs/pitchdeck/)

## License

MIT
