from backend.bot.notification.base import BaseNotificationProvider, NotificationManifest
from backend.bot.notification.registry import registry
from backend.bot.notifier import get_bot
from typing import Optional
import logging

logger = logging.getLogger(__name__)


@registry.plugin
class TelegramProvider(BaseNotificationProvider):
    @classmethod
    def manifest(cls) -> NotificationManifest:
        return NotificationManifest(
            name="telegram",
            display_name="Telegram",
            version="1.0.0",
            required_env_vars=["TELEGRAM_BOT_TOKEN"],
            tags=["messaging", "alerts"],
        )

    def __init__(self):
        self.bot_instance = get_bot()

    async def send(self, message: str, event_type: str, details: Optional[dict] = None) -> bool:
        if not self.bot_instance:
            return False
        try:
            await self.bot_instance.send_telegram_message(message)
            return True
        except Exception as e:
            logger.error(f"Telegram send failed: {e}")
            return False

    async def health_check(self) -> bool:
        if not self.bot_instance or not self.bot_instance.token:
            return False
        try:
            await self.bot_instance._bot.get_me()
            return True
        except Exception:
            return False
