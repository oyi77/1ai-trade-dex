"""Carved verbatim out of ``backend/bot/telegram_bot.py`` — statements moved, no logic changed."""

from . import telegram_bot as _facade

try:
    from telegram import (
        Bot,
        InlineKeyboardButton,
        InlineKeyboardMarkup,
        Update,
    )
    from telegram.ext import (
        Application,
        CallbackQueryHandler,
        CommandHandler,
        ContextTypes,
    )
    from telegram.constants import ParseMode

    TELEGRAM_AVAILABLE = True
except ImportError:
    TELEGRAM_AVAILABLE = False
    _facade.logger.warning("python-telegram-bot not installed — Telegram alerts disabled")
def bot_from_settings() -> "PolyEdgeBot":
    """Create PolyEdgeBot from app settings."""

    token = getattr(_facade.settings, "TELEGRAM_BOT_TOKEN", "") or ""
    raw_ids = getattr(_facade.settings, "TELEGRAM_ADMIN_CHAT_IDS", "") or ""
    admin_ids = []
    for part in str(raw_ids).split(","):
        part = part.strip()
        if part.isdigit():
            admin_ids.append(int(part))

    return _facade.PolyEdgeBot(token=token, admin_ids=admin_ids)
