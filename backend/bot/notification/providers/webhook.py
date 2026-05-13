from backend.bot.notification.base import BaseNotificationProvider, NotificationManifest
from backend.bot.notification.registry import registry
import logging
import os
from typing import Optional
import httpx

logger = logging.getLogger(__name__)


@registry.plugin
class GenericWebhookProvider(BaseNotificationProvider):
    @classmethod
    def manifest(cls) -> NotificationManifest:
        return NotificationManifest(
            name="webhook",
            display_name="Generic Webhook",
            version="1.0.0",
            required_env_vars=["WEBHOOK_URL"],
            tags=["messaging", "alerts"],
        )

    async def send(self, message: str, event_type: str, details: Optional[dict] = None) -> bool:
        webhook_url = os.environ.get("WEBHOOK_URL")
        if not webhook_url:
            return False
        payload = {
            "message": message,
            "event_type": event_type,
        }
        if details:
            payload["details"] = details
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    webhook_url,
                    json=payload,
                    headers={"Content-Type": "application/json"},
                    timeout=10.0,
                )
                return response.status_code >= 200 and response.status_code < 300
        except Exception as e:
            logger.error(f"Generic webhook send failed: {e}")
            return False
