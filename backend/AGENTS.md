<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-05-09 | Updated: 2026-05-09 -->

# backend

## Purpose
Python FastAPI backend — trading engine, strategy execution, AI signal generation, market data feeds, and all server-side logic for PolyEdge. Organized into domain layers: core execution, strategies, AI/LLM, API routers, data providers, and supporting infrastructure.

## Key Files

| File | Description |
|------|-------------|
| `__init__.py` | Package marker |
| `config.py` | Central configuration — all env var bindings, feature flags, external API URLs |

## Subdirectories

| Directory | Purpose |
|-----------|---------|
| `core/` | Trading engine — execution, risk, settlement, AGI lifecycle, scheduler (see `core/AGENTS.md`) |
| `strategies/` | Alpha strategy implementations — BaseStrategy subclasses (see `strategies/AGENTS.md`) |
| `ai/` | LLM routing, debate engine, signal parsing, model integrations (see `ai/AGENTS.md`) |
| `api/` | FastAPI routers — auth, markets, trading, AGI, admin, WebSocket/SSE (see `api/AGENTS.md`) |
| `models/` | SQLAlchemy ORM models and session factory (see `models/AGENTS.md`) |
| `data/` | Market data providers, CLOB client, Gamma API, market universe scanner (see `data/AGENTS.md`) |
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

## For AI Agents

### Working In This Directory
- **`backend/config.py` is the single source of truth for env vars** — never hardcode URLs, keys, or thresholds; always add new config to `config.py` and `.env.example` together.
- **Layer boundaries matter:** strategies call core, core calls models/data, API calls core — never import upward (e.g. core must not import from api/).
- **Database schema changes require a migration:** `alembic revision --autogenerate -m "description"` then `alembic upgrade head`. Never edit existing migration files.
- `backend/modules/` is for infrastructure modules (data feeds, execution helpers, scanners) — NOT alpha strategies. Alpha strategies go in `backend/strategies/`.
- All new feature flags must be added to `backend/config.py` and documented in `.env.example`.

### Testing Requirements
- Run from project root: `pytest` (uses `pytest.ini`)
- Backend-specific tests also live in `backend/tests/`
- Do not run live trading tests without `SHADOW_MODE=true`

### Common Patterns
- Import config: `from backend.config import settings`
- Get DB session: `with get_db_session() as db:` (see `backend/db/utils.py`)
- Emit events: `event_bus.emit(EventType.X, payload)` (see `backend/core/event_bus.py`)
- **Logging**: Use `from loguru import logger` exclusively — never `import logging` or `logging.getLogger()`. Loguru auto-captures module name. Config in `backend/core/log.py`. Structured fields: `logger.info("trade executed", strategy="btc_oracle", market="BTC-UP")`. Env vars: `LOG_LEVEL`, `LOG_JSON`, `LOG_FILE`, `LOG_ROTATION`, `LOG_RETENTION`.
- **Error handling**: Never use bare `except Exception: pass` — always add `logger.exception("descriptive message")` so errors are visible. Silent error swallowing is the #1 root cause of observability failures.

## Dependencies

### External
- `FastAPI` + `uvicorn` — web framework and ASGI server
- `SQLAlchemy 2.0` + `Alembic` — ORM and migrations
- `SQLite` / `Redis` — storage and job queue
- `httpx` — async HTTP client for external APIs
- `pydantic` — data validation and settings management
