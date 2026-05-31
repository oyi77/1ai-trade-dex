import importlib
import os
from typing import List

from backend.core.plugin_errors import PluginEnvVarMissing, PluginNotFound
from backend.core.plugin_registry import PluginRegistry
from backend.core.registry_utils import check_env_vars
from backend.monitoring.backends.base import BaseMetricsBackend, MetricsBackendManifest


class MetricsBackendRegistry(
    PluginRegistry[MetricsBackendManifest, BaseMetricsBackend]
):
    _instance = None

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance.__initialized = False
        return cls._instance

    def __init__(self, name: str = "metrics_backend_registry"):
        if hasattr(self, "__initialized"):
            return
        super().__init__(name="metrics_backend_registry")
        self._health_check_interval = 60.0
        self.__initialized = True

    @classmethod
    def reset(cls) -> None:
        if cls._instance is not None:
            super(MetricsBackendRegistry, cls._instance).reset()
            cls._instance.__initialized = False
            cls._instance = None

    def register(self, backend_class: type) -> None:
        manifest = backend_class.manifest()
        name = manifest.name

        missing = check_env_vars(manifest)
        if missing:
            raise PluginEnvVarMissing(
                f"Metrics backend '{name}' requires env vars: {missing}"
            )

        try:
            instance = backend_class()
            self._plugins[name] = instance
            self._manifests[name] = manifest
            self._enabled[name] = True
            self._health_status[name] = True
        except Exception:
            logger.debug(f"metrics_registry: failed to register backend '{name}'")

    def get(self, name: str) -> BaseMetricsBackend:
        if name not in self._plugins:
            raise PluginNotFound(f"Metrics backend '{name}' not found")
        if not self._enabled.get(name, False):
            raise PluginNotFound(f"Metrics backend '{name}' is disabled")
        if not self._health_status.get(name, False):
            raise PluginNotFound(f"Metrics backend '{name}' is unhealthy")
        return self._plugins[name]

    def list_available(self) -> List[str]:
        return list(self._manifests.keys())

    def list_enabled(self) -> List[str]:
        return [name for name, enabled in self._enabled.items() if enabled]

    def record_metric(
        self, metric_type: str, name: str, value: float, tags: dict = None
    ) -> None:
        import asyncio

        loop = asyncio.new_event_loop()

        async def execute():
            for name, enabled in self._enabled.items():
                if enabled and name in self._plugins:
                    backend = self._plugins[name]
                    if metric_type == "counter":
                        await backend.increment_counter(name, int(value), tags or {})
                    elif metric_type == "gauge":
                        await backend.record_gauge(name, value, tags or {})
                    elif metric_type == "histogram":
                        await backend.record_histogram(name, value, tags or {})

        loop.run_until_complete(execute())
        loop.close()

    async def health_check_all(self) -> dict:
        results = {}
        for name, backend in self._plugins.items():
            try:
                results[name] = await backend.health_check()
            except Exception:
                results[name] = False
        return results

    def auto_discover(self, package_name: str) -> None:
        package = importlib.import_module(package_name)
        package_dir = os.path.dirname(package.__file__)

        for root, dirs, files in os.walk(package_dir):
            for file in files:
                if file.endswith(".py") and not file.startswith("_"):
                    module_name = file[:-3]
                    full_module = f"{package_name}.{module_name}"
                    try:
                        importlib.import_module(full_module)
                    except Exception:
                        logger.debug(f"metrics_registry: failed to auto-discover module '{full_module}'")


registry = MetricsBackendRegistry()


def plugin(cls: type) -> type:
    registry.register(cls)
    return cls
