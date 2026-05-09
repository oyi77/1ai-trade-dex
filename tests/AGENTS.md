<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-05-09 | Updated: 2026-05-09 -->

# tests

## Purpose
Root-level integration tests for the PolyEdge backend. Tests here exercise cross-cutting concerns — API endpoints, settlement flows, signal parsing, WebSocket behavior, and AGI autonomous loop integration. Unit tests for individual modules live in `backend/tests/`.

## Key Files

| File | Description |
|------|-------------|
| `conftest.py` | Shared pytest fixtures — in-memory SQLite DB, apscheduler stubs, session factory |
| `test_admin_api.py` | Admin API endpoint integration tests |
| `test_agi_autonomous_loop.py` | AGI promotion/demotion lifecycle integration tests |
| `test_backtest_data.py` | Backtest data validation tests |
| `test_backtest_gate.py` | Backtest gate enforcement tests |
| `test_clob.py` | CLOB API client tests |
| `test_copy_trader.py` | Copy trader strategy tests |
| `test_graceful_shutdown.py` | Graceful shutdown behavior tests |
| `test_settlement.py` | Settlement flow integration tests |
| `test_signal_engine.py` | Signal generation and routing tests |
| `test_signal_parser.py` | AI signal parser tests |
| `test_validation.py` | Input validation tests |
| `test_ws_client.py` | WebSocket client tests |
| `test_ws_reconnect.py` | WebSocket reconnection logic tests |
| `verify_data_validation.py` | Data validation verification script (run manually) |

## Subdirectories

| Directory | Purpose |
|-----------|---------|
| `fixtures/` | Static JSON fixtures — sample signals, trades, proposals, audit logs |
| `load/` | Load and stress tests — WebSocket and rate limit testing |
| `reliability/` | Error recovery and reliability tests |

## For AI Agents

### Working In This Directory
- **Always use in-memory SQLite for test isolation** — `conftest.py` provides `TestSessionLocal`; never connect to the production DB in tests.
- **Stub `apscheduler` and `backend.core.scheduler` before importing the app** — the scheduler starts background jobs on import; tests that skip this stub will hang or fail. See `conftest.py` for the pattern.
- **Never run tests with live API credentials** — set `SHADOW_MODE=true` and mock external API calls.
- Load tests in `load/` are not part of the standard `pytest` run — execute them manually against a running instance.
- `verify_*.py` scripts are manual verification tools, not pytest tests — run them explicitly, not via `pytest`.

### Testing Requirements
- Run all tests: `pytest` from project root
- Run a specific file: `pytest tests/test_settlement.py -v`
- Run with coverage: `pytest --cov=backend`
- Load tests: `python tests/load/websocket_load_test.py` (requires running server)

### Common Patterns
- Use `TestClient(app)` from `fastapi.testclient` for API tests
- Override DB dependency: `app.dependency_overrides[get_db] = lambda: TestSessionLocal()`
- Mock external calls: `@patch("backend.data.gamma.GammaClient.get_markets")`
- Async tests: mark with `@pytest.mark.asyncio`

## Dependencies

### Internal
- `backend.api.main` — FastAPI app under test
- `backend.models.database` — ORM models and Base for schema creation
- `conftest.py` — shared fixtures

### External
- `pytest` — test runner
- `pytest-asyncio` — async test support
- `fastapi.testclient` — ASGI test client
- `unittest.mock` — mocking utilities
