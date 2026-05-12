import pytest
import os
from unittest.mock import AsyncMock, patch

from backend.monitoring.backends.base import BaseMetricsBackend, MetricsBackendManifest
from backend.monitoring.backends.registry import registry
from backend.core.plugin_errors import PluginEnvVarMissing, PluginNotFound


class MockBackend(BaseMetricsBackend):
    @classmethod
    def manifest(cls) -> MetricsBackendManifest:
        return MetricsBackendManifest(
            name="mock_backend",
            display_name="Mock Backend",
            version="1.0.0",
            required_env_vars=[],
            tags=["test"],
        )

    async def increment_counter(self, name: str, value: int = 1, tags: dict = None) -> None:
        pass

    async def record_gauge(self, name: str, value: float, tags: dict = None) -> None:
        pass

    async def record_histogram(self, name: str, value: float, tags: dict = None) -> None:
        pass


class EnvBackend(BaseMetricsBackend):
    @classmethod
    def manifest(cls) -> MetricsBackendManifest:
        return MetricsBackendManifest(
            name="env_backend",
            display_name="Env Backend",
            version="1.0.0",
            required_env_vars=["TEST_METRICS_API_KEY"],
            tags=["test"],
        )

    async def increment_counter(self, name: str, value: int = 1, tags: dict = None) -> None:
        pass

    async def record_gauge(self, name: str, value: float, tags: dict = None) -> None:
        pass

    async def record_histogram(self, name: str, value: float, tags: dict = None) -> None:
        pass


@pytest.fixture(autouse=True)
def cleanup_registry():
    registry.reset()
    yield
    registry.reset()


def test_register_valid_backend():
    registry.register(MockBackend)
    assert "mock_backend" in registry._plugins
    assert registry._enabled["mock_backend"] is True


def test_register_backend_missing_env_vars():
    if "TEST_METRICS_API_KEY" in os.environ:
        del os.environ["TEST_METRICS_API_KEY"]
    with pytest.raises(PluginEnvVarMissing):
        registry.register(EnvBackend)


def test_record_metric_broadcasts_to_all():
    registry.register(MockBackend)
    
    with patch.object(MockBackend, "increment_counter", new_callable=AsyncMock) as mock_method:
        registry.record_metric("counter", "test_metric", 10)
    
    assert mock_method.called


def test_disabled_backend_skipped():
    registry.register(MockBackend)
    registry._enabled["mock_backend"] = False
    
    with patch.object(MockBackend, "increment_counter", new_callable=AsyncMock) as mock_method:
        registry.record_metric("counter", "test_metric", 10)
    
    assert not mock_method.called


def test_get_backend():
    registry.register(MockBackend)
    backend = registry.get("mock_backend")
    assert isinstance(backend, MockBackend)


def test_get_backend_not_found():
    with pytest.raises(PluginNotFound):
        registry.get("nonexistent")


def test_list_available():
    registry.register(MockBackend)
    backends = registry.list_available()
    assert "mock_backend" in backends


def test_list_enabled():
    registry.register(MockBackend)
    registry._enabled["mock_backend"] = False
    enabled = registry.list_enabled()
    assert "mock_backend" not in enabled


def test_auto_discover():
    os.environ["DATADOG_API_KEY"] = "test-key"
    os.environ["AWS_ACCESS_KEY_ID"] = "test"
    os.environ["AWS_SECRET_ACCESS_KEY"] = "test-secret"
    
    registry.reset()
    registry.auto_discover("backend.monitoring.backends")
    backends = registry.list_available()
    assert "datadog" in backends
    assert "cloudwatch" in backends


def test_health_check_all():
    import asyncio
    
    async def async_test():
        result = await registry.health_check_all()
        assert isinstance(result, dict)
    
    asyncio.run(async_test())
