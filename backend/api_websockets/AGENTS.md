<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-05-09 | Updated: 2026-05-09 -->

# backend/api_websockets

## Purpose
Real-time WebSocket broadcast modules for live dashboard updates. Decouples frontend streaming from the main API by broadcasting events (activities, proposals, brain graph, livestream) via `backend.api.ws_manager_v2.topic_manager`.

## Key Files

| File | Description |
|------|-------------|
| `activity_stream.py` | Broadcasts activity log entries to WebSocket clients when new activities are logged via `POST /api/activities`. |
| `brain_stream.py` | Broadcasts brain graph events: signal arrival, debate start/end, trade execution, proposal generation. |
| `livestream.py` | MiroFish debate livestream — broadcasts bull/bear arguments, verdicts, and arena state to dashboard. Uses pipeline cards (max 50) and TaskManager for background tasks. |
| `proposals.py` | Broadcasts proposal status changes (approved, rejected, created) to all connected WebSocket clients. |

## For AI Agents

### Working In This Directory
- All modules use a global `TaskManager` instance set via `set_task_manager()` at startup
- Broadcast functions import `topic_manager` from `backend.api.ws_manager_v2` lazily to avoid circular imports
- All functions are async and use `asyncio` for non-blocking broadcasts

### Common Patterns
- Global task manager pattern: `set_task_manager(tm)` / `get_task_manager()`
- Lazy import of `topic_manager` inside broadcast functions
- Message format: `{"type": "...", "data": {...}, "timestamp": "..."}`

## Dependencies

### Internal
- `backend.api.ws_manager_v2` — WebSocket topic manager for broadcasting
- `backend.core.task_manager` — TaskManager for background task lifecycle

### External
- `asyncio` — Async scheduling
- `logging` — Structured logging

<!-- MANUAL: -->
