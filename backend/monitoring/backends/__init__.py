from backend.monitoring.backends.base import BaseMetricsBackend, MetricsBackendManifest
from backend.monitoring.backends.registry import registry, plugin, MetricsBackendRegistry

registry.auto_discover("backend.monitoring.backends")

__all__ = [
    "BaseMetricsBackend",
    "MetricsBackendManifest",
    "registry",
    "plugin",
    "MetricsBackendRegistry",
]
