---
sidebar_position: 5
---

# Project Structure

PolyEdge is organized into backend and frontend directories, separating core trading logic from monitoring and administration.

## Directory Tree

```text
polyedge/
├── backend/
│   ├── api/            # FastAPI routes and middleware
│   ├── core/           # Orchestration, risk, scheduling, and signal logic
│   ├── data/           # Market data clients and integration
│   ├── models/         # SQLAlchemy database models
│   ├── strategies/     # Individual trading strategy implementations
│   ├── ai/             # AI ensemble and signal providers
│   ├── bot/            # Telegram and Discord notification routers
│   ├── queue/          # Job queue (Redis and SQLite implementations)
│   └── tests/          # Pytest backend test suite
├── frontend/
│   ├── src/            # React source code
│   │   ├── components/ # Reusable UI components
│   │   ├── hooks/      # TanStack Query and state management hooks
│   │   └── pages/      # Page-level dashboard and admin views
│   ├── e2e/            # Playwright end-to-end tests
│   └── vite.config.ts  # Vite build configuration
├── docs/               # System and architecture documentation
├── main.py             # Main entry point (API server and workers)
├── run.py              # Environment-validated runner
└── docker-compose.yml  # Multi-service container orchestration
```

## Top-Level Directories

### Backend
The heart of the trading bot, written in Python. It contains the API layer, core trading engine, market data clients, and strategy implementations.

### Frontend
A React dashboard for monitoring signals, trades, and portfolio performance. It also provides administrative controls for managing the bot's configuration.

### Docs
Documentation for the system, including API references, architecture decision records (ADRs), and setup guides.

## Key Files

| File | Purpose |
|------|---------|
| `main.py` | Starts the FastAPI server and background processes. |
| `backend/api/main.py` | Configures FastAPI, CORS, and registers all sub-routers. |
| `backend/core/orchestrator.py` | Coordinates the execution of registered strategies. |
| `backend/core/risk/risk_manager.py` | Validates trades against position and portfolio risk limits. |
| `backend/core/scheduling/` | Scheduler, task management, and scheduling strategies (sub-package). |
| `backend/core/settlement/` | Trade settlement, dispute tracking, and auto-redeem (sub-package). |
| `backend/core/wallet/` | Wallet management, bankroll allocation, and reconciliation (sub-package). |
| `backend/core/edge/` | Edge calculation, calibration, and signal pipeline (sub-package). |
| `backend/strategies/base.py` | Base class and context for implementing trading strategies. |
| `backend/strategies/` | 20+ strategy implementations (BTC momentum, oracle, copy trader, etc.). |
| `backend/markets/` | Abstract market provider layer with 11 plugin providers. |
| `backend/config.py` | Central configuration file for all system settings. |
| `frontend/src/api.ts` | Frontend client for communicating with the backend API. |

## Module Dependency Overview

The system is designed with a layered architecture:
- **API** depends on **Core**, **Models**, and **Application** services.
- **Core** depends on **Data**, **Strategies**, **AI**, and **Risk Manager**.
- **Core** is organized into sub-packages: `risk/`, `scheduling/`, `settlement/`, `wallet/`, `edge/`, `learning/`, `execution_pipeline/`, `activity/`.
- **Strategies** inherit from a base class in **Core** and use **Data** and **AI** for signal generation.
- **Markets** provides an abstract provider layer — 11 plug-and-play exchange plugins, registered via auto-discovery.
- **Data** clients are isolated, providing a consistent interface for market and external information.
- **Models** are split across ~24 domain-specific files (trade_db, strategy_db, signal_db, wallet_db, etc.) with `database.py` as a thin re-exporter.
- **Application**, **Domain**, and **Repositories** layers provide clean separation for business logic, domain models, and data access.
