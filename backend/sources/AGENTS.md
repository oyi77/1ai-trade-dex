<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-05-09 | Updated: 2026-05-09 -->

# backend/sources

## Purpose
Raw data source adapters for Polymarket order book feeds. Provides low-level access to market data before aggregation and processing.

## Key Files

| File | Description |
|------|-------------|
| `polymarket_book.py` | Polymarket order book raw feed adapter. Connects to Polymarket WebSocket for real-time order book updates. Parses raw messages into internal data structures. |

## For AI Agents

### Working In This Directory
- Raw feeds are ephemeral — persist data in `backend.data` if needed for historical analysis
- WebSocket connections are managed by `backend.data.ws_client`
- All parsers validate message format before processing

### Common Patterns
- Use `backend.data.ws_client` for WebSocket connection management
- Parse messages with `json.loads()` then validate schema with Pydantic models

## Dependencies

### Internal
- `backend.data.ws_client` — WebSocket client wrapper
- `backend.data.orderbook_ws` — Orderbook-specific WebSocket handling

### External
- `websockets` — WebSocket client library
- `json` — Message parsing

<!-- MANUAL: -->
