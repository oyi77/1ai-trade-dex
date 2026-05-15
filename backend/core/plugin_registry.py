"""Generic plugin registry base classes and utilities."""
import asyncio
import importlib
import logging
import os
import pkgutil
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Generic, List, Optional, TypeVar, Dict, Set

logger = logging.getLogger(__name__)

T_Manifest = TypeVar("T_Manifest")
T_Plugin = TypeVar("T_Plugin")


@dataclass
class BaseManifest:
    """Base manifest dataclass for all plugin types."""
    name: str = ""
    version: str = "1.0.0"
    required_env_vars: List[str] = field(default_factory=list)
    tags: List[str] = field(default_factory=list)


class BasePlugin(ABC):
    """Abstract base class for all plugin types."""

    @classmethod
    @abstractmethod
    def manifest(cls) -> BaseManifest:
        """Return the plugin's static metadata."""
        ...

    async def health_check(self) -> bool:
        """Optional liveness probe. Default: return True."""
        return True

    async def teardown(self) -> None:
        """Called when the plugin is detached. Close connections, flush caches."""
        pass


class PluginRegistry(Generic[T_Manifest, T_Plugin]):
    """Generic plugin registry with auto-discovery and health monitoring.

    Type parameters:
        T_Manifest: the manifest dataclass (ProviderManifest, DataSourceManifest, etc.)
        T_Plugin: the base plugin class (BaseAIProvider, BaseDataSource, etc.)
    """

    def __init__(self, name: str = "plugin_registry"):
        self.name = name
        self._plugins: Dict[str, T_Plugin] = {}
        self._manifests: Dict[str, T_Manifest] = {}
        self._enabled: Dict[str, bool] = {}
        self._health_status: Dict[str, bool] = {}
        self._health_check_task: Optional[asyncio.Task] = None
        self._health_check_interval: float = 60.0

    def plugin(self, cls: type) -> type:
        """Decorator that registers a class with this registry at import time."""
        self.register(cls)
        return cls

    def register(self, plugin_class: type) -> None:
        """Register a plugin class. Validates manifest and checks env vars."""
        manifest = plugin_class.manifest()
        name = manifest.name

        # Check required env vars
        from backend.core.plugin_errors import PluginEnvVarMissing
        import os
        missing = [v for v in manifest.required_env_vars if not os.environ.get(v)]
        if missing:
            raise PluginEnvVarMissing(
                f"Plugin '{name}' requires env vars: {missing}"
            )

        # Instantiate and store
        try:
            instance = plugin_class()
            self._plugins[name] = instance
            self._manifests[name] = manifest
            self._enabled[name] = True
            self._health_status[name] = True
            logger.info(f"Registered plugin: {name} v{manifest.version}")
        except Exception as e:
            logger.warning(f"Failed to instantiate plugin {name}: {e}")

    def get(self, name: str) -> T_Plugin:
        """Get a plugin by name. Raises PluginNotFound if missing or disabled."""
        from backend.core.plugin_errors import PluginNotFound
        if name not in self._plugins:
            raise PluginNotFound(f"Plugin '{name}' not found in {self.name}")
        if not self._enabled.get(name, False):
            raise PluginNotFound(f"Plugin '{name}' is disabled")
        if not self._health_status.get(name, False):
            raise PluginNotFound(f"Plugin '{name}' is unhealthy")
        return self._plugins[name]

    def list_all(self) -> List[T_Manifest]:
        """Return manifests of all enabled, healthy plugins."""
        return [
            self._manifests[n]
            for n in self._plugins
            if self._enabled.get(n, False) and self._health_status.get(n, False)
        ]

    def set_enabled(self, name: str, enabled: bool) -> None:
        """Enable or disable a plugin at runtime."""
        if name not in self._plugins:
            from backend.core.plugin_errors import PluginNotFound
            raise PluginNotFound(f"Plugin '{name}' not found")
        self._enabled[name] = enabled
        logger.info(f"Plugin '{name}' {'enabled' if enabled else 'disabled'}")

    def auto_discover(self, package_path: str) -> int:
        """Import all modules in a package directory to trigger registration.

        Returns the number of plugins registered.
        """
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
        logger.info(f"Auto-discovered {count} modules in {package_path}")
        return count

    async def run_health_checks(self) -> Dict[str, bool]:
        """Run health checks on all registered plugins."""
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
                    logger.warning(f"Health check failed for plugin: {name}")
            except Exception as e:
                self._health_status[name] = False
                results[name] = False
                logger.error(f"Health check exception for {name}: {e}")
        return results

    async def start_health_check_loop(self, interval: float = 60.0) -> None:
        """Start background health check loop."""
        self._health_check_interval = interval

        async def _loop():
            while True:
                try:
                    await self.run_health_checks()
                except Exception as e:
                    logger.error(f"Health check loop error: {e}")
                await asyncio.sleep(interval)

        self._health_check_task = asyncio.create_task(_loop())
        logger.info(f"Health check loop started (interval={interval}s)")

    async def stop_health_check_loop(self) -> None:
        """Stop the background health check loop."""
        if self._health_check_task:
            self._health_check_task.cancel()
            try:
                await self._health_check_task
            except asyncio.CancelledError:
                pass
            self._health_check_task = None

    def reset(self) -> None:
        self._plugins.clear()
        self._manifests.clear()
        self._enabled.clear()
        self._health_status.clear()
        self._health_check_task = None
