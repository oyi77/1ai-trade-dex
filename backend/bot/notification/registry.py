from backend.bot.notification.base import BaseNotificationProvider, NotificationManifest
from backend.core.plugin_errors import PluginEnvVarMissing, PluginNotFound
import asyncio
import importlib
import os
import pkgutil
from typing import List, Optional
import logging

logger = logging.getLogger(__name__)


class NotificationRegistry:
    _instance: "NotificationRegistry" = None

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance.__initialized = False
        return cls._instance

    def __init__(self, name: str = "notification_registry"):
        if hasattr(self, "__initialized"):
            return
        self.name = name
        self._plugins: dict[str, BaseNotificationProvider] = {}
        self._manifests: dict[str, NotificationManifest] = {}
        self._enabled: dict[str, bool] = {}
        self._health_status: dict[str, bool] = {}
        self.__initialized = True

    @classmethod
    def reset(cls) -> None:
        if cls._instance is not None:
            cls._instance._plugins.clear()
            cls._instance._manifests.clear()
            cls._instance._enabled.clear()
            cls._instance._health_status.clear()
            cls._instance.__initialized = False
            cls._instance = None

    def plugin(self, cls: type) -> type:
        self.register(cls)
        return cls

    def register(self, plugin_class: type) -> None:
        manifest = plugin_class.manifest()
        name = manifest.name

        if not os.environ.get("SHADOW_MODE") and name != "webhook":
            missing = [v for v in manifest.required_env_vars if not os.environ.get(v)]
            if missing:
                raise PluginEnvVarMissing(f"Notification plugin '{name}' requires env vars: {missing}")

        try:
            instance = plugin_class()
            self._plugins[name] = instance
            self._manifests[name] = manifest
            self._enabled[name] = True
            self._health_status[name] = True
            logger.info(f"Registered notification provider: {name} v{manifest.version}")
        except Exception as e:
            logger.warning(f"Failed to instantiate notification provider {name}: {e}")

    def get(self, name: str) -> BaseNotificationProvider:
        if name not in self._plugins:
            raise PluginNotFound(f"Notification provider '{name}' not found")
        if not self._enabled.get(name, False):
            raise PluginNotFound(f"Notification provider '{name}' is disabled")
        if not self._health_status.get(name, False):
            raise PluginNotFound(f"Notification provider '{name}' is unhealthy")
        return self._plugins[name]

    def list_available(self) -> List[str]:
        return list(self._plugins.keys())

    def get_enabled(self) -> List[str]:
        return [name for name, enabled in self._enabled.items() if enabled]

    def set_enabled(self, name: str, enabled: bool) -> None:
        if name in self._enabled:
            self._enabled[name] = enabled

    def is_enabled(self, name: str) -> bool:
        return self._enabled.get(name, False)

    async def broadcast(self, event_type: str, message: str, details: Optional[dict] = None) -> None:
        for name in self.get_enabled():
            try:
                provider = self._plugins[name]
                await provider.send(message, event_type, details)
            except Exception as e:
                logger.error(f"Failed to send notification via '{name}': {e}")

    async def send_to(self, channel_name: str, event_type: str, message: str, details: Optional[dict] = None) -> bool:
        if channel_name not in self._plugins:
            logger.error(f"Notification provider '{channel_name}' not found")
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

    async def health_check_all(self) -> dict[str, bool]:
        results = {}
        for name, provider in self._plugins.items():
            try:
                results[name] = await provider.health_check()
            except Exception as e:
                logger.error(f"Health check failed for '{name}': {e}")
                results[name] = False
        return results

    async def auto_discover(self, package_path: str = "backend.bot.notification.providers") -> None:
        package = importlib.import_module(package_path)
        for _, name, _ in pkgutil.iter_modules(package.__path__):
            try:
                module = importlib.import_module(f"{package_path}.{name}")
                for attr_name in dir(module):
                    attr = getattr(module, attr_name)
                    if (
                        isinstance(attr, type)
                        and issubclass(attr, BaseNotificationProvider)
                        and attr != BaseNotificationProvider
                    ):
                        self.register(attr)
            except Exception as e:
                logger.warning(f"Failed to auto-discover provider '{name}': {e}")


registry = NotificationRegistry()
