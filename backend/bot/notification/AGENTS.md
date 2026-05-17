<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-05-17 -->

# bot/notification

## Purpose
Plugin-based notification provider system. Provides abstract base classes and a registry for multi-channel notification delivery (Telegram, Discord, Slack, Webhook). Decouples notification logic from specific delivery channels.

## Key Files
| File | Description |
|------|-------------|
| `__init__.py` | Exports `BaseNotificationProvider`, `NotificationManifest`, `NotificationRegistry`, `registry` |
| `base.py` | `BaseNotificationProvider` ABC + `NotificationManifest` — all providers subclass this; `send(message, event_type, details) -> bool` |
| `registry.py` | `NotificationRegistry` singleton — auto-discovers providers, broadcasts to all enabled channels, health checks |

## Subdirectories
| Directory | Purpose |
|-----------|---------|
| `providers/` | Concrete notification provider implementations (Telegram, Discord, Slack, Webhook) |

## For AI Agents

### Working In This Directory
- The registry is a singleton — use `from backend.bot.notification import registry`
- Providers are auto-discovered from `backend.bot.notification.providers` via `registry.auto_discover()`
- `broadcast()` sends to ALL enabled providers; `send_to()` targets a specific channel
- Env vars are validated at registration time (except in `SHADOW_MODE`)
- Notifications are async — `send()` returns `True` on success, `False` on failure (never raises)

### Common Patterns
- Broadcast: `await registry.broadcast("trade_alert", "BTC long opened at $65000")`
- Send to one: `await registry.send_to("telegram", "status", "System healthy")`
- Register manually: `registry.register(MyProvider)`

## Dependencies

### Internal
- `backend.core.plugin_errors` — `PluginEnvVarMissing`, `PluginNotFound`

### External
- Platform-specific SDKs per provider (python-telegram-bot, discord.py, slack_sdk, httpx)
