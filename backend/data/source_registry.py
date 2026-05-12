"""Data source registry for the plugin system."""
import asyncio
import json
import logging
import os
from typing import List, Optional

from backend.core.plugin_errors import PluginEnvVarMissing, PluginNotFound
from backend.core.plugin_registry import PluginRegistry
from backend.data.base_source import BaseDataSource, DataSourceManifest, DataType
from backend.models.database import BotState, get_db

logger = logging.getLogger(__name__)

try:
    from prometheus_client import Counter

    PROMETHEUS_AVAILABLE = True
    data_source_health_check_failures_total = Counter(
        "data_source_health_check_failures_total",
        "Total number of data source health check failures",
    )
except ImportError:
    PROMETHEUS_AVAILABLE = False
    data_source_health_check_failures_total = None


class DataSourceRegistry(PluginRegistry[DataSourceManifest, BaseDataSource]):
    """Singleton registry for data source plugins."""

    _instance: Optional["DataSourceRegistry"] = None

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance.__initialized = False
        return cls._instance

    def __init__(self, name: str = "data_source_registry"):
        if self.__initialized:
            return
        super().__init__(name="data_source_registry")
        self._health_check_interval = 30.0
        self.__initialized = True

    @classmethod
    def reset(cls) -> None:
        if cls._instance is not None:
            super(DataSourceRegistry, cls._instance).reset()
            cls._instance.__initialized = False
            cls._instance = None

    def register(self, source_class: type) -> None:
        """Register a data source class. Validates manifest and checks env vars."""
        manifest = source_class.manifest()
        name = manifest.name

        missing = [v for v in manifest.required_env_vars if not os.environ.get(v)]
        if missing:
            raise PluginEnvVarMissing(
                f"Data source '{name}' requires env vars: {missing}"
            )

        try:
            instance = source_class()
            self._plugins[name] = instance
            self._manifests[name] = manifest
            self._enabled[name] = True
            self._health_status[name] = True
            logger.info(f"Registered data source: {name} v{manifest.version}")
        except Exception as e:
            logger.warning(f"Failed to instantiate data source {name}: {e}")

    def get(self, name: str) -> BaseDataSource:
        """Get a data source by name."""
        if name not in self._plugins:
            raise PluginNotFound(f"Data source '{name}' not found")
        if not self._enabled.get(name, False):
            raise PluginNotFound(f"Data source '{name}' is disabled")
        if not self._health_status.get(name, False):
            raise PluginNotFound(f"Data source '{name}' is unhealthy")
        return self._plugins[name]

    def get_for_type(
        self, data_type: DataType
    ) -> List[BaseDataSource]:
        """Return all healthy sources that provide this data type, sorted by priority."""
        results = []
        for name, plugin in self._plugins.items():
            if not self._enabled.get(name, False):
                continue
            if not self._health_status.get(name, False):
                continue
            manifest = self._manifests[name]
            if data_type in manifest.data_types:
                results.append(plugin)
        # Sort by whether "primary" tag exists (sources with "primary" first)
        results.sort(key=lambda p: "primary" not in self._manifests[
            list(self._plugins.keys())[list(self._plugins.values()).index(p)]
        ].tags)
        return results

    def list_all(self) -> List[DataSourceManifest]:
        """Return all manifests (enabled and disabled)."""
        return list(self._manifests.values())

    def set_enabled(self, name: str, enabled: bool) -> None:
        """Enable or disable a data source and persist to BotState."""
        if name not in self._plugins:
            raise PluginNotFound(f"Data source '{name}' not found")
        self._enabled[name] = enabled
        logger.info(f"Data source '{name}' {'enabled' if enabled else 'disabled'}")

        db = next(get_db())
        try:
            state = db.query(BotState).filter(BotState.mode == "paper").first()
            if not state:
                state = BotState(mode="paper", misc_data={})
                db.add(state)
                db.commit()

            misc = json.loads(state.misc_data) if state.misc_data else {}
            if "data_sources" not in misc:
                misc["data_sources"] = {}

            misc["data_sources"][name] = {"enabled": enabled}
            state.misc_data = json.dumps(misc)
            db.commit()
            logger.info(f"Persisted data source '{name}' enabled={enabled} to BotState")
        except Exception as e:
            logger.error(f"Failed to persist data source state for '{name}': {e}")
            db.rollback()
        finally:
            db.close()

    def auto_discover(self, package_path: str = "backend.data.sources") -> int:
        """Import all modules in the sources directory."""
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
        logger.info(f"Auto-discovered {count} data source modules")
        return count

    async def run_health_checks(self) -> dict:
        """Run health checks on all registered sources."""
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
                    logger.warning(f"Data source health check failed: {name}")
                    if PROMETHEUS_AVAILABLE and data_source_health_check_failures_total:
                        data_source_health_check_failures_total.inc()
            except Exception as e:
                self._health_status[name] = False
                results[name] = False
                logger.error(f"Data source health check exception for {name}: {e}")
                if PROMETHEUS_AVAILABLE and data_source_health_check_failures_total:
                    data_source_health_check_failures_total.inc()
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
        logger.info(f"Data source health check loop started (interval={interval}s)")


# Module-level singleton
source_registry = DataSourceRegistry()