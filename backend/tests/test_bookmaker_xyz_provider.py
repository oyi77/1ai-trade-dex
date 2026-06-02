"""Test suite for BookmakerXYZProvider."""

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
    with patch.dict(
        os.environ,
        {
            "AZURO_GRAPH_URL": "https://graph.azuro.org",
            "AZURO_RPC_URL": "https://rpc.azuro.org",
        },
        clear=False,
    ):
        from backend.markets.providers.bookmaker_xyz_provider import (
            BookmakerXYZProvider,
        )

        return BookmakerXYZProvider(paper_mode=True)


def test_manifest(provider):
    m = provider.manifest()
    assert m.name == "bookmaker_xyz"
    assert m.is_live_venue is False  # Azuro subgraph 301
    assert m.supports_paper_mode is True
    assert VenueCapability.MARKET_ORDERS in m.capabilities
    assert VenueCapability.MARKET_SEARCH in m.capabilities
    assert "AZURO_GRAPH_URL" in m.required_env_vars


@pytest.mark.asyncio
async def test_place_order_paper_mode(provider):
    order = NormalizedOrder(
        market_id="cond123",
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        size=Decimal("10"),
        price=Decimal("0.5"),
    )
    result = await provider.place_order(order)
    assert result.status == OrderStatus.FILLED
    assert result.filled_size == Decimal("10")


@pytest.mark.asyncio
async def test_place_order_paper_no_price(provider):
    order = NormalizedOrder(
        market_id="cond123",
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        size=Decimal("10"),
    )
    result = await provider.place_order(order)
    assert result.status == OrderStatus.FILLED
    assert result.filled_avg_price == Decimal("0.5")


@pytest.mark.asyncio
async def test_cancel_order_raises(provider):
    with pytest.raises(ValueError, match="non-cancellable"):
        await provider.cancel_order("any_id")


@pytest.mark.asyncio
async def test_get_balance_returns_zero(provider):
    bal = await provider.get_balance()
    assert bal.venue == "bookmaker_xyz"
    assert bal.available_cash == Decimal("0")


@pytest.mark.asyncio
async def test_get_positions_returns_empty(provider):
    positions = await provider.get_positions()
    assert positions == []


@pytest.mark.asyncio
async def test_get_markets(provider):
    mock_client = AsyncMock()
    mock_client.get_markets = AsyncMock(
        return_value=[
            {"conditionId": "c1", "question": "Will X win?"},
            {"conditionId": "c2", "title": "Match Y vs Z"},
        ]
    )
    provider._client = mock_client
    markets = await provider.get_markets()
    assert len(markets) == 2
    assert markets[0].venue == "bookmaker_xyz"
    assert markets[0].market_id == "c1"
    assert markets[0].title == "Will X win?"
    assert markets[0].is_active is True
    assert markets[1].title == "Match Y vs Z"


@pytest.mark.asyncio
async def test_get_markets_filters_non_dict(provider):
    mock_client = AsyncMock()
    mock_client.get_markets = AsyncMock(
        return_value=["not_a_dict", {"conditionId": "c1", "question": "Q?"}]
    )
    provider._client = mock_client
    markets = await provider.get_markets()
    assert len(markets) == 1


@pytest.mark.asyncio
async def test_place_order_live_no_key(provider):
    provider._paper_mode = False
    mock_client = AsyncMock()
    provider._client = mock_client
    order = NormalizedOrder(
        market_id="cond1",
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        size=Decimal("10"),
    )
    with patch.dict(os.environ, {"AZURO_PRIVATE_KEY": ""}, clear=False):
        result = await provider.place_order(order)
    assert result.status == OrderStatus.REJECTED
    assert "PRIVATE_KEY" in result.raw["error"]


@pytest.mark.asyncio
async def test_place_order_live_success(provider):
    provider._paper_mode = False
    mock_client = AsyncMock()
    mock_client.sign_and_send_bet = AsyncMock(return_value="0xtxhash123")
    mock_client.estimate_gas_fee = AsyncMock(return_value=10_000_000_000_000_000)
    provider._client = mock_client
    order = NormalizedOrder(
        market_id="cond1",
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        size=Decimal("10"),
        price=Decimal("0.5"),
    )
    with patch.dict(os.environ, {"AZURO_PRIVATE_KEY": "0xkey"}, clear=False):
        result = await provider.place_order(order)
    assert result.venue_order_id == "0xtxhash123"
    assert result.status == OrderStatus.FILLED


@pytest.mark.asyncio
async def test_place_order_live_exception(provider):
    provider._paper_mode = False
    mock_client = AsyncMock()
    mock_client.sign_and_send_bet = AsyncMock(side_effect=Exception("tx reverted"))
    provider._client = mock_client
    order = NormalizedOrder(
        market_id="cond1",
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        size=Decimal("10"),
    )
    with patch.dict(os.environ, {"AZURO_PRIVATE_KEY": "0xkey"}, clear=False):
        result = await provider.place_order(order)
    assert result.status == OrderStatus.REJECTED


@pytest.mark.asyncio
async def test_health_check(provider):
    mock_client = AsyncMock()
    mock_client.health_check = AsyncMock(return_value=True)
    provider._client = mock_client
    assert await provider.health_check() is True


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
