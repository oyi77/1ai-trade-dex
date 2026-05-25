from backend.bot.notification.base import BaseNotificationProvider, NotificationManifest
from backend.bot.notification.registry import registry
from backend.bot.notifier import get_bot
from backend.config import settings
from backend.core.circuit_breaker import CircuitBreaker
from backend.core.external_rate_limiter import ExternalRateLimiter
from backend.core.errors import CircuitOpenError
from typing import Optional
import logging

logger = logging.getLogger(__name__)

# Circuit breaker for Telegram API — protects against cascading failures
_telegram_breaker = CircuitBreaker(
    "telegram_api", failure_threshold=settings.CB_FAILURE_THRESHOLD, recovery_timeout=settings.CB_RECOVERY_TIMEOUT
)

# Rate limiter for Telegram API — respects ~30 msg/sec global limit
_telegram_rate_limiter = ExternalRateLimiter(
    name="telegram",
    max_calls_per_minute=1800,
    circuit_breaker=_telegram_breaker,
)


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

    async def send(
        self, message: str, event_type: str, details: Optional[dict] = None
    ) -> bool:
        if not self.bot_instance:
            return False
        try:
            await _telegram_rate_limiter.call(
                self.bot_instance.send_telegram_message, message
            )
            return True
        except CircuitOpenError:
            logger.warning("Telegram circuit OPEN, notification dropped")
            return False
        except Exception as e:
            logger.error(f"Telegram send failed: {e}")
            return False

    async def health_check(self) -> bool:
        if not self.bot_instance or not self.bot_instance.token:
            return False
        try:
            await _telegram_breaker.call(self.bot_instance._bot.get_me)
            return True
        except CircuitOpenError:
            logger.warning("Telegram circuit OPEN during health check")
            return False
        except Exception:
            logger.warning("Telegram health check failed", exc_info=True)
            return False
