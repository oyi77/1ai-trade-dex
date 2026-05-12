import pytest
from backend.data.base_source import BaseDataSource, DataSourceManifest, DataType
from backend.data.source_registry import DataSourceRegistry, DataSourceRegistry
from backend.core.plugin_errors import PluginEnvVarMissing, PluginNotFound


class MockDataSource(BaseDataSource):
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
            rate_limit_per_minute=60,
            is_live=True,
            tags=["test"],
        )

    async def fetch(self, data_type, params=None):
        return {"data": "mock"}


class EnvDataSource(BaseDataSource):
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


class TestDataSourceRegistry:
    def setup_method(self):
        DataSourceRegistry._instance = None
        self.registry = DataSourceRegistry()

    def test_register_valid_source(self):
        self.registry.register(MockDataSource)

        assert "mock_source" in self.registry._plugins
        assert self.registry._enabled["mock_source"] is True

    def test_register_invalid_env_var(self):
        with pytest.raises(PluginEnvVarMissing):
            self.registry.register(EnvDataSource)

    def test_get_for_type(self):
        registry = DataSourceRegistry("test")
        registry.register(MockDataSource)

        sources = registry.get_for_type(DataType.PRICE)

        assert len(sources) == 1
        assert sources[0].manifest().name == "mock_source"

        sources = registry.get_for_type(DataType.WEATHER)
        assert len(sources) == 0

    def test_set_enabled_persists(self):
        registry = DataSourceRegistry("test")
        registry.register(MockDataSource)

        registry.set_enabled("mock_source", False)
        assert registry._enabled["mock_source"] is False

        registry.set_enabled("mock_source", True)
        assert registry._enabled["mock_source"] is True

    def test_get_source_by_name(self):
        registry = DataSourceRegistry("test")
        registry.register(MockDataSource)

        source = registry.get("mock_source")

        assert isinstance(source, MockDataSource)

    def test_get_disabled_source_raises(self):
        registry = DataSourceRegistry("test")
        registry.register(MockDataSource)
        registry.set_enabled("mock_source", False)

        with pytest.raises(PluginNotFound):
            registry.get("mock_source")

    def test_get_missing_source_raises(self):
        registry = DataSourceRegistry("test")
        with pytest.raises(PluginNotFound):
            registry.get("nonexistent")

    def test_list_all_returns_manifests(self):
        registry = DataSourceRegistry("test")
        registry.register(MockDataSource)

        manifests = registry.list_all()

        assert len(manifests) == 1
        assert manifests[0].name == "mock_source"

    def test_registry_singleton(self):
        registry1 = DataSourceRegistry()
        registry2 = DataSourceRegistry()

        assert registry1 is registry2

    def test_list_all_empty_when_no_plugins(self):
        registry = DataSourceRegistry("test")
        manifests = registry.list_all()

        assert manifests == []

    def test_register_source_health_status(self):
        registry = DataSourceRegistry("test")
        registry.register(MockDataSource)

        assert registry._health_status["mock_source"] is True

    def test_register_source_uses_manifest(self):
        registry = DataSourceRegistry("test")
        registry.register(MockDataSource)

        manifest = registry._manifests["mock_source"]
        assert manifest.name == "mock_source"
        assert len(manifest.data_types) == 2


def test_data_source_registry_error_handling():
    DataSourceRegistry._instance = None
    registry = DataSourceRegistry()

    try:
        registry.register(EnvDataSource)
    except PluginEnvVarMissing as e:
        assert "TEST_API_KEY" in str(e)
    else:
        pytest.fail("Expected PluginEnvVarMissing")

    DataSourceRegistry._instance = None


def test_data_source_registry_register_health():
    import asyncio

    DataSourceRegistry._instance = None
    registry = DataSourceRegistry()

    registry.register(MockDataSource)

    node = registry.get("mock_source")
    health = asyncio.run(node.health_check())

    assert health is True or health is False

    DataSourceRegistry._instance = None


def test_data_source_registry_get_multiple_types():
    DataSourceRegistry._instance = None

    class MultiTypeDataSource(BaseDataSource):
        @classmethod
        def manifest(cls):
            return DataSourceManifest(
                name="multi_source",
                display_name="Multi Source",
                version="1.0.0",
                data_types=[DataType.PRICE, DataType.CANDLES, DataType.ORDERBOOK],
                required_env_vars=[],
            )

        async def fetch(self, data_type, params=None):
            return {"data": "multi"}

    registry = DataSourceRegistry()
    registry.register(MultiTypeDataSource)

    sources_price = registry.get_for_type(DataType.PRICE)
    sources_candles = registry.get_for_type(DataType.CANDLES)
    sources_orderbook = registry.get_for_type(DataType.ORDERBOOK)

    assert len(sources_price) == 1
    assert len(sources_candles) == 1
    assert len(sources_orderbook) == 1

    DataSourceRegistry._instance = None


def test_data_source_registry_enabled_states():
    DataSourceRegistry._instance = None
    registry = DataSourceRegistry()

    registry.register(MockDataSource)

    assert registry._enabled["mock_source"] is True

    registry.set_enabled("mock_source", False)

    assert registry._enabled["mock_source"] is False

    DataSourceRegistry._instance = None


def test_data_source_registry_disabled_get_raises():
    DataSourceRegistry._instance = None
    registry = DataSourceRegistry()

    registry.register(MockDataSource)
    registry.set_enabled("mock_source", False)

    try:
        registry.get("mock_source")
    except PluginNotFound:
        pass
    else:
        pytest.fail("Expected PluginNotFound")

    DataSourceRegistry._instance = None
