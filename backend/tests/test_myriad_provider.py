"""Test suite for MyriadProvider."""

import os
import pytest
from decimal import Decimal
from unittest.mock import patch, AsyncMock

from backend.markets.order_types import (
    NormalizedOrder,
    OrderSide,
    OrderType,
    OrderStatus,
    PositionSide,
    VenueCapability,
)


@pytest.fixture
def provider():
    with patch.dict(
        os.environ, {"MYRIAD_API_URL": "https://api.myriad.markets"}, clear=False
    ):
        from backend.markets.providers.myriad_provider import MyriadProvider

        return MyriadProvider(paper_mode=True)


def test_manifest(provider):
    m = provider.manifest()
    assert m.name == "myriad"
    assert m.is_live_venue is False  # API 404
    assert m.supports_paper_mode is True
    assert VenueCapability.LIMIT_ORDERS in m.capabilities
    assert VenueCapability.MARKET_SEARCH in m.capabilities
    assert "MYRIAD_API_URL" in m.required_env_vars


@pytest.mark.asyncio
async def test_place_order_paper_mode(provider):
    order = NormalizedOrder(
        market_id="mkt1",
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        size=Decimal("20"),
        price=Decimal("0.7"),
    )
    result = await provider.place_order(order)
    assert result.status == OrderStatus.FILLED
    assert result.filled_size == Decimal("20")
    assert result.filled_avg_price == Decimal("0.7")
    assert result.venue_order_id.startswith("paper_myriad_")


@pytest.mark.asyncio
async def test_place_order_paper_no_price(provider):
    order = NormalizedOrder(
        market_id="mkt1",
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        size=Decimal("10"),
    )
    result = await provider.place_order(order)
    assert result.status == OrderStatus.FILLED
    assert result.filled_avg_price == Decimal("0.5")


@pytest.mark.asyncio
async def test_place_order_live_rejects_no_price(provider):
    provider._paper_mode = False
    order = NormalizedOrder(
        market_id="mkt1",
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        size=Decimal("10"),
    )
    result = await provider.place_order(order)
    assert result.status == OrderStatus.REJECTED
    assert "limit price" in result.raw["error"].lower()


@pytest.mark.asyncio
async def test_place_order_live_success(provider):
    provider._paper_mode = False
    mock_client = AsyncMock()
    mock_client.place_order = AsyncMock(return_value={"order_id": "myr_1"})
    provider._client = mock_client
    order = NormalizedOrder(
        market_id="mkt1",
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        size=Decimal("10"),
        price=Decimal("0.5"),
    )
    result = await provider.place_order(order)
    assert result.venue_order_id == "myr_1"
    assert result.status == OrderStatus.FILLED


@pytest.mark.asyncio
async def test_place_order_live_api_error(provider):
    provider._paper_mode = False
    mock_client = AsyncMock()
    mock_client.place_order = AsyncMock(return_value={"error": "market closed"})
    provider._client = mock_client
    order = NormalizedOrder(
        market_id="mkt1",
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        size=Decimal("10"),
        price=Decimal("0.5"),
    )
    result = await provider.place_order(order)
    assert result.status == OrderStatus.REJECTED


@pytest.mark.asyncio
async def test_cancel_order(provider):
    mock_client = AsyncMock()
    mock_client.cancel_order = AsyncMock(return_value=True)
    provider._client = mock_client
    result = await provider.cancel_order("ord_1")
    assert result is True


@pytest.mark.asyncio
async def test_get_balance(provider):
    mock_client = AsyncMock()
    mock_client.get_balance = AsyncMock(return_value=Decimal("5000"))
    provider._client = mock_client
    bal = await provider.get_balance()
    assert bal.venue == "myriad"
    assert bal.available_cash == Decimal("5000")


@pytest.mark.asyncio
async def test_get_positions(provider):
    mock_client = AsyncMock()
    mock_client.get_positions = AsyncMock(
        return_value=[
            {
                "market_id": "m1",
                "side": "long",
                "size": 50,
                "price": 0.6,
                "current_price": 0.7,
                "pnl": 5,
            },
            {
                "market_id": "m2",
                "side": "short",
                "size": 30,
                "price": 0.4,
                "current_price": 0.3,
                "pnl": 3,
            },
        ]
    )
    provider._client = mock_client
    positions = await provider.get_positions()
    assert len(positions) == 2
    assert positions[0].market_id == "m1"
    assert positions[0].side == PositionSide.LONG
    assert positions[0].avg_entry_price == Decimal("0.6")
    assert positions[0].venue == "myriad"
    assert positions[1].side == PositionSide.SHORT


@pytest.mark.asyncio
async def test_get_positions_error(provider):
    mock_client = AsyncMock()
    mock_client.get_positions = AsyncMock(side_effect=Exception("API down"))
    provider._client = mock_client
    # MyriadProvider doesn't wrap get_positions in try/except, so it will raise
    with pytest.raises(Exception, match="API down"):
        await provider.get_positions()


@pytest.mark.asyncio
async def test_search_markets(provider):
    mock_client = AsyncMock()
    mock_client.get_markets = AsyncMock(
        return_value=[
            {
                "id": "m1",
                "title": "BTC 100k",
                "description": "Bitcoin",
                "category": "crypto",
                "status": "active",
            },
            {
                "id": "m2",
                "title": "ETH merge",
                "description": "Ethereum",
                "category": "crypto",
                "status": "active",
            },
            {
                "id": "m3",
                "title": "Fed rate",
                "description": "Economics",
                "category": "economics",
                "status": "closed",
            },
        ]
    )
    provider._client = mock_client
    markets = await provider.search_markets(query="btc")
    assert len(markets) == 1
    assert markets[0].market_id == "m1"
    assert markets[0].venue == "myriad"
    assert markets[0].is_active is True
    assert markets[0].category == "crypto"


@pytest.mark.asyncio
async def test_search_markets_no_query(provider):
    mock_client = AsyncMock()
    mock_client.get_markets = AsyncMock(
        return_value=[
            {
                "id": "m1",
                "title": "X",
                "description": "",
                "category": "other",
                "status": "active",
            },
        ]
    )
    provider._client = mock_client
    markets = await provider.search_markets(query="")
    assert len(markets) == 1


def test_rejected_helper(provider):
    order = NormalizedOrder(
        market_id="m1",
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        size=Decimal("5"),
        client_order_id="co1",
    )
    result = provider._rejected(order, "bad order")
    assert result.status == OrderStatus.REJECTED
    assert result.raw["error"] == "bad order"
    assert result.client_order_id == "co1"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
