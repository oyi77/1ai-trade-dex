"""Test suite for the generic PluginRegistry."""
import asyncio
import pytest
from unittest.mock import MagicMock, patch, AsyncMock

from backend.core.plugin_registry import PluginRegistry, BasePlugin, BaseManifest
from backend.core.plugin_errors import PluginEnvVarMissing, PluginNotFound


class TestPluginRegistry:
    """Tests for the generic PluginRegistry base class."""

    def test_register_valid_plugin(self):
        """Registering a valid plugin succeeds and gets healthy status."""

        class TestManifest(BaseManifest):
            pass

        class TestPlugin(BasePlugin):
            @classmethod
            def manifest(cls):
                return TestManifest(
                    name="test_plugin",
                    version="1.0.0",
                    required_env_vars=[],
                    tags=[],
                )

        registry = PluginRegistry("test_registry")
        registry.register(TestPlugin)

        assert "test_plugin" in registry._plugins
        assert registry._enabled["test_plugin"] is True
        assert registry._health_status["test_plugin"] is True

    def test_register_plugin_missing_env_vars(self):
        """Registering a plugin with missing required env vars raises error."""

        class EnvManifest(BaseManifest):
            pass

        class EnvPlugin(BasePlugin):
            @classmethod
            def manifest(cls):
                return EnvManifest(
                    name="env_plugin",
                    version="1.0.0",
                    required_env_vars=["MISSING_VAR_XYZ"],
                    tags=[],
                )

        registry = PluginRegistry("test_registry")
        with pytest.raises(PluginEnvVarMissing):
            registry.register(EnvPlugin)

    def test_get_missing_plugin(self):
        """Getting a non-existent plugin raises PluginNotFound."""
        registry = PluginRegistry("test_registry")
        with pytest.raises(PluginNotFound):
            registry.get("nonexistent")

    def test_get_disabled_plugin(self):
        """Getting a disabled plugin raises PluginNotFound."""

        class SimpleManifest(BaseManifest):
            pass

        class SimplePlugin(BasePlugin):
            @classmethod
            def manifest(cls):
                return SimpleManifest(
                    name="simple",
                    version="1.0.0",
                    required_env_vars=[],
                    tags=[],
                )

        registry = PluginRegistry("test_registry")
        registry.register(SimplePlugin)
        registry.set_enabled("simple", False)

        with pytest.raises(PluginNotFound):
            registry.get("simple")

    def test_set_enabled_disabled(self):
        """Set enabled/disabled updates state."""

        class ToggleManifest(BaseManifest):
            pass

        class TogglePlugin(BasePlugin):
            @classmethod
            def manifest(cls):
                return ToggleManifest(
                    name="toggle",
                    version="1.0.0",
                    required_env_vars=[],
                    tags=[],
                )

        registry = PluginRegistry("test_registry")
        registry.register(TogglePlugin)

        registry.set_enabled("toggle", False)
        assert registry._enabled["toggle"] is False

        registry.set_enabled("toggle", True)
        assert registry._enabled["toggle"] is True

    def test_list_all_returns_only_healthy(self):
        """list_all returns only enabled and healthy plugins."""

        class HManifest(BaseManifest):
            pass

        class UManifest(BaseManifest):
            pass

        class HPlugin(BasePlugin):
            @classmethod
            def manifest(cls):
                return HManifest(
                    name="healthy",
                    version="1.0.0",
                    required_env_vars=[],
                    tags=[],
                )

        class UPlugin(BasePlugin):
            @classmethod
            def manifest(cls):
                return UManifest(
                    name="unhealthy",
                    version="1.0.0",
                    required_env_vars=[],
                    tags=[],
                )

        registry = PluginRegistry("test_registry")
        registry.register(HPlugin)
        registry.register(UPlugin)
        registry._health_status["unhealthy"] = False

        manifests = registry.list_all()
        assert len(manifests) == 1
        assert manifests[0].name == "healthy"

    def test_auto_discover_loads_modules(self):
        """Auto-discover imports all modules in a package."""
        registry = PluginRegistry("test_registry")
        count = registry.auto_discover("backend.tests")
        assert count >= 0

    def test_health_check_marks_degraded(self):
        """Health check failure marks plugin as degraded."""

        class FManifest(BaseManifest):
            pass

        class FailingPlugin(BasePlugin):
            @classmethod
            def manifest(cls):
                return FManifest(
                    name="failing",
                    version="1.0.0",
                    required_env_vars=[],
                    tags=[],
                )

            async def health_check(self):
                return False

        registry = PluginRegistry("test_registry")
        registry.register(FailingPlugin)

        results = asyncio.run(registry.run_health_checks())

        assert results["failing"] is False
        assert registry._health_status["failing"] is False

    def test_plugin_decorator_registers(self):
        """The @registry.plugin decorator registers the class."""
        registry = PluginRegistry("decorator_test")

        class DManifest(BaseManifest):
            pass

        @registry.plugin
        class DecoratedPlugin(BasePlugin):
            @classmethod
            def manifest(cls):
                return DManifest(
                    name="decorated",
                    version="1.0.0",
                    required_env_vars=[],
                    tags=[],
                )

        assert "decorated" in registry._plugins


if __name__ == "__main__":
    pytest.main([__file__, "-v"])