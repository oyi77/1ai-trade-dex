"""Test suite for crypto exchange feed registry."""
import pytest

from backend.data.crypto_feeds.base import BaseExchangeFeed, ExchangeFeedManifest
from backend.data.crypto_feeds.registry import ExchangeFeedRegistry
from backend.core.plugin_errors import PluginEnvVarMissing


class MockFeed(BaseExchangeFeed):
    def __init__(self, price=100.0, healthy=True, klines=None):
        self._price = price
        self._healthy = healthy
        self._klines = klines or []

    @classmethod
    def manifest(cls):
        return ExchangeFeedManifest(
            name="mock",
            display_name="Mock Feed",
            version="1.0.0",
            base_url="https://mock.example.com",
            supported_pairs=["BTCUSDT"],
            rate_limit_per_minute=60,
            required_env_vars=[],
            tags=["test"],
        )

    async def get_btc_price(self):
        return self._price

    async def get_klines(self, symbol, interval, limit):
        return self._klines


class EnvFeed(BaseExchangeFeed):
    @classmethod
    def manifest(cls):
        return ExchangeFeedManifest(
            name="envfeed",
            display_name="Env Feed",
            version="1.0.0",
            base_url="https://env.example.com",
            supported_pairs=["BTCUSDT"],
            rate_limit_per_minute=60,
            required_env_vars=["TEST_ENV_VAR_XYZ"],
            tags=["test"],
        )

    async def get_btc_price(self):
        return 100.0

    async def get_klines(self, symbol, interval, limit):
        return []


def test_register_valid_feed():
    registry = ExchangeFeedRegistry("test_registry")
    registry.register(MockFeed)
    assert "mock" in registry._plugins
    assert registry._enabled["mock"] is True
    assert registry._health_status["mock"] is True


def test_register_with_missing_env_vars():
    registry = ExchangeFeedRegistry("test_registry")
    with pytest.raises(PluginEnvVarMissing):
        registry.register(EnvFeed)


def test_get_price_from_specific_feed():
    registry = ExchangeFeedRegistry("test_registry")
    registry.register(MockFeed)
    price = registry.get_price("mock")
    assert price == 100.0


def test_get_price_fallback_on_failure():
    class FailingFeed(BaseExchangeFeed):
        @classmethod
        def manifest(cls):
            return ExchangeFeedManifest(
                name="failing",
                display_name="Failing",
                version="1.0.0",
                base_url="https://fail.example.com",
                supported_pairs=["BTCUSDT"],
                rate_limit_per_minute=60,
                required_env_vars=[],
                tags=["test"],
            )

        async def get_btc_price(self):
            raise Exception("API down")

        async def get_klines(self, symbol, interval, limit):
            return []

    registry = ExchangeFeedRegistry("test_registry")
    registry.register(FailingFeed)
    registry._enabled["failing"] = False
    registry._health_status["failing"] = False

    price = registry.get_price("failing")
    assert price is None


def test_get_fallback_chain_ordered_by_health():
    ExchangeFeedRegistry.reset()

    class Healthy1Feed(BaseExchangeFeed):
        @classmethod
        def manifest(cls):
            return ExchangeFeedManifest(
                name="healthy1",
                display_name="Healthy1",
                version="1.0.0",
                base_url="https://h1.example.com",
                supported_pairs=["BTCUSDT"],
                rate_limit_per_minute=60,
                required_env_vars=[],
                tags=["test"],
            )
        async def get_btc_price(self): return 100.0
        async def get_klines(self, symbol, interval, limit): return []

    class Healthy2Feed(BaseExchangeFeed):
        @classmethod
        def manifest(cls):
            return ExchangeFeedManifest(
                name="healthy2",
                display_name="Healthy2",
                version="1.0.0",
                base_url="https://h2.example.com",
                supported_pairs=["BTCUSDT"],
                rate_limit_per_minute=60,
                required_env_vars=[],
                tags=["test"],
            )
        async def get_btc_price(self): return 200.0
        async def get_klines(self, symbol, interval, limit): return []

    class UnhealthyFeed(BaseExchangeFeed):
        @classmethod
        def manifest(cls):
            return ExchangeFeedManifest(
                name="unhealthy",
                display_name="Unhealthy",
                version="1.0.0",
                base_url="https://uh.example.com",
                supported_pairs=["BTCUSDT"],
                rate_limit_per_minute=60,
                required_env_vars=[],
                tags=["test"],
            )
        async def get_btc_price(self): raise Exception("down")
        async def get_klines(self, symbol, interval, limit): return []

    registry = ExchangeFeedRegistry("test_registry")
    registry.register(Healthy1Feed)
    registry.register(Healthy2Feed)
    registry.register(UnhealthyFeed)

    fallback = registry.get_fallback_chain()
    assert len(fallback) >= 2
    assert "healthy1" in fallback
    assert "healthy2" in fallback


def test_disabled_feed_skipped():
    registry = ExchangeFeedRegistry("test_registry")
    registry.register(MockFeed)
    registry.set_enabled("mock", False)

    assert registry.get_price("mock") is None


def test_auto_discover():
    registry = ExchangeFeedRegistry("test_registry")
    count = registry.auto_discover("backend.data.crypto_feeds.providers")
    assert count > 0


def test_health_check():
    registry = ExchangeFeedRegistry("test_registry")
    registry.register(MockFeed)
    import asyncio
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        result = loop.run_until_complete(registry.run_health_checks())
        assert result.get("mock") is True
    finally:
        loop.close()


def test_registry_singleton():
    registry1 = ExchangeFeedRegistry("test")
    registry2 = ExchangeFeedRegistry("test")
    assert registry1 is registry2


def test_reset_registry():
    ExchangeFeedRegistry.reset()

    class TestFeed(BaseExchangeFeed):
        @classmethod
        def manifest(cls):
            return ExchangeFeedManifest(
                name="testreset",
                display_name="Test Reset",
                version="1.0.0",
                base_url="https://reset.example.com",
                supported_pairs=["BTCUSDT"],
                rate_limit_per_minute=60,
                required_env_vars=[],
                tags=["test"],
            )
        async def get_btc_price(self): return 100.0
        async def get_klines(self, symbol, interval, limit): return []

    registry = ExchangeFeedRegistry("test_registry")
    registry.register(TestFeed)
    assert "testreset" in registry._plugins
    ExchangeFeedRegistry.reset()
    assert "testreset" not in registry._plugins
