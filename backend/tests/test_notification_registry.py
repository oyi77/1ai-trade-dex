import asyncio
import pytest
from unittest.mock import MagicMock, patch, AsyncMock
import os
import sys

sys.path.insert(0, "/Users/paijo/1ai-poly-trader")

from backend.bot.notification.base import BaseNotificationProvider, NotificationManifest
from backend.bot.notification.registry import NotificationRegistry, registry
from backend.core.plugin_errors import PluginEnvVarMissing, PluginNotFound


class MockProvider(BaseNotificationProvider):
    def __init__(self, health_result=True, send_result=True):
        self.health_result = health_result
        self.send_result = send_result
        self.sent_messages = []

    @classmethod
    def manifest(cls):
        return NotificationManifest(
            name="mock",
            version="1.0.0",
            required_env_vars=[],
            tags=[],
        )

    async def send(self, message, event_type, details=None):
        self.sent_messages.append((message, event_type, details))
        return self.send_result

    async def health_check(self):
        return self.health_result


class TestNotificationRegistry:
    def setup_method(self):
        registry.reset()

    def test_register_valid_provider(self):
        registry.register(MockProvider)

        assert "mock" in registry._plugins
        assert registry._enabled["mock"] is True
        assert registry._health_status["mock"] is True

    def test_register_provider_missing_env_vars(self):
        class EnvProvider(BaseNotificationProvider):
            @classmethod
            def manifest(cls):
                return NotificationManifest(
                    name="env_provider",
                    version="1.0.0",
                    required_env_vars=["MISSING_VAR_TEST"],
                    tags=[],
                )

            async def send(self, message, event_type, details=None):
                return True

            async def health_check(self):
                return True

        with pytest.raises(PluginEnvVarMissing):
            registry.register(EnvProvider)

    def test_send_to_unregistered_channel(self):
        registry.register(MockProvider)

        result = asyncio.run(registry.send_to("nonexistent", "test", "message"))

        assert result is False

    def test_send_to_disabled_channel(self):
        registry.register(MockProvider)
        registry.set_enabled("mock", False)

        result = asyncio.run(registry.send_to("mock", "test", "message"))

        assert result is False
        assert registry.is_enabled("mock") is False

    def test_broadcast_to_all_enabled_providers(self):
        registry.register(MockProvider)
        mock_provider = registry._plugins["mock"]
        mock_provider.send_result = True

        asyncio.run(registry.broadcast("test_event", "test message", {"key": "value"}))

        assert len(mock_provider.sent_messages) == 1
        assert mock_provider.sent_messages[0] == ("test message", "test_event", {"key": "value"})

    def test_send_to_specific_provider_success(self):
        registry.register(MockProvider)
        mock_provider = registry._plugins["mock"]

        result = asyncio.run(registry.send_to("mock", "test_event", "test message"))

        assert result is True
        assert len(mock_provider.sent_messages) == 1

    def test_auto_discover_loads_providers(self):
        asyncio.run(registry.auto_discover("backend.bot.notification.providers"))

        available = registry.list_available()

        assert len(available) > 0

    def test_health_check_all(self):
        registry.register(MockProvider)
        mock_provider = registry._plugins["mock"]
        mock_provider.health_result = True

        result = asyncio.run(registry.health_check_all())

        assert "mock" in result
        assert result["mock"] is True

    def test_get_nonexistent_provider(self):
        with pytest.raises(PluginNotFound):
            registry.get("nonexistent")

    def test_get_disabled_provider(self):
        registry.register(MockProvider)
        registry.set_enabled("mock", False)

        with pytest.raises(PluginNotFound):
            registry.get("mock")

    def test_get_unhealthy_provider(self):
        registry.register(MockProvider)
        registry._health_status["mock"] = False

        with pytest.raises(PluginNotFound):
            registry.get("mock")


def test_telegram_manifest():
    registry.reset()
    os.environ["TELEGRAM_BOT_TOKEN"] = "test_token"
    os.environ["DISCORD_WEBHOOK_URL"] = "https://discord.test"
    os.environ["SLACK_WEBHOOK_URL"] = "https://slack.test"
    os.environ["WEBHOOK_URL"] = "https://webhook.test"

    from backend.bot.notification.providers import telegram

    manifest = telegram.TelegramProvider.manifest()

    assert manifest.name == "telegram"
    assert "TELEGRAM_BOT_TOKEN" in manifest.required_env_vars


def test_discord_manifest():
    registry.reset()
    os.environ["DISCORD_WEBHOOK_URL"] = "https://discord.test"
    os.environ["TELEGRAM_BOT_TOKEN"] = "test_token"
    os.environ["SLACK_WEBHOOK_URL"] = "https://slack.test"
    os.environ["WEBHOOK_URL"] = "https://webhook.test"

    from backend.bot.notification.providers import discord

    manifest = discord.DiscordProvider.manifest()

    assert manifest.name == "discord"
    assert "DISCORD_WEBHOOK_URL" in manifest.required_env_vars


def test_slack_manifest():
    registry.reset()
    os.environ["SLACK_WEBHOOK_URL"] = "https://slack.test"
    os.environ["TELEGRAM_BOT_TOKEN"] = "test_token"
    os.environ["DISCORD_WEBHOOK_URL"] = "https://discord.test"
    os.environ["WEBHOOK_URL"] = "https://webhook.test"

    from backend.bot.notification.providers import slack

    manifest = slack.SlackProvider.manifest()

    assert manifest.name == "slack"
    assert "SLACK_WEBHOOK_URL" in manifest.required_env_vars


def test_webhook_manifest():
    registry.reset()
    os.environ["WEBHOOK_URL"] = "https://webhook.test"
    os.environ["TELEGRAM_BOT_TOKEN"] = "test_token"
    os.environ["DISCORD_WEBHOOK_URL"] = "https://discord.test"
    os.environ["SLACK_WEBHOOK_URL"] = "https://slack.test"

    from backend.bot.notification.providers import webhook

    manifest = webhook.GenericWebhookProvider.manifest()

    assert manifest.name == "webhook"
    assert "WEBHOOK_URL" in manifest.required_env_vars


class TestEnvShadowMode:
    def setup_method(self):
        registry.reset()
        os.environ["SHADOW_MODE"] = "true"

    def test_register_with_missing_env_vars_in_shadow_mode(self):
        class EnvProvider(BaseNotificationProvider):
            @classmethod
            def manifest(cls):
                return NotificationManifest(
                    name="env_provider",
                    version="1.0.0",
                    required_env_vars=["MISSING_VAR_TEST"],
                    tags=[],
                )

            async def send(self, message, event_type, details=None):
                return True

            async def health_check(self):
                return True

        registry.register(EnvProvider)

        assert "env_provider" in registry._plugins

    def teardown_method(self):
        if "SHADOW_MODE" in os.environ:
            del os.environ["SHADOW_MODE"]
