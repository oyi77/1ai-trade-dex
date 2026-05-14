# API LAYER
<!-- Parent: ../AGENTS.md -->

**Module**: `backend/api/` — FastAPI REST endpoints, 189 routes

## PURPOSE

REST API layer: 189 endpoints across 10+ routers. FastAPI with CORS, lifespan-managed, Prometheus metrics.

## ENTRY POINT

`main.py` (2234 LOC) — FastAPI app entrypoint  
Lifespan events: app startup/shutdown handlers  
CORS: configured for cross-origin requests  
Metrics: Prometheus instrumentation

## ROUTE STRUCTURE

| Router | Purpose | File | Endpoints |
|--------|---------|------|-----------|
| **auth** | Authentication, user management | auth.py (734 LOC) | ~15 |
| **markets** | Market queries, CLOB data | markets.py | ~20 |
| **trading** | Trade execution, history | trading.py | ~25 |
| **copy_trading** | Leaderboard copy trading | copy_trading.py | ~15 |
| **arbitrage** | Cross-exchange arbitrage | arbitrage.py | ~10 |
| **market_intel** | AI signals, market analysis | market_intel.py | ~20 |
| **auto_trader** | Automated strategy execution | auto_trader.py | ~15 |
| **system** | Health checks, system status | system.py (2234 LOC) | ~20 |
| **risk** | Risk management queries | risk.py | ~15 |
| **admin** | Admin operations, settings | settings.py (928 LOC) | ~40 |

## CRITICAL RULES

### Health Checks
- `/api/v1/health` uses **bounded dependency checks**
- Slow RPC calls degrade health, NOT hang requests
- Tiered checks: fast → medium → slow (with timeouts)

### Error Handling
- Never bare `except Exception: pass`
- Always `logger.exception("descriptive")` with request context
- Return structured error responses (status codes + error details)

### Session Management
- Use bounded DB sessions (no long-lived sessions)
- Proper async/await (FastAPI native)

## ANTI-PATTERNS

- ❌ Synchronous RPC calls in endpoints
- ❌ Silent exceptions (logger.exception required)
- ❌ No timeout on external API calls
- ❌ Unbounded DB query results

## TESTING

```bash
pytest backend/tests/ -k "api" -v
```
