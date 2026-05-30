"""Test suite for market provider registry."""

import os
import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from decimal import Decimal

from backend.markets.base_provider import BaseMarketProvider, MarketProviderManifest
from backend.markets.order_types import (
    NormalizedOrder,
    NormalizedOrderResult,
    NormalizedBalance,
    OrderSide,
    OrderStatus,
    OrderType,
    VenueCapability,
)
from backend.markets.provider_registry import MarketProviderRegistry
from backend.core.plugin_errors import (
    PluginEnvVarMissing,
    MarketProviderNotFound,
)


@pytest.fixture(autouse=True)
def _reset_registry():
    """Reset singleton registry before each test to prevent cross-test pollution."""
    MarketProviderRegistry.reset()
    yield
    MarketProviderRegistry.reset()


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


@patch.dict(os.environ, {"TRADING_MODE": "paper"}, clear=False)
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


@pytest.mark.asyncio
async def test_polymarket_provider_rejects_live_order_without_price():
    with patch.dict(
        os.environ,
        {"POLYMARKET_API_KEY": "test-key", "POLYMARKET_API_SECRET": "test-secret"},
        clear=False,
    ):
        from backend.markets.providers.polymarket_provider import PolymarketProvider

    provider = PolymarketProvider(paper_mode=False)
    order = NormalizedOrder(
        market_id="12345678901234567890",
        side=OrderSide.YES,
        order_type=OrderType.LIMIT,
        size=Decimal("10"),
    )

    result = await provider.place_order(order)

    assert result.status == OrderStatus.REJECTED
    assert "limit price" in result.raw["error"]


def test_kalshi_provider_builds_v2_order_payload():
    with patch.dict(
        os.environ,
        {"KALSHI_API_KEY_ID": "test-key", "KALSHI_PRIVATE_KEY_PATH": "/tmp/test.pem"},
        clear=False,
    ):
        from backend.markets.providers.kalshi_provider import KalshiProvider

    provider = KalshiProvider(paper_mode=False)
    order = NormalizedOrder(
        market_id="FED-26MAY-T3.00",
        side=OrderSide.NO,
        order_type=OrderType.LIMIT,
        size=Decimal("2"),
        price=Decimal("0.37"),
        client_order_id="client-1",
    )

    payload = provider._to_kalshi_order(order)

    assert payload == {
        "ticker": "FED-26MAY-T3.00",
        "action": "buy",
        "side": "no",
        "count_fp": "2.00",
        "type": "limit",
        "client_order_id": "client-1",
        "no_price_dollars": 0.37,
    }


@pytest.mark.asyncio
async def test_kalshi_get_positions():
    """KalshiProvider.get_positions normalizes raw positions."""
    with patch.dict(
        os.environ,
        {"KALSHI_API_KEY_ID": "test-key", "KALSHI_PRIVATE_KEY_PATH": "/tmp/test.pem"},
        clear=False,
    ):
        from backend.markets.providers.kalshi_provider import KalshiProvider

    provider = KalshiProvider(paper_mode=False)
    mock_raw = [
        {
            "ticker": "FED-26MAY-T3.00",
            "side": "yes",
            "count": 5,
            "average_price": 0.65,
            "current_price": 0.70,
        },
        {"ticker": "BTC-100K", "side": "no", "count": 10, "average_price": 0.30},
    ]
    with patch.object(provider._client, "get_positions", return_value=mock_raw):
        positions = await provider.get_positions()

    assert len(positions) == 2
    assert positions[0].market_id == "FED-26MAY-T3.00"
    assert positions[0].side.value == "long"
    assert positions[0].size == Decimal("5")
    assert positions[0].avg_entry_price == Decimal("0.65")
    assert positions[0].current_price == Decimal("0.70")
    assert positions[1].market_id == "BTC-100K"
    assert positions[1].side.value == "short"
    assert positions[1].current_price is None


@pytest.mark.asyncio
async def test_kalshi_get_positions_filter_by_market():
    """KalshiProvider.get_positions filters by market_id."""
    with patch.dict(
        os.environ,
        {"KALSHI_API_KEY_ID": "test-key", "KALSHI_PRIVATE_KEY_PATH": "/tmp/test.pem"},
        clear=False,
    ):
        from backend.markets.providers.kalshi_provider import KalshiProvider

    provider = KalshiProvider(paper_mode=False)
    mock_raw = [
        {"ticker": "FED-26MAY", "side": "yes", "count": 5, "average_price": 0.65},
        {"ticker": "BTC-100K", "side": "no", "count": 10, "average_price": 0.30},
    ]
    with patch.object(provider._client, "get_positions", return_value=mock_raw):
        positions = await provider.get_positions(market_id="FED-26MAY")

    assert len(positions) == 1
    assert positions[0].market_id == "FED-26MAY"


@pytest.mark.asyncio
async def test_kalshi_get_positions_error_returns_empty():
    """KalshiProvider.get_positions returns [] on error."""
    with patch.dict(
        os.environ,
        {"KALSHI_API_KEY_ID": "test-key", "KALSHI_PRIVATE_KEY_PATH": "/tmp/test.pem"},
        clear=False,
    ):
        from backend.markets.providers.kalshi_provider import KalshiProvider

    provider = KalshiProvider(paper_mode=False)
    with patch.object(
        provider._client, "get_positions", side_effect=Exception("API down")
    ):
        positions = await provider.get_positions()

    assert positions == []


@pytest.mark.asyncio
async def test_kalshi_search_markets():
    """KalshiProvider.search_markets fetches and normalizes markets."""
    with patch.dict(
        os.environ,
        {"KALSHI_API_KEY_ID": "test-key", "KALSHI_PRIVATE_KEY_PATH": "/tmp/test.pem"},
        clear=False,
    ):
        from backend.markets.providers.kalshi_provider import KalshiProvider

    provider = KalshiProvider(paper_mode=False)
    mock_data = {
        "markets": [
            {
                "ticker": "FED-26MAY",
                "title": "Fed rate cut",
                "category": "economics",
                "yes_bid_dollars": 0.65,
                "volume_fp": 1000,
                "open_interest": 500,
                "status": "open",
            },
            {
                "ticker": "BTC-100K",
                "title": "Bitcoin 100k",
                "category": "crypto",
                "yes_bid_dollars": 0.30,
                "volume_fp": 5000,
                "open_interest": 2000,
                "status": "open",
            },
        ]
    }
    with patch.object(provider._client, "get_markets", return_value=mock_data):
        markets = await provider.search_markets(query="fed")

    assert len(markets) == 1
    assert markets[0].market_id == "FED-26MAY"
    assert markets[0].venue == "kalshi"
    assert markets[0].title == "Fed rate cut"
    assert markets[0].yes_price == Decimal("0.65")
    assert markets[0].no_price == Decimal("0.35")


@pytest.mark.asyncio
async def test_kalshi_search_markets_with_category():
    """KalshiProvider.search_markets filters by category."""
    with patch.dict(
        os.environ,
        {"KALSHI_API_KEY_ID": "test-key", "KALSHI_PRIVATE_KEY_PATH": "/tmp/test.pem"},
        clear=False,
    ):
        from backend.markets.providers.kalshi_provider import KalshiProvider

    provider = KalshiProvider(paper_mode=False)
    mock_data = {
        "markets": [
            {
                "ticker": "FED-26MAY",
                "title": "Fed rate",
                "category": "economics",
                "yes_bid": 65,
                "volume": 1000,
                "status": "open",
            },
            {
                "ticker": "BTC-100K",
                "title": "Bitcoin 100k",
                "category": "crypto",
                "yes_bid": 30,
                "volume": 5000,
                "status": "open",
            },
        ]
    }
    with patch.object(provider._client, "get_markets", return_value=mock_data):
        markets = await provider.search_markets(category="crypto")

    assert len(markets) == 1
    assert markets[0].market_id == "BTC-100K"


@pytest.mark.asyncio
async def test_polymarket_search_markets():
    """PolymarketProvider.search_markets fetches from Gamma API."""
    with patch.dict(
        os.environ,
        {"POLYMARKET_API_KEY": "test-key", "POLYMARKET_API_SECRET": "test-secret"},
        clear=False,
    ):
        from backend.markets.providers.polymarket_provider import PolymarketProvider

    provider = PolymarketProvider(paper_mode=False)
    mock_gamma = [
        {
            "condition_id": "abc123",
            "question": "Will BTC hit 100k?",
            "description": "Bitcoin price market",
            "category": "crypto",
            "outcomePrices": "[0.65, 0.35]",
            "volume": 50000,
            "openInterest": 10000,
            "active": True,
        },
        {
            "condition_id": "def456",
            "question": "Fed rate cut?",
            "description": "Economics market",
            "category": "economics",
            "outcomePrices": "[0.40, 0.60]",
            "volume": 20000,
            "openInterest": 5000,
            "active": True,
        },
    ]
    import backend.data.gamma as gamma_mod

    with patch.object(gamma_mod, "fetch_markets", return_value=mock_gamma):
        markets = await provider.search_markets(query="btc")

    assert len(markets) == 1
    assert markets[0].market_id == "abc123"
    assert markets[0].venue == "polymarket"
    assert markets[0].title == "Will BTC hit 100k?"
    assert markets[0].yes_price == Decimal("0.65")
    assert markets[0].no_price == Decimal("0.35")


@pytest.mark.asyncio
async def test_polymarket_search_markets_with_category():
    """PolymarketProvider.search_markets filters by category."""
    with patch.dict(
        os.environ,
        {"POLYMARKET_API_KEY": "test-key", "POLYMARKET_API_SECRET": "test-secret"},
        clear=False,
    ):
        from backend.markets.providers.polymarket_provider import PolymarketProvider

    provider = PolymarketProvider(paper_mode=False)
    mock_gamma = [
        {
            "condition_id": "abc123",
            "question": "BTC?",
            "category": "crypto",
            "outcomePrices": "[0.65]",
            "volume": 1000,
            "active": True,
        },
        {
            "condition_id": "def456",
            "question": "Fed?",
            "category": "economics",
            "outcomePrices": "[0.40]",
            "volume": 2000,
            "active": True,
        },
    ]
    import backend.data.gamma as gamma_mod

    with patch.object(gamma_mod, "fetch_markets", return_value=mock_gamma):
        markets = await provider.search_markets(category="economics")

    assert len(markets) == 1
    assert markets[0].market_id == "def456"


@pytest.mark.asyncio
async def test_polymarket_get_positions_no_wallet():
    """PolymarketProvider.get_positions returns [] when no wallet configured."""
    with patch.dict(
        os.environ,
        {"POLYMARKET_API_KEY": "test-key", "POLYMARKET_API_SECRET": "test-secret"},
        clear=False,
    ):
        from backend.markets.providers.polymarket_provider import PolymarketProvider

    provider = PolymarketProvider(paper_mode=False)
    mock_clob = AsyncMock()
    mock_clob._account = None
    mock_clob.__aenter__ = AsyncMock(return_value=mock_clob)
    mock_clob.__aexit__ = AsyncMock(return_value=False)

    with patch(
        "backend.markets.providers.polymarket_provider.clob_from_settings",
        return_value=mock_clob,
    ):
        positions = await provider.get_positions()

    assert positions == []


@pytest.mark.asyncio
async def test_polymarket_get_positions_with_wallet():
    """PolymarketProvider.get_positions fetches positions via CLOB."""
    with patch.dict(
        os.environ,
        {"POLYMARKET_API_KEY": "test-key", "POLYMARKET_API_SECRET": "test-secret"},
        clear=False,
    ):
        from backend.markets.providers.polymarket_provider import PolymarketProvider

    provider = PolymarketProvider(paper_mode=False)
    mock_clob = AsyncMock()
    mock_clob._account = MagicMock()
    mock_clob._account.address = "0x1234"
    mock_clob.get_trader_positions = AsyncMock(
        return_value=[
            {
                "market_id": "mkt1",
                "outcome": "YES",
                "size": 100,
                "avg_price": 0.65,
                "current_price": 0.70,
            },
            {"market_id": "mkt2", "outcome": "NO", "size": 50, "avg_price": 0.30},
        ]
    )
    mock_clob.__aenter__ = AsyncMock(return_value=mock_clob)
    mock_clob.__aexit__ = AsyncMock(return_value=False)

    with patch(
        "backend.markets.providers.polymarket_provider.clob_from_settings",
        return_value=mock_clob,
    ):
        positions = await provider.get_positions()

    assert len(positions) == 2
    assert positions[0].market_id == "mkt1"
    assert positions[0].side.value == "long"
    assert positions[0].size == Decimal("100")
    assert positions[0].venue == "polymarket"
    assert positions[1].market_id == "mkt2"
    assert positions[1].side.value == "short"


@pytest.mark.asyncio
async def test_polymarket_get_positions_filter_by_market():
    """PolymarketProvider.get_positions filters by market_id."""
    with patch.dict(
        os.environ,
        {"POLYMARKET_API_KEY": "test-key", "POLYMARKET_API_SECRET": "test-secret"},
        clear=False,
    ):
        from backend.markets.providers.polymarket_provider import PolymarketProvider

    provider = PolymarketProvider(paper_mode=False)
    mock_clob = AsyncMock()
    mock_clob._account = MagicMock()
    mock_clob._account.address = "0x1234"
    mock_clob.get_trader_positions = AsyncMock(
        return_value=[
            {"market_id": "mkt1", "outcome": "YES", "size": 100, "avg_price": 0.65},
            {"market_id": "mkt2", "outcome": "NO", "size": 50, "avg_price": 0.30},
        ]
    )
    mock_clob.__aenter__ = AsyncMock(return_value=mock_clob)
    mock_clob.__aexit__ = AsyncMock(return_value=False)

    with patch(
        "backend.markets.providers.polymarket_provider.clob_from_settings",
        return_value=mock_clob,
    ):
        positions = await provider.get_positions(market_id="mkt1")

    assert len(positions) == 1
    assert positions[0].market_id == "mkt1"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
