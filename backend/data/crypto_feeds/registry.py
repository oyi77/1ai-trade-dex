from __future__ import annotations

import logging
from typing import Dict, List, Optional

from backend.core.plugin_registry import PluginRegistry
from backend.core.registry_utils import check_env_vars
from backend.data.crypto_feeds.base import ExchangeFeedManifest, BaseExchangeFeed

logger = logging.getLogger(__name__)

_registry: Optional[ExchangeFeedRegistry] = None


class ExchangeFeedRegistry(PluginRegistry[ExchangeFeedManifest, BaseExchangeFeed]):
    _instance: Optional["ExchangeFeedRegistry"] = None

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance.__initialized = False
        return cls._instance

    def __init__(self, name: str = "exchange_feed_registry"):
        if self.__initialized:
            return
        super().__init__(name="exchange_feed_registry")
        self._health_check_interval = 60.0
        self.__initialized = True

    @classmethod
    def reset(cls) -> None:
        if cls._instance is not None:
            super(ExchangeFeedRegistry, cls._instance).reset()
            cls._instance.__initialized = False
            cls._instance = None

    def register(self, feed_class: type) -> None:
        manifest = feed_class.manifest()
        name = manifest.name

        from backend.core.plugin_errors import PluginEnvVarMissing

        missing = check_env_vars(manifest)
        if missing:
            raise PluginEnvVarMissing(
                f"Exchange feed '{name}' requires env vars: {missing}"
            )

        try:
            instance = feed_class()
            self._plugins[name] = instance
            self._manifests[name] = manifest
            self._enabled[name] = True
            self._health_status[name] = True
            logger.info(f"Registered exchange feed: {name} v{manifest.version}")
        except Exception as e:
            logger.warning(f"Failed to instantiate exchange feed {name}: {e}")

    def get_price(self, feed_name: Optional[str] = None) -> Optional[float]:
        if feed_name is not None:
            if feed_name not in self._plugins:
                return None
            if not self._enabled.get(feed_name, False):
                return None
            if not self._health_status.get(feed_name, False):
                return None
            plugin = self._plugins[feed_name]
            import asyncio

            loop = asyncio.new_event_loop()
            try:
                asyncio.set_event_loop(loop)
                return loop.run_until_complete(plugin.get_btc_price())
            except Exception:
                return None
            finally:
                loop.close()

        healthy_feeds = self.get_fallback_chain()
        if not healthy_feeds:
            return None

        import asyncio

        loop = asyncio.new_event_loop()
        try:
            asyncio.set_event_loop(loop)
            for feed in healthy_feeds:
                plugin = self._plugins[feed]
                try:
                    price = loop.run_until_complete(plugin.get_btc_price())
                    if price and price > 0:
                        return price
                except Exception:
                    continue
            return None
        finally:
            loop.close()

    def get_fallback_chain(self) -> List[str]:
        healthy = []
        for name in self._plugins:
            if self._enabled.get(name, False) and self._health_status.get(name, False):
                healthy.append(name)
        return healthy

    def get_health_status(self) -> Dict[str, bool]:
        return self._health_status.copy()


def get_registry() -> ExchangeFeedRegistry:
    global _registry
    if _registry is None:
        _registry = ExchangeFeedRegistry()
    return _registry


def reset_registry() -> None:
    global _registry
    if _registry is not None:
        _registry.reset()
        _registry = None
