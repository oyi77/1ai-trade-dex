from backend.bot.notification.base import BaseNotificationProvider, NotificationManifest
from backend.bot.notification.registry import registry
import logging
import os
from typing import Optional
import httpx

logger = logging.getLogger(__name__)


@registry.plugin
class SlackProvider(BaseNotificationProvider):
    @classmethod
    def manifest(cls) -> NotificationManifest:
        return NotificationManifest(
            name="slack",
            display_name="Slack",
            version="1.0.0",
            required_env_vars=["SLACK_WEBHOOK_URL"],
            tags=["messaging", "alerts"],
        )

    async def send(self, message: str, event_type: str, details: Optional[dict] = None) -> bool:
        webhook_url = os.environ.get("SLACK_WEBHOOK_URL")
        if not webhook_url:
            return False
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    webhook_url,
                    json={"text": message},
                    headers={"Content-Type": "application/json"},
                    timeout=10.0,
                )
                return response.status_code == 200
        except Exception as e:
            logger.error(f"Slack send failed: {e}")
            return False
