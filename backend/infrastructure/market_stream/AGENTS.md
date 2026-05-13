<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-05-07 | Updated: 2026-05-10 -->

# market_stream

## Purpose
Real-time market stream infrastructure. Routes orderbook updates from WebSocket feeds to downstream consumers (arbitrage monitors, HFT strategies).

## Key Files

| File | Description |
|------|-------------|
| `__init__.py` | Package marker |
| `orderbook_router.py` | Orderbook update router — adapts Polymarket WS snapshots into `OrderbookUpdate` and dispatches real-time orderbook data to subscribers with circuit-breaker protection |

## Subdirectories

None.

## For AI Agents

### Working In This Directory
- `OrderbookUpdate` dataclass is the standard format for orderbook data across the system
- Circuit breakers protect against cascading WebSocket failures
- Used by HFT strategies

### Testing Requirements
- Run: `pytest backend/tests/ -v -k orderbook`

### Common Patterns
- Async callback-based architecture
- Circuit breaker wrapping for resilience
- Dataclass-based message passing

## Dependencies

### Internal
- `backend.config` — Settings
- `backend.core.circuit_breaker` — CircuitBreaker for resilience

### External
- `asyncio` — Async runtime

<!-- MANUAL: -->
