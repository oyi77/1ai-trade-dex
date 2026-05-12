<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-05-07 | Updated: 2026-05-10 -->

# events

## Purpose
Server-Sent Events (SSE) router with channel-based filtering. Allows frontend clients to subscribe to specific event channels (trades, signals, health, etc.) for real-time dashboard updates.

## Key Files

| File | Description |
|------|-------------|
| `__init__.py` | Package marker |
| `sse_router.py` | Channel-aware SSE router — `/api/v1/events/stream` with parameterized channel subscriptions |

## Subdirectories

None.

## For AI Agents

### Working In This Directory
- Events are published via `backend.core.event_bus.publish_event()`
- SSE clients connect to `/api/v1/events/stream?channels=trades,signals,health`
- Channel-to-event-type mapping defined in `sse_router.py`

### Testing Requirements
- Run: `pytest backend/tests/ -v -k sse`

### Common Patterns
- Use `StreamingResponse` with `text/event-stream` content type
- Filter events by channel parameter before sending to client
- Heartbeat mechanism to keep connections alive

## Dependencies

### Internal
- `backend.core.event_bus` — Event bus for publishing events
- `backend.config` — Settings

### External
- `fastapi` — API framework
- `sse_starlette` — SSE support for Starlette/FastAPI

<!-- MANUAL: -->