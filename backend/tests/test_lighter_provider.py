"""Test suite for LighterProvider."""

import os
import pytest
from decimal import Decimal
from unittest.mock import patch, MagicMock, AsyncMock

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
    with patch.dict(os.environ, {"WALLET_PRIVATE_KEY": "0x" + "aa" * 32}, clear=False):
        with patch(
            "backend.clients.lighter_client.LighterClient.__init__", return_value=None
        ):
            from backend.markets.providers.lighter_provider import LighterProvider

            p = LighterProvider(paper_mode=True)
            p._client = MagicMock()
            return p


def test_manifest(provider):
    m = provider.manifest()
    assert m.name == "lighter"
    assert m.is_live_venue is True
    assert VenueCapability.LIMIT_ORDERS in m.capabilities
    assert VenueCapability.SHORT_SELLING in m.capabilities
    assert "WALLET_PRIVATE_KEY" in m.required_env_vars


@pytest.mark.asyncio
async def test_place_order_paper_mode(provider):
    order = NormalizedOrder(
        market_id="1",
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        size=Decimal("10"),
        price=Decimal("3500"),
    )
    result = await provider.place_order(order)
    assert result.status == OrderStatus.FILLED
    assert result.filled_size == Decimal("10")
    assert result.venue_order_id.startswith("paper_lt_")


@pytest.mark.asyncio
async def test_place_order_live_success(provider):
    provider._paper_mode = False
    mock_client = AsyncMock()
    mock_client.place_order = AsyncMock(
        return_value={"order_id": "lt_456", "status": "open"}
    )
    provider._client = mock_client
    order = NormalizedOrder(
        market_id="1",
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        size=Decimal("10"),
        price=Decimal("3500"),
    )
    result = await provider.place_order(order)
    assert result.venue_order_id == "lt_456"
    assert result.status == OrderStatus.OPEN


@pytest.mark.asyncio
async def test_place_order_live_exception(provider):
    provider._paper_mode = False
    mock_client = AsyncMock()
    mock_client.place_order = AsyncMock(side_effect=Exception("zk proof fail"))
    provider._client = mock_client
    order = NormalizedOrder(
        market_id="1",
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        size=Decimal("10"),
    )
    result = await provider.place_order(order)
    assert result.status == OrderStatus.REJECTED


@pytest.mark.asyncio
async def test_cancel_order(provider):
    mock_client = AsyncMock()
    mock_client.cancel_order = AsyncMock(return_value=True)
    provider._client = mock_client
    result = await provider.cancel_order("5:123")
    assert result is True
    mock_client.cancel_order.assert_called_once_with(5, 123)


@pytest.mark.asyncio
async def test_cancel_order_fails(provider):
    mock_client = AsyncMock()
    mock_client.cancel_order = AsyncMock(side_effect=Exception("fail"))
    provider._client = mock_client
    result = await provider.cancel_order("5:999")
    assert result is False


@pytest.mark.asyncio
async def test_get_balance_list_format(provider):
    mock_client = MagicMock()
    mock_client._ensure_initialized = MagicMock()

    eth_acc = MagicMock()
    eth_acc.symbol = "ETH"
    eth_acc.balance = "5"

    usdc_acc = MagicMock()
    usdc_acc.symbol = "USDC"
    usdc_acc.balance = "2000"

    result = MagicMock()
    result.accounts = [eth_acc, usdc_acc]

    mock_client._account_api.account = AsyncMock(return_value=result)
    provider._client = mock_client
    bal = await provider.get_balance()
    assert bal.venue == "lighter"
    assert bal.available_cash == Decimal("2000")
    assert bal.total_equity == Decimal("2000")
    assert bal.reserved_margin == Decimal("0")


@pytest.mark.asyncio
async def test_get_balance_dict_format(provider):
    mock_client = MagicMock()
    mock_client._ensure_initialized = MagicMock()

    usdc_acc = MagicMock()
    usdc_acc.symbol = "USDC"
    usdc_acc.balance = "1000"

    result = MagicMock()
    result.accounts = [usdc_acc]

    mock_client._account_api.account = AsyncMock(return_value=result)
    provider._client = mock_client
    bal = await provider.get_balance()
    assert bal.available_cash == Decimal("1000")


@pytest.mark.asyncio
async def test_get_positions(provider):
    mock_client = AsyncMock()
    mock_client.get_positions = AsyncMock(
        return_value=[
            {
                "market_id": 1,
                "size": 5,
                "side": "long",
                "entry_price": "3500",
                "mark_price": "3600",
                "unrealized_pnl": "500",
            },
            {
                "marketId": 2,
                "contracts": 3,
                "side": "short",
                "entryPrice": "100000",
                "markPrice": "99000",
                "unrealizedPnl": "300",
            },
            {
                "market_id": 3,
                "size": 0,
                "side": "long",
                "entry_price": "0",
                "mark_price": "150",
            },
        ]
    )
    provider._client = mock_client
    positions = await provider.get_positions()
    assert len(positions) == 2
    assert positions[0].market_id == "1"
    assert positions[0].side == PositionSide.LONG
    assert positions[1].side == PositionSide.SHORT


@pytest.mark.asyncio
async def test_get_positions_dict_format(provider):
    mock_client = AsyncMock()
    mock_client.get_positions = AsyncMock(
        return_value={
            "positions": [
                {
                    "market_id": 1,
                    "size": 5,
                    "side": "long",
                    "entry_price": "3500",
                    "mark_price": "3600",
                },
            ]
        }
    )
    provider._client = mock_client
    positions = await provider.get_positions()
    assert len(positions) == 1


@pytest.mark.asyncio
async def test_health_check(provider):
    mock_client = AsyncMock()
    mock_client.health_check = AsyncMock(return_value=True)
    provider._client = mock_client
    assert await provider.health_check() is True


@pytest.mark.asyncio
async def test_watch_account(provider):
    mock_client = AsyncMock()
    mock_client.watch_account = AsyncMock(return_value={"balance": 1000})
    provider._client = mock_client
    result = await provider.watch_account()
    assert result == {"balance": 1000}


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
