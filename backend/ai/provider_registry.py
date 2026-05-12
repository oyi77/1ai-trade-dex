"""AI Provider registry for the plugin system."""
from backend.core.plugin_errors import PluginEnvVarMissing, PluginNotFound
from backend.core.plugin_registry import PluginRegistry
from backend.ai.base_provider import BaseAIProvider, ProviderManifest

from backend.models.database import botstate_mutex, BotState
from backend.monitoring.metrics import _metrics_lock, _metrics
import asyncio
import json
import logging
import os
from typing import List

logger = logging.getLogger(__name__)


class ProviderRegistry(PluginRegistry[ProviderManifest, BaseAIProvider]):
    """Singleton registry for AI provider plugins."""

    _instance: "ProviderRegistry" = None

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance.__initialized = False
        return cls._instance

    def __init__(self, name: str = "ai_provider_registry"):
        if hasattr(self, "__initialized"):
            return
        super().__init__(name="ai_provider_registry")
        self._health_check_interval = 60.0
        self._health_check_task = None
        self.__initialized = True

    @classmethod
    def reset(cls) -> None:
        if cls._instance is not None:
            super(ProviderRegistry, cls._instance).reset()
            cls._instance.__initialized = False
            cls._instance = None

    def register(self, provider_class: type) -> None:
        manifest = provider_class.manifest()
        name = manifest.name

        missing = [v for v in manifest.required_env_vars if not os.environ.get(v)]
        if missing:
            raise PluginEnvVarMissing(
                f"AI provider '{name}' requires env vars: {missing}"
            )

        try:
            instance = provider_class()
            self._plugins[name] = instance
            self._manifests[name] = manifest
            self._enabled[name] = True
            self._health_status[name] = True
            logger.info(f"Registered AI provider: {name} v{manifest.version}")
        except Exception as e:
            logger.warning(f"Failed to instantiate AI provider {name}: {e}")

    def get(self, name: str) -> BaseAIProvider:
        if name not in self._plugins:
            raise PluginNotFound(f"AI provider '{name}' not found")
        if not self._enabled.get(name, False):
            raise PluginNotFound(f"AI provider '{name}' is disabled")
        if not self._health_status.get(name, False):
            raise PluginNotFound(f"AI provider '{name}' is unhealthy")
        return self._plugins[name]

    def list_available(self) -> List[ProviderManifest]:
        return [
            self._manifests[n]
            for n in self._plugins
            if self._enabled.get(n, False) and self._health_status.get(n, False)
        ]

    def set_enabled(self, name: str, enabled: bool) -> None:
        if name not in self._plugins:
            from backend.core.plugin_errors import PluginNotFound
            raise PluginNotFound(f"AI provider '{name}' not found")

        self._enabled[name] = enabled
        logger.info(f"AI provider '{name}' {'enabled' if enabled else 'disabled'}")

        async def _set_enabled_async():
            async with botstate_mutex:
                session_factory = self._get_session_factory()
                if session_factory is None:
                    logger.warning("Could not persist provider enabled state: no session factory")
                    return

                with session_factory() as db:
                    bot_state = db.query(BotState).filter_by(mode="paper").first()
                    if bot_state is None:
                        bot_state = BotState(mode="paper", misc_data="{}")
                        db.add(bot_state)

                    misc_data = {}
                    if bot_state.misc_data:
                        try:
                            misc_data = json.loads(bot_state.misc_data)
                        except json.JSONDecodeError:
                            misc_data = {}

                    if "providers" not in misc_data:
                        misc_data["providers"] = {}

                    misc_data["providers"][name] = {"enabled": enabled}

                    bot_state.misc_data = json.dumps(misc_data)
                    db.commit()

        asyncio.run(_set_enabled_async())

    def _get_session_factory(self):
        try:
            from backend.models.database import session_scope
            return session_scope
        except ImportError:
            return None

    async def health_check(self) -> None:
        for name, provider in self._plugins.items():
            try:
                is_healthy = await provider.health_check()
                self._health_status[name] = is_healthy
                if not is_healthy:
                    logger.warning(f"Provider '{name}' failed health check and is marked degraded")
                    with _metrics_lock:
                        _metrics["ai_provider_health_check_failures_total"] = _metrics.get("ai_provider_health_check_failures_total", 0) + 1
            except Exception as e:
                self._health_status[name] = False
                logger.warning(f"Provider '{name}' health check error: {e}")
                with _metrics_lock:
                    _metrics["ai_provider_health_check_failures_total"] = _metrics.get("ai_provider_health_check_failures_total", 0) + 1

    def start_health_check(self) -> None:
        async def _health_check_loop():
            while True:
                await asyncio.sleep(self._health_check_interval)
                await self.health_check()

        self._health_check_task = asyncio.create_task(_health_check_loop())
        logger.info("AI provider health check loop started")

    def stop_health_check(self) -> None:
        if self._health_check_task is not None:
            self._health_check_task.cancel()
            try:
                asyncio.run(self._health_check_task)
            except asyncio.CancelledError:
                pass
            self._health_check_task = None
            logger.info("AI provider health check loop stopped")

    def get_best_provider(self, tags: List[str]) -> BaseAIProvider:
        available = self.list_available()

        if not available:
            return None

        matched = []
        for manifest in available:
            name = manifest.name
            provider_tags = manifest.tags

            if not tags:
                matched.append(name)
            elif any(tag in provider_tags for tag in tags):
                matched.append(name)

        if not matched:
            return None

        for name in matched:
            if self._health_status.get(name, False):
                return self._plugins[name]

        return None

    def auto_discover(self, package_path: str = "backend.ai.providers") -> int:
        count = 0
        try:
            import pkgutil
            import importlib

            package = importlib.import_module(package_path)
            for importer, modname, ispkg in pkgutil.walk_packages(
                package.__path__, prefix=package.__name__ + "."
            ):
                try:
                    importlib.import_module(modname)
                    count += 1
                except Exception as e:
                    logger.warning(f"Failed to import {modname}: {e}")
        except Exception as e:
            logger.error(f"Auto-discover failed for {package_path}: {e}")
        logger.info(f"Auto-discovered {count} AI provider modules")
        return count


provider_registry = ProviderRegistry()
