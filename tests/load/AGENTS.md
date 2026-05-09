<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-05-05 | Updated: 2026-05-09 -->

# tests/load

## Purpose
Load and stress tests for the PolyEdge system. Validates performance under high-concurrency conditions.

## Key Files

| File | Description |
|------|-------------|
| `rate_limit_test.py` | Rate limiting tests: validates API rate limits, backpressure, and request throttling under load. |
| `websocket_load_test.py` | WebSocket load tests: simulates 1000+ concurrent WebSocket connections, measures latency and message throughput. |
| `websocket_load_test_simple.py` | Simplified WebSocket load test for quick validation of connection limits. |

## For AI Agents

### Working In This Directory
- Load tests may hit real APIs — use mocks for CI environments
- Set `SHADOW_MODE=true` before running to prevent live trades
- Monitor system resources (CPU, memory, DB connections) during tests

### Common Patterns
- Use `asyncio.gather()` for concurrent request simulation
- Assert response times < 500ms for API, < 100ms for WebSocket latency

## Dependencies

### Internal
- `backend.api.main` — FastAPI app for testing
- `backend.core.event_bus` — Event bus for WebSocket tests

### External
- `pytest` — Test runner
- `asyncio` — Concurrent execution
- `httpx` — HTTP client for load testing

<!-- MANUAL: -->
