"""Market provider registry for the plugin system."""

import asyncio
import logging
import os
from typing import List, Optional

from backend.core.plugin_errors import (
    MarketProviderNotFound,
    PluginEnvVarMissing,
)
from backend.core.plugin_registry import PluginRegistry
from backend.markets.base_provider import BaseMarketProvider, MarketProviderManifest

logger = logging.getLogger(__name__)


class MarketProviderRegistry(
    PluginRegistry[MarketProviderManifest, BaseMarketProvider]
):
    """Singleton registry for market (trading venue) provider plugins."""

    _instance: Optional["MarketProviderRegistry"] = None

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance.__initialized = False
        return cls._instance

    def __init__(self, name: str = "market_provider_registry"):
        if self.__initialized:
            return
        super().__init__(name="market_provider_registry")
        self._health_check_interval = 15.0
        self.__initialized = True

    @classmethod
    def reset(cls) -> None:
        if cls._instance is not None:
            super(MarketProviderRegistry, cls._instance).reset()
            cls._instance.__initialized = False
            cls._instance = None

    def register(self, provider_class: type) -> None:
        """Register a market provider class. Validates manifest and checks env vars."""
        manifest = provider_class.manifest()
        name = manifest.name

        missing = [v for v in manifest.required_env_vars if not os.environ.get(v)]
        if missing:
            raise PluginEnvVarMissing(
                f"Missing required environment variables for provider {name}: {', '.join(missing)}"
            )

        try:
            # Inject paper_mode based on TRADING_MODE env var
            paper_mode = os.environ.get("TRADING_MODE", "paper") != "live"
            instance = provider_class(paper_mode=paper_mode)
            self._plugins[name] = instance
            self._manifests[name] = manifest
            self._enabled[name] = True
            self._health_status[name] = True
            logger.info(
                f"Registered market provider: {name} v{manifest.version} (paper_mode={paper_mode})"
            )
        except Exception as e:
            logger.warning(f"Failed to instantiate market provider {name}: {e}")

    def get(self, name: str) -> BaseMarketProvider:
        """Get a market provider by name."""
        if name not in self._plugins:
            raise MarketProviderNotFound(f"Market provider '{name}' not found")
        if not self._enabled.get(name, False):
            raise MarketProviderNotFound(f"Market provider '{name}' is disabled")
        if not self._health_status.get(name, False):
            raise MarketProviderNotFound(f"Market provider '{name}' is unhealthy")
        return self._plugins[name]

    def get_live_venues(self) -> List[BaseMarketProvider]:
        """Return only live venue providers that are healthy."""
        return [
            p
            for n, p in self._plugins.items()
            if self._enabled.get(n, False)
            and self._health_status.get(n, False)
            and self._manifests[n].is_live_venue
        ]

    def get_paper_venues(self) -> List[BaseMarketProvider]:
        """Return only paper/sandbox providers."""
        return [
            p
            for n, p in self._plugins.items()
            if self._enabled.get(n, False) and not self._manifests[n].is_live_venue
        ]

    def get_for_capability(self, capability: str) -> List[BaseMarketProvider]:
        """Return all healthy providers with a specific capability."""
        results = []
        for name, plugin in self._plugins.items():
            if not self._enabled.get(name, False):
                continue
            if not self._health_status.get(name, False):
                continue
            manifest = self._manifests[name]
            if capability in manifest.capabilities:
                results.append(plugin)
        return results

    def list_all(self) -> List[MarketProviderManifest]:
        """Return manifests of all healthy, enabled providers."""
        return [
            self._manifests[n]
            for n in self._plugins
            if self._enabled.get(n, False) and self._health_status.get(n, False)
        ]

    def set_enabled(self, name: str, enabled: bool, force: bool = False) -> None:
        """Enable or disable a provider at runtime.

        Before disabling a live provider, check for open positions.
        """
        from backend.core.plugin_errors import MarketProviderHasOpenPositions

        if name not in self._plugins:
            raise MarketProviderNotFound(f"Market provider '{name}' not found")

        if not enabled and not force:
            # Check for open positions before disabling
            try:
                provider = self._plugins[name]
                positions = asyncio.get_event_loop().run_until_complete(
                    provider.get_positions()
                )
                if positions:
                    raise MarketProviderHasOpenPositions(
                        f"Cannot disable '{name}': {len(positions)} open positions. "
                        f"Use force=True to override."
                    )
            except Exception as exc:
                logger.debug(
                    "Provider position check failed while disabling %s: %s", name, exc
                )

        self._enabled[name] = enabled
        logger.info(f"Market provider '{name}' {'enabled' if enabled else 'disabled'}")

    def auto_discover(self, package_path: str = "backend.markets.providers") -> int:
        """Import all modules in the providers directory."""
        import pkgutil
        import importlib

        count = 0
        try:
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
        logger.info(f"Auto-discovered {count} market provider modules")
        return count

    async def run_health_checks(self) -> dict:
        """Run health checks on all registered providers."""
        results = {}
        for name, plugin in self._plugins.items():
            if not self._enabled.get(name, False):
                results[name] = False
                continue
            try:
                healthy = await plugin.health_check()
                self._health_status[name] = healthy
                results[name] = healthy
                if not healthy:
                    logger.warning(f"Market provider health check failed: {name}")
            except Exception as e:
                self._health_status[name] = False
                results[name] = False
                logger.error(f"Market provider health check exception for {name}: {e}")
        return results

    async def start_health_check_loop(self, interval: float = 15.0) -> None:
        """Start background health check loop."""
        self._health_check_interval = interval

        async def _loop():
            while True:
                try:
                    await self.run_health_checks()
                except Exception as e:
                    logger.error(f"Health check loop error: {e}")
                await asyncio.sleep(interval)

        asyncio.create_task(_loop())
        logger.info(f"Market provider health check loop started (interval={interval}s)")


# Module-level singleton
market_registry = MarketProviderRegistry()
