"""Test suite for HyperliquidProvider."""

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
            "backend.clients.hyperliquid_client.HyperliquidClient.__init__",
            return_value=None,
        ):
            from backend.markets.providers.hyperliquid_provider import (
                HyperliquidProvider,
            )

            p = HyperliquidProvider(paper_mode=True)
            p._client = MagicMock()
            return p


def test_manifest(provider):
    m = provider.manifest()
    assert m.name == "hyperliquid"
    assert m.is_live_venue is True
    assert VenueCapability.LIMIT_ORDERS in m.capabilities
    assert VenueCapability.SHORT_SELLING in m.capabilities
    assert "WALLET_PRIVATE_KEY" in m.required_env_vars


@pytest.mark.asyncio
async def test_place_order_paper_mode(provider):
    order = NormalizedOrder(
        market_id="ETH",
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        size=Decimal("1"),
        price=Decimal("3500"),
    )
    result = await provider.place_order(order)
    assert result.status == OrderStatus.FILLED
    assert result.filled_size == Decimal("1")
    assert result.venue_order_id.startswith("paper_hl_")


@pytest.mark.asyncio
async def test_cancel_order_paper_mode(provider):
    result = await provider.cancel_order("paper_test")
    assert result is False  # paper mode doesn't have order stored


@pytest.mark.asyncio
async def test_get_balance_paper_mode(provider):
    """Paper mode just returns mock via client."""
    mock_client = MagicMock()
    mock_client.get_balance.return_value = {
        "marginSummary": {"accountValue": "5000", "totalMarginUsed": "200"}
    }
    provider._client = mock_client
    bal = await provider.get_balance()
    assert bal.venue == "hyperliquid"
    assert bal.available_cash == Decimal("5000")
    assert bal.reserved_margin == Decimal("200")


@pytest.mark.asyncio
async def test_get_positions(provider):
    mock_client = AsyncMock()
    mock_client.get_positions = AsyncMock(
        return_value=[
            {
                "position": {
                    "coin": "ETH",
                    "szi": "2.5",
                    "entryPx": "3500",
                    "oraclePx": "3600",
                    "unrealizedPnl": "250",
                }
            },
            {
                "position": {
                    "coin": "BTC",
                    "szi": "-0.1",
                    "entryPx": "100000",
                    "oraclePx": "99000",
                    "unrealizedPnl": "100",
                }
            },
            {
                "position": {
                    "coin": "SOL",
                    "szi": "0",
                    "entryPx": "0",
                    "oraclePx": "150",
                }
            },
        ]
    )
    provider._client = mock_client
    positions = await provider.get_positions()
    assert len(positions) == 2  # zero-size filtered
    assert positions[0].market_id == "ETH"
    assert positions[0].side == PositionSide.LONG
    assert positions[0].size == Decimal("2.5")
    assert positions[0].current_price == Decimal("3600")
    assert positions[1].market_id == "BTC"
    assert positions[1].side == PositionSide.SHORT


@pytest.mark.asyncio
async def test_place_order_live_success(provider):
    provider._paper_mode = False
    mock_client = AsyncMock()
    mock_client.place_order = AsyncMock(return_value={"oid": 12345, "status": "open"})
    provider._client = mock_client
    order = NormalizedOrder(
        market_id="ETH",
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        size=Decimal("1"),
        price=Decimal("3500"),
    )
    result = await provider.place_order(order)
    assert result.venue_order_id == "12345"
    assert result.status == OrderStatus.OPEN


@pytest.mark.asyncio
async def test_place_order_live_exception(provider):
    provider._paper_mode = False
    mock_client = AsyncMock()
    mock_client.place_order = AsyncMock(side_effect=Exception("RPC error"))
    provider._client = mock_client
    order = NormalizedOrder(
        market_id="ETH",
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        size=Decimal("1"),
        price=Decimal("3500"),
    )
    result = await provider.place_order(order)
    assert result.status == OrderStatus.REJECTED
    assert "RPC error" in result.raw["error"]


@pytest.mark.asyncio
async def test_cancel_order_live(provider):
    provider._paper_mode = False
    mock_client = AsyncMock()
    mock_client.cancel_order = AsyncMock(return_value=True)
    provider._client = mock_client
    result = await provider.cancel_order("ETH:12345")
    assert result is True
    mock_client.cancel_order.assert_called_once_with("ETH", 12345)


@pytest.mark.asyncio
async def test_cancel_order_live_fails(provider):
    provider._paper_mode = False
    mock_client = AsyncMock()
    mock_client.cancel_order = AsyncMock(side_effect=Exception("not found"))
    provider._client = mock_client
    result = await provider.cancel_order("ETH:999")
    assert result is False


@pytest.mark.asyncio
async def test_health_check(provider):
    mock_client = AsyncMock()
    mock_client.health_check = AsyncMock(return_value=True)
    provider._client = mock_client
    assert await provider.health_check() is True


def test_rejected_helper(provider):
    order = NormalizedOrder(
        market_id="ETH",
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        size=Decimal("1"),
        price=Decimal("3500"),
        client_order_id="co1",
    )
    result = provider._rejected(order, "test")
    assert result.status == OrderStatus.REJECTED
    assert result.raw["error"] == "test"
    assert result.remaining_size == Decimal("1")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
