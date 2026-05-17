<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-05-17 -->

# bot/notification/providers

## Purpose
Concrete notification provider implementations. Each provider wraps a specific messaging platform behind the `BaseNotificationProvider` interface.

## Key Files
| File | Description |
|------|-------------|
| `__init__.py` | Auto-imports all provider modules to trigger registration |
| `telegram.py` | Telegram notification provider — requires `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` |
| `discord.py` | Discord notification provider — requires `DISCORD_WEBHOOK_URL` |
| `slack.py` | Slack notification provider — requires `SLACK_WEBHOOK_URL` |
| `webhook.py` | Generic HTTP webhook provider — requires `WEBHOOK_URL` |

## For AI Agents

### Working In This Directory
- Each provider subclasses `BaseNotificationProvider` and implements `manifest()` and `send()`
- Providers are auto-discovered on import — adding a new file here with a valid subclass is sufficient
- `manifest()` declares `required_env_vars` — the registry validates these at startup (unless `SHADOW_MODE`)
- `send()` must return `bool` (True=success, False=failure) and never raise exceptions

## Dependencies

### Internal
- `backend.bot.notification.base` — `BaseNotificationProvider`, `NotificationManifest`
- `backend.core.plugin_errors` — error types

### External
- `telegram` — python-telegram-bot (optional)
- `discord` — discord.py (optional)
- `slack_sdk` — Slack SDK (optional)
- `httpx` — HTTP client for webhooks
