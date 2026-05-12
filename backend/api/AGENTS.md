<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-05-09 | Updated: 2026-05-09 -->

# backend/api

## Purpose
FastAPI routers — all HTTP endpoints, WebSocket handlers, SSE streams, middleware, and the ASGI app factory. Modularized from a former monolithic `main.py`; see `docs/architecture/API_STRUCTURE.md` for the full modularization history.

## Key Files

| File | Description |
|------|-------------|
| `main.py` | ASGI app factory — mounts all routers, CORS middleware, lifespan handler |
| `lifespan.py` | FastAPI lifespan context — startup/shutdown hooks for scheduler, DB, Redis |
| `auth.py` | Admin auth routes + `authorize_realtime_access()` — cookie session and legacy API key validation |
| `dashboard.py` | Dashboard data endpoints — BotState, stats, equity |
| `trading.py` | Trade management endpoints |
| `markets.py` | Market data and discovery endpoints |
| `admin.py` | Admin control endpoints — strategy enable/disable, mode switching |
| `settings.py` | Settings read/write endpoints including risk profile |
| `proposals.py` | Strategy improvement proposal endpoints |
| `analytics.py` | Analytics and performance endpoints |
| `backtest.py` | Backtesting endpoints |
| `alerts.py` | Alert configuration and history endpoints |
| `activities.py` | Activity log endpoints |
| `brain.py` | AI brain / decision log endpoints |
| `learning.py` | Online learning endpoints |
| `arbitrage.py` | Arbitrage opportunity endpoints |
| `copy_trading.py` | Copy trading monitor endpoints |
| `market_intel.py` | Market intelligence endpoints |
| `wallets.py` | Wallet management endpoints |
| `sync.py` | Data sync endpoints |
| `system.py` | System health and status endpoints |
| `metrics_endpoint.py` | Prometheus metrics scrape endpoint |
| `auto_trader.py` | Auto-trader control endpoints |
| `agi_routes.py` | AGI experiment and genome endpoints |
| `agi/kg_router.py` | Knowledge graph endpoints |
| `events/sse_router.py` | SSE event stream — channel-aware, cookie-authenticated |
| `websockets_routes.py` | WebSocket routes — secured with `authorize_realtime_access()` |
| `ws_manager_v2.py` | WebSocket connection manager |
| `errors.py` | Global exception handlers |
| `validation.py` | Pydantic request/response models |
| `versioning.py` | API versioning utilities |
| `rate_limiter.py` | Per-IP rate limiting middleware |
| `connection_limits.py` | WebSocket connection limit enforcement |
| `timeout_middleware.py` | Request timeout middleware |

## For AI Agents

### Working In This Directory
- **All new endpoints must be added to `docs/api.md`** — it is the authoritative REST API reference.
- **Realtime auth is centralized in `auth.py:authorize_realtime_access()`** — wire all new SSE and WebSocket routes through it. Never add a new realtime endpoint that bypasses auth.
- **SSE is the canonical realtime channel** — `events/sse_router.py` is the single SSE source. Do not add a second SSE endpoint in `websockets_routes.py` (this was a past bug, now fixed).
- **Never import from `backend/strategies/` or `backend/core/` directly in routers** — routers call service/core functions, they do not instantiate strategies.
- All routers use `prefix="/api/v1/..."` — maintain this convention for new routers. REST routes use `/api/v1/`, WebSocket routes use `/ws/`.
- Request validation models live in `validation.py` — add new Pydantic models there, not inline in route handlers.

### Adding a New Endpoint
1. Add the route to the appropriate existing router file (or create a new one for a new domain)
2. If creating a new router, register it in `main.py`
3. Add Pydantic request/response models to `validation.py`
4. Add the endpoint to `docs/api.md`

### Testing Requirements
- Use `TestClient(app)` from `fastapi.testclient`
- Override `get_db` dependency with in-memory SQLite session
- Test auth: verify 401 for unauthenticated requests to protected endpoints
- Test SSE: verify `authorize_realtime_access()` is called

### Common Patterns
- Auth dependency: `admin: bool = Depends(require_admin)`
- DB dependency: `db: Session = Depends(get_db)`
- Emit SSE event: `await event_bus.emit(EventType.TRADE_EXECUTED, payload)`

## Dependencies

### Internal
- `backend.core` — business logic called by routers
- `backend.models.database` — ORM models and `get_db`
- `backend.config` — `settings`

### External
- `fastapi` — routing, dependency injection, WebSocket
- `pydantic` — request/response validation
- `sqlalchemy` — DB session via `get_db`
