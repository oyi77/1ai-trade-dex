<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-05-09 | Updated: 2026-05-09 -->

# backend/services

## Purpose
External service integrations — MiroFish debate system lifecycle management and rollback utilities. Manages the state machine for the built-in debate engine (Bull/Bear/Judge) that powers MiroFish-compatible signal generation.

## Key Files

| File | Description |
|------|-------------|
| `mirofish_service.py` | `MiroFishService` — state machine for the debate engine: STOPPED→RUNNING→PAUSED→STOPPED |
| `mirofish_monitor.py` | Health monitoring for the MiroFish debate service |
| `mirofish_mock_server.py` | Local mock MiroFish server for development and testing (replaces the removed PM2 `mirofish-mock` process) |
| `rollback_manager.py` | `RollbackManager` — coordinates system rollback on critical failures |

## For AI Agents

### Working In This Directory
- **MiroFish is powered by the built-in debate engine** (`backend/ai/debate_engine.py`), not an external process. The PM2 `mirofish-mock` process was removed; `mirofish_mock_server.py` provides equivalent mock behavior for local dev.
- **State transitions are strict:** STOPPED→RUNNING (start), RUNNING→PAUSED (pause), RUNNING→STOPPED (stop), PAUSED→RUNNING (resume). Any→RUNNING (restart). Do not add transitions that skip states.
- `mirofish_mock_server.py` is for development only — it must not be started in production. The `ecosystem.config.js` PM2 config intentionally excludes it.
- `RollbackManager` is a last-resort safety mechanism — it should only be invoked by circuit breaker trip handlers, not by normal business logic.

### Testing Requirements
- Test state machine transitions — verify invalid transitions raise errors
- Mock the debate engine in service tests to avoid LLM API calls
- Test `mirofish_mock_server.py` response format matches the real MiroFish API contract

### Common Patterns
- Start the service: `service = MiroFishService(); await service.start()`
- Check status: `status = service.get_status()  # returns {"state": "RUNNING", ...}`
- Use mock in tests: start `mirofish_mock_server.py` and point `settings.MIROFISH_URL` at it

## Dependencies

### Internal
- `backend.ai.debate_engine` — Bull/Bear/Judge debate implementation
- `backend.ai.mirofish_client` — MiroFish API client
- `backend.config` — `settings` for MiroFish URL and credentials
- `backend.core.circuit_breaker` — circuit breaker integration for `RollbackManager`

### External
- `fastapi` — mock server uses FastAPI
- `asyncio` — async state machine
