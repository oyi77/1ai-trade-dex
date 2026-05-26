"""Notification registry — inherits from PluginRegistry for multi-channel notifications."""

import logging
from typing import Optional, List

from backend.bot.notification.base import BaseNotificationProvider, NotificationManifest
from backend.core.plugin_registry import PluginRegistry

logger = logging.getLogger(__name__)


class NotificationRegistry(PluginRegistry[NotificationManifest, BaseNotificationProvider]):
    """Singleton registry for notification providers (Telegram, Discord, Slack, Webhook).

    Inherits register(), get(), set_enabled(), auto_discover(), run_health_checks()
    from PluginRegistry. Adds broadcast(), send_to(), and send_alert() convenience methods.
    """

    _instance: Optional["NotificationRegistry"] = None

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance.__initialized = False
        return cls._instance

    def __init__(self, name: str = "notification_registry"):
        if self.__initialized:
            return
        super().__init__(name=name, health_interval=120.0, env_var_check=False)
        self.__initialized = True

    @classmethod
    def reset(cls) -> None:
        import threading
        with threading.Lock():
            if cls._instance is not None:
                cls._instance._plugins.clear()
                cls._instance._manifests.clear()
                cls._instance._enabled.clear()
                cls._instance._health_status.clear()
                cls._instance.__initialized = False
                cls._instance = None

    def get_enabled(self) -> List[str]:
        return [name for name, enabled in self._enabled.items() if enabled]

    def is_enabled(self, name: str) -> bool:
        return self._enabled.get(name, False)

    async def broadcast(
        self, event_type: str, message: str, details: Optional[dict] = None
    ) -> None:
        """Send to all enabled providers."""
        for name in self.get_enabled():
            try:
                provider = self._plugins[name]
                await provider.send(message, event_type, details)
            except Exception as e:
                logger.error(f"Failed to send notification via '{name}': {e}")

    async def send_to(
        self,
        channel_name: str,
        event_type: str,
        message: str,
        details: Optional[dict] = None,
    ) -> bool:
        """Send to a specific channel."""
        if channel_name not in self._plugins:
            logger.debug(f"Notification provider '{channel_name}' not found")
            return False
        if not self._enabled.get(channel_name, False):
            logger.warning(f"Notification provider '{channel_name}' is disabled")
            return False
        if not self._health_status.get(channel_name, False):
            logger.error(f"Notification provider '{channel_name}' is unhealthy")
            return False

        try:
            provider = self._plugins[channel_name]
            await provider.send(message, event_type, details)
            return True
        except Exception as e:
            logger.error(f"Failed to send notification via '{channel_name}': {e}")
            return False

    # ── Backward-compatible aliases ──

    def list_available(self) -> List[str]:
        """Legacy alias — returns list of enabled provider names."""
        return self.get_enabled()

    async def health_check_all(self) -> dict:
        """Legacy alias for run_health_checks."""
        return await self.run_health_checks()

    async def send_alert(
        self, title: str = "", message: str = "", level: str = "info"
    ) -> bool:
        """Convenience method for alert notifications. Fixes broken imports."""
        return await self.send_to(
            "telegram", level, f"{title}\n{message}" if title else message
        )

    async def auto_discover(
        self, package_path: str = "backend.bot.notification.providers"
    ) -> None:
        """Auto-discover notification providers via base PluginRegistry.auto_discover."""
        self._auto_discover(package_path)


registry = NotificationRegistry()
