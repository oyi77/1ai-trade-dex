"""Test suite for SXBetProvider."""

import os
import pytest
from decimal import Decimal
from unittest.mock import patch, AsyncMock

from backend.markets.order_types import (
    NormalizedOrder,
    OrderSide,
    OrderType,
    OrderStatus,
    VenueCapability,
)


@pytest.fixture
def provider():
    with patch.dict(os.environ, {"SXBET_API_URL": "https://api.sxbet.io"}, clear=False):
        from backend.markets.providers.sxbet_provider import SXBetProvider

        return SXBetProvider(paper_mode=True)


def test_manifest(provider):
    m = provider.manifest()
    assert m.name == "sxbet"
    assert m.is_live_venue is True
    assert m.supports_paper_mode is True
    assert VenueCapability.LIMIT_ORDERS in m.capabilities
    assert VenueCapability.MARKET_SEARCH in m.capabilities
    assert "SXBET_API_URL" in m.required_env_vars


@pytest.mark.asyncio
async def test_place_order_paper_mode(provider):
    order = NormalizedOrder(
        market_id="hash123",
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        size=Decimal("10"),
        price=Decimal("2.5"),
    )
    result = await provider.place_order(order)
    assert result.status == OrderStatus.FILLED
    assert result.filled_size == Decimal("10")
    assert result.filled_avg_price == Decimal("2.5")
    assert result.venue_order_id.startswith("paper_")


@pytest.mark.asyncio
async def test_place_order_paper_no_price(provider):
    order = NormalizedOrder(
        market_id="hash123",
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        size=Decimal("10"),
    )
    result = await provider.place_order(order)
    assert result.status == OrderStatus.FILLED
    assert result.filled_avg_price == Decimal("0.5")


@pytest.mark.asyncio
async def test_cancel_order_returns_false(provider):
    """SX.bet doesn't support cancel."""
    result = await provider.cancel_order("any_id")
    assert result is False


@pytest.mark.asyncio
async def test_get_balance_returns_zero(provider):
    bal = await provider.get_balance()
    assert bal.venue == "sxbet"
    assert bal.available_cash == Decimal("0")


@pytest.mark.asyncio
async def test_get_positions_returns_empty(provider):
    positions = await provider.get_positions()
    assert positions == []


@pytest.mark.asyncio
async def test_place_order_live_no_key():
    with patch.dict(
        os.environ,
        {"SXBET_API_URL": "https://api.sxbet.io", "SXBET_PRIVATE_KEY": ""},
        clear=False,
    ):
        from backend.markets.providers.sxbet_provider import SXBetProvider

        prov = SXBetProvider(paper_mode=False)
    mock_client = AsyncMock()
    prov._client = mock_client
    order = NormalizedOrder(
        market_id="hash1",
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        size=Decimal("1"),
        price=Decimal("2.0"),
    )
    with patch.dict(os.environ, {"SXBET_PRIVATE_KEY": ""}, clear=False):
        result = await prov.place_order(order)
    assert result.status == OrderStatus.REJECTED
    assert "PRIVATE_KEY" in result.raw["error"]


@pytest.mark.asyncio
async def test_place_order_live_success():
    with patch.dict(os.environ, {"SXBET_API_URL": "https://api.sxbet.io"}, clear=False):
        from backend.markets.providers.sxbet_provider import SXBetProvider

        prov = SXBetProvider(paper_mode=False)
    mock_client = AsyncMock()
    mock_client.place_maker_order = AsyncMock(
        return_value={"orderId": "sx_ord_1", "fee": "0.05"}
    )
    prov._client = mock_client
    order = NormalizedOrder(
        market_id="hash1",
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        size=Decimal("5"),
        price=Decimal("2.0"),
    )
    with patch.dict(os.environ, {"SXBET_PRIVATE_KEY": "0xabc123"}, clear=False):
        result = await prov.place_order(order)
    assert result.venue_order_id == "sx_ord_1"
    assert result.status == OrderStatus.OPEN
    assert result.fees_paid == Decimal("0.05")


@pytest.mark.asyncio
async def test_place_order_live_exception():
    with patch.dict(os.environ, {"SXBET_API_URL": "https://api.sxbet.io"}, clear=False):
        from backend.markets.providers.sxbet_provider import SXBetProvider

        prov = SXBetProvider(paper_mode=False)
    mock_client = AsyncMock()
    mock_client.place_maker_order = AsyncMock(side_effect=Exception("network error"))
    prov._client = mock_client
    order = NormalizedOrder(
        market_id="hash1",
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        size=Decimal("5"),
        price=Decimal("2.0"),
    )
    with patch.dict(os.environ, {"SXBET_PRIVATE_KEY": "0xabc"}, clear=False):
        result = await prov.place_order(order)
    assert result.status == OrderStatus.REJECTED


@pytest.mark.asyncio
async def test_get_markets(provider):
    mock_client = AsyncMock()
    mock_client.get_markets = AsyncMock(
        return_value=[
            {"marketHash": "hash1", "title": "Team A vs Team B"},
            {"marketHash": "hash2", "teamOneName": "X", "teamTwoName": "Y"},
        ]
    )
    provider._client = mock_client
    markets = await provider.get_markets()
    assert len(markets) == 2
    assert markets[0].title == "Team A vs Team B"
    assert markets[0].venue == "sxbet"
    assert markets[0].market_id == "hash1"
    assert markets[1].title == "X vs Y"


@pytest.mark.asyncio
async def test_get_markets_handles_dict_response(provider):
    mock_client = AsyncMock()
    mock_client.get_markets = AsyncMock(
        return_value={"data": {"markets": [{"marketHash": "h1", "title": "Game 1"}]}}
    )
    provider._client = mock_client
    markets = await provider.get_markets()
    assert len(markets) == 1
    assert markets[0].market_id == "h1"


@pytest.mark.asyncio
async def test_health_check(provider):
    mock_client = AsyncMock()
    mock_client.health_check = AsyncMock(return_value=True)
    provider._client = mock_client
    assert await provider.health_check() is True


def test_rejected_helper(provider):
    order = NormalizedOrder(
        market_id="h1",
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        size=Decimal("5"),
        client_order_id="co1",
    )
    result = provider._rejected(order, "test error")
    assert result.status == OrderStatus.REJECTED
    assert result.raw["error"] == "test error"
    assert result.client_order_id == "co1"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
