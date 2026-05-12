"""Test suite for AI provider registry."""
import pytest
from unittest.mock import AsyncMock, MagicMock

from backend.ai.base_provider import BaseAIProvider, ProviderManifest
from backend.ai.provider_registry import ProviderRegistry
from backend.core.plugin_errors import PluginEnvVarMissing, PluginNotFound


class MockAIProvider(BaseAIProvider):
    @classmethod
    def manifest(cls):
        return ProviderManifest(
            name="mock_provider",
            display_name="Mock Provider",
            version="1.0.0",
            supports_streaming=False,
            supports_tool_use=False,
            max_tokens=4096,
            required_env_vars=[],
            cost_per_1k_tokens_usd=0.001,
            tags=["test", "cheap"],
        )

    async def complete(self, prompt, system=None, max_tokens=1000, temperature=0.7, **kwargs):
        return "mock response"


class EnvAIProvider(BaseAIProvider):
    @classmethod
    def manifest(cls):
        return ProviderManifest(
            name="env_provider",
            display_name="Env Provider",
            version="1.0.0",
            required_env_vars=["TEST_PROVIDER_API_KEY"],
            tags=["test"],
        )

    async def complete(self, prompt, system=None, max_tokens=1000, temperature=0.7, **kwargs):
        return "env response"


def test_register_valid_provider():
    registry = ProviderRegistry("test_registry")
    registry.register(MockAIProvider)
    assert "mock_provider" in registry._plugins
    assert registry._enabled["mock_provider"] is True


def test_register_missing_env_var():
    registry = ProviderRegistry("test_registry")
    with pytest.raises(PluginEnvVarMissing):
        registry.register(EnvAIProvider)


def test_get_provider_by_name():
    registry = ProviderRegistry("test_registry")
    registry.register(MockAIProvider)
    provider = registry.get("mock_provider")
    assert isinstance(provider, MockAIProvider)


def test_disabled_provider_raises():
    registry = ProviderRegistry("test_registry")
    registry.register(MockAIProvider)
    registry.set_enabled("mock_provider", False)
    with pytest.raises(PluginNotFound):
        registry.get("mock_provider")


def test_list_available_returns_healthy_enabled():
    registry = ProviderRegistry("test_registry")
    registry.register(MockAIProvider)
    
    class DisabledProvider(MockAIProvider):
        @classmethod
        def manifest(cls):
            return ProviderManifest(
                name="disabled_provider",
                display_name="Disabled",
                version="1.0.0",
                required_env_vars=[],
                tags=["test"],
            )

    registry.register(DisabledProvider)
    registry.set_enabled("disabled_provider", False)
    
    manifests = registry.list_available()
    assert len(manifests) == 1
    assert manifests[0].name == "mock_provider"


def test_get_best_provider_returns_best():
    registry = ProviderRegistry("test_registry")
    registry.register(MockAIProvider)
    
    class BetterProvider(MockAIProvider):
        @classmethod
        def manifest(cls):
            return ProviderManifest(
                name="better_provider",
                display_name="Better",
                version="1.0.0",
                required_env_vars=[],
                cost_per_1k_tokens_usd=0.002,
                tags=["test", "better"],
            )

    registry.register(BetterProvider)
    
    provider = registry.get_best_provider(["test"])
    assert provider is not None
    assert provider.manifest().name == "mock_provider"
    
    registry.set_enabled("mock_provider", False)
    registry.set_enabled("better_provider", False)
    provider = registry.get_best_provider(["nonexistent"])
    assert provider is None



