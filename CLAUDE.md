# PolyEdge — Agent Rules

Condensed critical rules for AI coding assistants. Full guidance is in `AGENTS.md` and subdirectory `AGENTS.md` files.

## Non-negotiable rules

- **Never commit `.env`** — it contains live API keys and wallet credentials.
- **Every code change must update affected docs** — `AGENTS.md` files, `docs/api.md` (new endpoints), `IMPLEMENTATION_GAPS.md` (new gaps), `.env.example` (new env vars). Do not skip.
- **Never run live trading tests without `SHADOW_MODE=true`**.
- **Database schema changes require an Alembic migration**: `alembic revision --autogenerate -m "description"` then `alembic upgrade head`. Never edit existing migration files.

## Architecture boundaries

- `backend/modules/` is for infrastructure modules (data feeds, execution helpers, scanners). Alpha strategies go in `backend/strategies/`.
- Layer import direction: `api/ → core/ → models/data/` — never import upward (e.g. `core/` must not import from `api/`).
- `backend/domain/` is the innermost layer — no imports from `core/`, `api/`, or `strategies/`.

## BotState concurrency

Always acquire `botstate_mutex` before any BotState read-modify-write:

```python
async with botstate_mutex:
    state = db.query(BotState).with_for_update().first()
    # ... mutate ...
    db.commit()
```

Skipping this causes lost updates under concurrent execution.

## Risk and settlement — ADR-gated files

`risk_manager.py`, `circuit_breaker.py`, and `settlement.py` must not be weakened without a new ADR in `docs/architecture/`. Any change that relaxes a limit, bypasses a check, or alters settlement logic requires documented justification.

## Trade records are append-only

Never mutate historical `Trade` rows to explain rejected attempts. Use `TradeAttemptRecorder` (`backend/core/trade_attempts.py`) instead. See `docs/architecture/adr-003-trade-attempt-observability.md`.

## Realtime auth

All SSE and WebSocket routes must go through `authorize_realtime_access()` in `backend/api/auth.py`. Never add a realtime endpoint that bypasses it. Frontend must use `withCredentials: true` — do not append tokens to SSE/WS URLs.

## Strategy governance

Killed strategies (disabled by AGI health check) must not be manually re-enabled. The authoritative enabled/disabled state is `StrategyConfig` in the DB, not any file. See `backend/strategies/AGENTS.md` for the full governance table.

## auto_trader is not a strategy

`backend/core/auto_trader.py` is an execution router. Trade attribution uses `Signal.track_name` to preserve the originating strategy name.
