"""Test suite for BaseAIProvider abstract base class."""

import asyncio
import pytest

from backend.ai.base_provider import BaseAIProvider, ProviderManifest


class MockProvider(BaseAIProvider):
    """Mock AI provider for testing."""

    @classmethod
    def manifest(cls):
        return ProviderManifest(
            name="mock",
            display_name="Mock Provider",
            version="1.0.0",
            supports_streaming=False,
            supports_tool_use=False,
            max_tokens=4096,
            required_env_vars=[],
            cost_per_1k_tokens_usd=0.001,
            tags=["test"],
        )

    async def complete(self, prompt, **kwargs):
        return "mock response"


# Define abstract subclasses at module level for proper test isolation
class NoManifestProvider(BaseAIProvider):
    pass


class NoCompleteProvider(BaseAIProvider):
    @classmethod
    def manifest(cls):
        return ProviderManifest(
            name="test",
            display_name="Test",
            version="1.0.0",
            required_env_vars=[],
        )


class TestBaseAIProvider:
    """Tests for BaseAIProvider abstract base class."""

    def test_manifest_abstract(self):
        """Subclass without manifest() raises TypeError on instantiation."""
        with pytest.raises(TypeError):
            NoManifestProvider()

    def test_complete_abstract(self):
        """Subclass without complete() raises TypeError on instantiation."""
        with pytest.raises(TypeError):
            NoCompleteProvider()

    @pytest.mark.asyncio
    async def test_health_check_default_implementation(self):
        """Default health_check returns True."""
        provider = MockProvider()
        result = await provider.health_check()
        assert result is True

    @pytest.mark.asyncio
    async def test_health_check_success(self):
        """health_check returns True for healthy provider."""
        provider = MockProvider()
        result = await provider.health_check()
        assert result is True

    @pytest.mark.asyncio
    async def test_health_check_failure(self):
        """health_check returns False when complete raises."""

        class FailingProvider(BaseAIProvider):
            @classmethod
            def manifest(cls):
                return ProviderManifest(
                    name="failing",
                    display_name="Failing Provider",
                    version="1.0.0",
                    required_env_vars=[],
                )

            async def complete(self, prompt, **kwargs):
                raise Exception("API failure")

        provider = FailingProvider()
        result = await provider.health_check()
        assert result is False

    def test_teardown_default(self):
        """teardown() returns None by default."""
        provider = MockProvider()
        result = asyncio.run(provider.teardown())
        assert result is None


def test_provider_manifest_structure():
    """ProviderManifest has all required fields."""
    manifest = ProviderManifest(
        name="test_provider",
        display_name="Test Provider",
        version="1.0.0",
        supports_streaming=True,
        supports_tool_use=False,
        max_tokens=2048,
        required_env_vars=["API_KEY"],
        cost_per_1k_tokens_usd=0.002,
        tags=["test", "cheap"],
    )
    assert manifest.name == "test_provider"
    assert manifest.display_name == "Test Provider"
    assert manifest.version == "1.0.0"
    assert manifest.supports_streaming is True
    assert manifest.supports_tool_use is False
    assert manifest.max_tokens == 2048
    assert manifest.required_env_vars == ["API_KEY"]
    assert manifest.cost_per_1k_tokens_usd == 0.002
    assert manifest.tags == ["test", "cheap"]


def test_instantiate_mock_provider():
    """Can instantiate MockProvider."""
    provider = MockProvider()
    assert provider.manifest().name == "mock"
