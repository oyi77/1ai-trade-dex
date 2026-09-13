"""
PolyEdge Telegram Bot.

Provides:
- Signal alerts: weather (with COPY/SKIP keyboard) and copy trade (notify-only)
- Commands: /status /positions /leaderboard /pause /resume /settings /mode
- Admin-only guard for destructive commands
- Error alerting: unhandled exceptions forwarded to admin

Execution modes:
- Weather signals: sends alert with inline keyboard [COPY TRADE][SKIP][VIEW MARKET]
  User must press COPY TRADE to execute (confirm mode)
- Copy trade signals: auto-executes within risk limits, sends notification after
"""

import asyncio
from datetime import datetime, timezone
from typing import Optional, Callable

from loguru import logger

from backend.config import settings

from ._telegram_bot_handle_callback import (
    PolyEdgeBotMixin2,
)

from ._telegram_bot_init import (
    PolyEdgeBotMixin,
)

class PolyEdgeBot(PolyEdgeBotMixin, PolyEdgeBotMixin2):
    """
    Telegram bot for PolyEdge.

    Usage:
        bot = PolyEdgeBot(token="...", admin_ids=[123456])
        await bot.start()
        await bot.send_weather_signal(signal)  # sends alert with keyboard
        await bot.send_copy_alert(signal)      # sends post-execution notify
        await bot.stop()
    """


from ._telegram_bot_telegram_available import (  # noqa: E402  (must follow the names it imports back)
    TELEGRAM_AVAILABLE,
    bot_from_settings,
)


__all__ = [
    "Callable",
    "Optional",
    "PolyEdgeBotMixin",
    "PolyEdgeBotMixin2",
    "asyncio",
    "datetime",
    "logger",
    "settings",
    "timezone",
]
