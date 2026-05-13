<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-05-09 | Updated: 2026-05-09 -->

# backend/infrastructure

## Purpose
Low-level infrastructure components — real-time market stream routing and WebSocket order book management. Provides the plumbing that connects exchange WebSocket feeds to strategy consumers.

## Subdirectories

| Directory | Purpose |
|-----------|---------|
| `market_stream/` | Real-time order book routing from WebSocket feeds to strategy subscribers |

## Key Files

| File | Description |
|------|-------------|
| `market_stream/orderbook_router.py` | `OrderbookRouter` — adapts Polymarket WebSocket snapshots and routes real-time order book updates to registered strategy callbacks; uses circuit breaker for feed resilience |
| `market_stream/__init__.py` | Package marker |

## For AI Agents

### Working In This Directory
- **`OrderbookRouter` uses a circuit breaker** — if the upstream WebSocket feed fails repeatedly, the circuit opens and callbacks stop receiving updates. Strategies must handle the absence of order book updates gracefully (fall back to REST polling or skip the cycle).
- **Callbacks are async** — register callbacks with `router.subscribe(market_id, async_callback)`. Synchronous callbacks will cause event loop blocking.
- The router is a singleton per process — do not instantiate multiple routers for the same feed.

### Testing Requirements
- Test callback registration and deregistration
- Test circuit breaker trip behavior — verify callbacks stop being called when circuit is open
- Mock WebSocket feed with `asyncio.Queue` for deterministic test delivery

### Common Patterns
```python
router = OrderbookRouter(settings)
await router.subscribe("market_id", my_async_callback)
await router.start()  # begins consuming WebSocket feed
```

## Dependencies

### Internal
- `backend.config` — `settings` for WebSocket URLs
- `backend.core.circuit_breaker` — feed resilience

### External
- `asyncio` — async callback dispatch
- `websockets` — WebSocket feed consumption
