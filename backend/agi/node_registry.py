"""Node registry for the AGI plugin system."""
import asyncio
import logging
from typing import List, Optional

from backend.core.plugin_registry import PluginRegistry
from backend.agi.base_node import NodeManifest, BaseAGINode

logger = logging.getLogger(__name__)


class NodeRegistry(PluginRegistry[NodeManifest, BaseAGINode]):
    """Singleton registry for AGI node plugins."""

    _instance: Optional["NodeRegistry"] = None

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance.__initialized = False
        return cls._instance

    def __init__(self, name: str = "node_registry"):
        if self.__initialized:
            return
        super().__init__(name="node_registry")
        self._health_check_interval = 30.0
        self.__initialized = True

    @classmethod
    def reset(cls) -> None:
        if cls._instance is not None:
            super(NodeRegistry, cls._instance).reset()
            cls._instance.__initialized = False
            cls._instance = None

    def register(self, node_class: type) -> None:
        """Register an AGI node class."""
        manifest = node_class.manifest()
        name = manifest.name
        try:
            instance = node_class()
            self._plugins[name] = instance
            self._manifests[name] = manifest
            self._enabled[name] = True
            self._health_status[name] = True
            logger.info(f"Registered AGI node: {name} v{manifest.version}")
        except Exception as e:
            logger.warning(f"Failed to instantiate AGI node {name}: {e}")

    def get(self, name: str) -> BaseAGINode:
        """Get a node by name."""
        if name not in self._plugins:
            raise KeyError(f"AGI node '{name}' not found")
        if not self._enabled.get(name, False):
            raise KeyError(f"AGI node '{name}' is disabled")
        return self._plugins[name]

    def list_all(self) -> List[NodeManifest]:
        """Return manifests of all enabled nodes."""
        return [
            self._manifests[n]
            for n in self._plugins
            if self._enabled.get(n, False)
        ]

    def auto_discover(self, package_path: str = "backend.agi.nodes") -> int:
        """Import all modules in the nodes directory."""
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
        logger.info(f"Auto-discovered {count} AGI node modules")
        return count

    async def run_health_checks(self) -> dict:
        """Run health checks on all registered nodes."""
        results = {}
        for name, plugin in self._plugins.items():
            if not self._enabled.get(name, False):
                results[name] = False
                continue
            try:
                healthy = await plugin.health_check()
                self._health_status[name] = healthy
                results[name] = healthy
            except Exception as e:
                self._health_status[name] = False
                results[name] = False
                logger.error(f"AGI node health check exception for {name}: {e}")
        return results

    async def start_health_check_loop(self, interval: float = 30.0) -> None:
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
        logger.info(f"AGI node health check loop started (interval={interval}s)")


# Module-level singleton
node_registry = NodeRegistry()
