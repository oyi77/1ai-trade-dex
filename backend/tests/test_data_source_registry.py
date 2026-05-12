"""Test suite for data source registry."""
import pytest

from backend.data.base_source import BaseDataSource, DataSourceManifest, DataType
from backend.data.source_registry import DataSourceRegistry
from backend.core.plugin_errors import PluginEnvVarMissing, PluginNotFound


class MockDataSource(BaseDataSource):
    """Test data source with no required env vars."""

    @classmethod
    def manifest(cls):
        return DataSourceManifest(
            name="mock_source",
            display_name="Mock Source",
            version="1.0.0",
            data_types=[DataType.PRICE, DataType.CANDLES],
            supports_streaming=False,
            supports_backfill=False,
            required_env_vars=[],
            tags=["test"],
        )

    async def fetch(self, data_type, params=None):
        return {"data": "mock"}


class EnvDataSource(BaseDataSource):
    """Test data source requiring env vars."""

    @classmethod
    def manifest(cls):
        return DataSourceManifest(
            name="env_source",
            display_name="Env Source",
            version="1.0.0",
            data_types=[DataType.PRICE],
            required_env_vars=["TEST_API_KEY"],
            tags=["test"],
        )

    async def fetch(self, data_type, params=None):
        return {"data": "env"}


def test_register_valid_source():
    """Register valid data source succeeds."""
    registry = DataSourceRegistry("test_registry")
    registry.register(MockDataSource)
    assert "mock_source" in registry._plugins
    assert registry._enabled["mock_source"] is True


def test_register_invalid_env_var():
    """Register source with missing env var raises PluginEnvVarMissing."""
    registry = DataSourceRegistry("test_registry")
    with pytest.raises(PluginEnvVarMissing):
        registry.register(EnvDataSource)


def test_get_for_type():
    """get_for_type filters sources by data type."""
    registry = DataSourceRegistry("test_registry")
    registry.register(MockDataSource)

    sources = registry.get_for_type(DataType.PRICE)
    assert len(sources) == 1
    assert sources[0].manifest().name == "mock_source"

    # Request type not supported
    sources = registry.get_for_type(DataType.WEATHER)
    assert len(sources) == 0


def test_set_enabled_persists():
    """Set enabled/disabled updates state."""
    registry = DataSourceRegistry("test_registry")
    registry.register(MockDataSource)

    registry.set_enabled("mock_source", False)
    assert registry._enabled["mock_source"] is False

    registry.set_enabled("mock_source", True)
    assert registry._enabled["mock_source"] is True


def test_get_missing_source():
    """Getting missing source raises PluginNotFound."""
    registry = DataSourceRegistry("test_registry")
    with pytest.raises(PluginNotFound):
        registry.get("nonexistent")


def test_list_all():
    """list_all returns manifests of healthy, enabled sources."""
    registry = DataSourceRegistry("test_registry")
    registry.register(MockDataSource)

    manifests = registry.list_all()
    assert len(manifests) == 1
    assert manifests[0].name == "mock_source"


def test_health_check_marks_degraded():
    """Health check failure marks source as degraded."""

    class FailingSource(BaseDataSource):
        @classmethod
        def manifest(cls):
            return DataSourceManifest(
                name="failing",
                display_name="Failing",
                version="1.0.0",
                data_types=[DataType.PRICE],
                required_env_vars=[],
            )

        async def fetch(self, data_type, params=None):
            raise Exception("fail")

    registry = DataSourceRegistry("test_registry")
    registry.register(FailingSource)

    import asyncio
    results = asyncio.run(registry.run_health_checks())

    assert results["failing"] is False
    assert registry._health_status["failing"] is False


if __name__ == "__main__":
    pytest.main([__file__, "-v"])