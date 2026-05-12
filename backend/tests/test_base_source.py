"""Test suite for BaseDataSource abstract base class."""
import pytest
from backend.data.base_source import BaseDataSource, DataSourceManifest, DataType


class MockDataSource(BaseDataSource):
    """Mock data source for testing."""

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


class TestBaseDataSource:
    """Tests for BaseDataSource abstract base class."""

    def test_manifest_abstract(self):
        """Subclass without manifest() raises TypeError on instantiation."""
        class NoManifestSource(BaseDataSource):
            pass

        with pytest.raises(TypeError):
            NoManifestSource()

    def test_fetch_abstract(self):
        """Subclass without fetch() raises TypeError on instantiation."""
        class NoFetchSource(BaseDataSource):
            @classmethod
            def manifest(cls):
                return DataSourceManifest(
                    name="test",
                    display_name="Test",
                    version="1.0.0",
                    data_types=[DataType.PRICE],
                )

        with pytest.raises(TypeError):
            NoFetchSource()

    @pytest.mark.asyncio
    async def test_health_check_success(self):
        """Default health_check returns True."""
        source = MockDataSource()
        result = await source.health_check()
        assert result is True

    @pytest.mark.asyncio
    async def test_health_check_failure(self):
        """health_check returns False when fetch raises."""
        class FailingSource(BaseDataSource):
            @classmethod
            def manifest(cls):
                return DataSourceManifest(
                    name="failing",
                    display_name="Failing Source",
                    version="1.0.0",
                    data_types=[DataType.PRICE],
                )

            async def fetch(self, data_type, params):
                raise Exception("Fetch failed")

        source = FailingSource()
        result = await source.health_check()
        assert result is False

    @pytest.mark.asyncio
    async def test_stream_not_implemented(self):
        """stream() raises NotImplementedError by default."""
        source = MockDataSource()
        with pytest.raises(NotImplementedError):
            await source.stream(DataType.PRICE, {})

    @pytest.mark.asyncio
    async def test_backfill_not_implemented(self):
        """backfill() raises NotImplementedError by default."""
        source = MockDataSource()
        with pytest.raises(NotImplementedError):
            await source.backfill(DataType.PRICE, {}, "2024-01-01", "2024-01-02")

    @pytest.mark.asyncio
    async def test_teardown_default(self):
        """teardown() returns None by default."""
        source = MockDataSource()
        result = await source.teardown()
        assert result is None

    def test_manifest_fields(self):
        """Manifest has all required fields."""
        source = MockDataSource()
        manifest = source.manifest()
        assert manifest.name == "mock_source"
        assert manifest.display_name == "Mock Source"
        assert manifest.version == "1.0.0"
        assert DataType.PRICE in manifest.data_types
        assert manifest.required_env_vars == []
        assert manifest.tags == ["test"]

    def test_instantiate_with_manifest(self):
        """Can instantiate MockDataSource."""
        source = MockDataSource()
        assert source.manifest().name == "mock_source"
