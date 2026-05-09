<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-04-10 | Updated: 2026-05-09 -->

# bot

## Purpose
Telegram bot notification and alerting system. Sends trade alerts, system status updates, and opportunity notifications to users via Telegram. Provides a dispatcher pattern with global bot instance for decoupled notification from trading logic.

## Key Files
| File | Description |
|------|-------------|
| notifier.py | Global notification dispatcher; singleton pattern with set_bot() and get_bot(); fire-and-forget async notifications |
| telegram_bot.py | PolyEdgeBot class; Telegram bot implementation with handlers for signals, trades, status updates |
| notification_router.py | Routing logic for different notification types (alerts, approvals, confirmations) |

## Subdirectories
None

## For AI Agents
### Working In This Directory
- Notification system uses global `_bot` instance set via `set_bot()` on startup
- All modules call `notify_*()` functions without holding a bot reference
- `_fire()` schedules coroutines on the event loop (best-effort, never raises)
- Notifications are async and fire-and-forget; failures logged but don't propagate
- Bot lifecycle: initialized in orchestrator startup, set globally, then called via notifier functions

### Testing Requirements
- Test notifier with and without bot initialized
- Verify async task scheduling (event loop running/not running)
- Test Telegram message formatting and truncation
- Verify notification type routing
- Test error handling (API rate limits, connection failures)

### Common Patterns
- Global bot instance accessed via get_bot()
- Async fire-and-forget for all notifications
- Error logging instead of exception propagation
- TYPE_CHECKING for import-time circular dependency avoidance
- Coroutine scheduling with asyncio.get_event_loop().create_task()

## Dependencies
### Internal
- backend.core.signals (signal types)
- backend.models.database (trade models)

### External
- python-telegram-bot (Telegram API)
- asyncio (async task scheduling)

<!-- MANUAL: -->
