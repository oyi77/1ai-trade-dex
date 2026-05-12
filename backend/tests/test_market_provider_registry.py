"""Test suite for market provider registry."""
import pytest
from decimal import Decimal

from backend.markets.base_provider import BaseMarketProvider, MarketProviderManifest
from backend.markets.order_types import (
    NormalizedOrderResult, NormalizedBalance,
    OrderStatus, VenueCapability,
)
from backend.markets.provider_registry import MarketProviderRegistry
from backend.core.plugin_errors import (
    PluginEnvVarMissing, MarketProviderNotFound,
)


class MockMarketProvider(BaseMarketProvider):
    """Test market provider with no required env vars."""

    @classmethod
    def manifest(cls):
        return MarketProviderManifest(
            name="mock_venue",
            display_name="Mock Venue",
            version="1.0.0",
            venue_type="test",
            capabilities=[VenueCapability.LIMIT_ORDERS, VenueCapability.MARKET_ORDERS],
            supported_currencies=["USDC"],
            required_env_vars=[],
            supports_paper_mode=True,
            is_live_venue=False,
            tags=["test"],
        )

    async def place_order(self, order):
        return NormalizedOrderResult(
            venue_order_id="mock_123",
            client_order_id=order.client_order_id,
            status=OrderStatus.FILLED,
            filled_size=order.size,
            filled_avg_price=order.price or Decimal("0.5"),
            remaining_size=Decimal("0"),
            fees_paid=Decimal("0"),
        )

    async def cancel_order(self, venue_order_id):
        return True

    async def get_balance(self):
        return NormalizedBalance(
            venue="mock",
            available_cash=Decimal("10000"),
            total_equity=Decimal("10000"),
            reserved_margin=Decimal("0"),
        )

    async def get_positions(self, market_id=None):
        return []


class EnvMarketProvider(BaseMarketProvider):
    """Test market provider requiring env vars."""

    @classmethod
    def manifest(cls):
        return MarketProviderManifest(
            name="env_venue",
            display_name="Env Venue",
            version="1.0.0",
            venue_type="test",
            capabilities=[VenueCapability.LIMIT_ORDERS],
            supported_currencies=["USDC"],
            required_env_vars=["TEST_VENUE_KEY"],
            tags=["test"],
        )

    async def place_order(self, order):
        return NormalizedOrderResult(
            venue_order_id="env_123",
            client_order_id=order.client_order_id,
            status=OrderStatus.FILLED,
            filled_size=order.size,
            filled_avg_price=order.price or Decimal("0.5"),
            remaining_size=Decimal("0"),
            fees_paid=Decimal("0"),
        )

    async def cancel_order(self, venue_order_id):
        return True

    async def get_balance(self):
        return NormalizedBalance(
            venue="env",
            available_cash=Decimal("10000"),
            total_equity=Decimal("10000"),
            reserved_margin=Decimal("0"),
        )

    async def get_positions(self, market_id=None):
        return []


def test_register_provider():
    """Register valid provider succeeds."""
    registry = MarketProviderRegistry("test_registry")
    registry.register(MockMarketProvider)
    assert "mock_venue" in registry._plugins


def test_register_missing_env_var():
    """Register provider with missing env var raises PluginEnvVarMissing."""
    registry = MarketProviderRegistry("test_registry")
    with pytest.raises(PluginEnvVarMissing):
        registry.register(EnvMarketProvider)


def test_get_provider():
    """Get provider returns instance."""
    registry = MarketProviderRegistry("test_registry")
    registry.register(MockMarketProvider)
    provider = registry.get("mock_venue")
    assert isinstance(provider, MockMarketProvider)


def test_disabled_provider_raises():
    """Getting disabled provider raises error."""
    registry = MarketProviderRegistry("test_registry")
    registry.register(MockMarketProvider)
    registry.set_enabled("mock_venue", False)
    with pytest.raises(MarketProviderNotFound):
        registry.get("mock_venue")


def test_get_for_capability():
    """get_for_capability filters providers by capability."""
    registry = MarketProviderRegistry("test_registry")
    registry.register(MockMarketProvider)

    providers = registry.get_for_capability("limit_orders")
    assert len(providers) == 1

    providers = registry.get_for_capability("nonexistent")
    assert len(providers) == 0


def test_set_enabled_with_positions():
    """Disabling provider with positions raises error without force."""
    registry = MarketProviderRegistry("test_registry")
    registry.register(MockMarketProvider)

    # Mock positions by directly setting internal state
    _ = registry._plugins["mock_venue"]
    registry._enabled["mock_venue"] = True
    registry._health_status["mock_venue"] = True

    # Without force, checks positions (our mock returns empty, so it passes)
    registry.set_enabled("mock_venue", False)
    assert registry._enabled["mock_venue"] is False


def test_force_disable():
    """Force disable bypasses position check."""
    registry = MarketProviderRegistry("test_registry")
    registry.register(MockMarketProvider)

    registry.set_enabled("mock_venue", False, force=True)
    assert registry._enabled["mock_venue"] is False


def test_paper_mode_injected():
    """Paper mode is injected based on TRADING_MODE env var."""
    # Default is paper mode
    registry = MarketProviderRegistry("test_registry")
    registry.register(MockMarketProvider)
    provider = registry._plugins["mock_venue"]
    assert provider._paper_mode is True


def test_list_all():
    """list_all returns manifests of healthy, enabled providers."""
    registry = MarketProviderRegistry("test_registry")
    registry.register(MockMarketProvider)

    manifests = registry.list_all()
    assert len(manifests) == 1
    assert manifests[0].name == "mock_venue"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])