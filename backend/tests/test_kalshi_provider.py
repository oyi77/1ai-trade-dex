"""Test suite for KalshiProvider."""

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
        os.environ,
        {"KALSHI_API_KEY_ID": "test-key", "KALSHI_PRIVATE_KEY_PATH": "/tmp/test.pem"},
        clear=False,
    ):
        from backend.markets.providers.kalshi_provider import KalshiProvider

        return KalshiProvider(paper_mode=True)


def test_manifest(provider):
    m = provider.manifest()
    assert m.name == "kalshi"
    assert m.is_live_venue is True
    assert VenueCapability.LIMIT_ORDERS in m.capabilities
    assert VenueCapability.MARKET_ORDERS in m.capabilities
    assert VenueCapability.MARKET_SEARCH in m.capabilities
    assert m.maker_fee_bps == 175
    assert m.taker_fee_bps == 700


@pytest.mark.asyncio
async def test_place_order_paper_mode(provider):
    order = NormalizedOrder(
        market_id="FED-26MAY",
        side=OrderSide.YES,
        order_type=OrderType.LIMIT,
        size=Decimal("5"),
        price=Decimal("0.65"),
    )
    result = await provider.place_order(order)
    assert result.status == OrderStatus.FILLED
    assert result.filled_size == Decimal("5")
    assert result.filled_avg_price == Decimal("0.65")
    assert result.fees_paid > 0  # Kalshi charges fees


@pytest.mark.asyncio
async def test_place_order_paper_no_price(provider):
    order = NormalizedOrder(
        market_id="FED-26MAY",
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        size=Decimal("5"),
    )
    result = await provider.place_order(order)
    assert result.status == OrderStatus.FILLED
    assert result.filled_avg_price == Decimal("0.5")


@pytest.mark.asyncio
async def test_cancel_order_paper_mode(provider):
    result = await provider.cancel_order("test_id")
    assert result is True


@pytest.mark.asyncio
async def test_get_balance_paper_mode(provider):
    bal = await provider.get_balance()
    assert bal.venue == "kalshi"
    assert bal.available_cash == Decimal("10000")


@pytest.mark.asyncio
async def test_get_balance_live_mode():
    with patch.dict(
        os.environ,
        {"KALSHI_API_KEY_ID": "k", "KALSHI_PRIVATE_KEY_PATH": "/tmp/t.pem"},
        clear=False,
    ):
        from backend.markets.providers.kalshi_provider import KalshiProvider

        prov = KalshiProvider(paper_mode=False)
    mock_client = AsyncMock()
    mock_client.get_balance = AsyncMock(return_value={"available": 500, "locked": 100})
    prov._client = mock_client
    bal = await prov.get_balance()
    assert bal.available_cash == Decimal("500")
    assert bal.reserved_margin == Decimal("100")
    assert bal.total_equity == Decimal("600")


@pytest.mark.asyncio
async def test_place_order_live_rejects_no_price():
    with patch.dict(
        os.environ,
        {"KALSHI_API_KEY_ID": "k", "KALSHI_PRIVATE_KEY_PATH": "/tmp/t.pem"},
        clear=False,
    ):
        from backend.markets.providers.kalshi_provider import KalshiProvider

        prov = KalshiProvider(paper_mode=False)
    order = NormalizedOrder(
        market_id="FED",
        side=OrderSide.YES,
        order_type=OrderType.LIMIT,
        size=Decimal("2"),
    )
    result = await prov.place_order(order)
    assert result.status == OrderStatus.REJECTED
    assert "limit price" in result.raw["error"].lower()


@pytest.mark.asyncio
async def test_place_order_live_success():
    with patch.dict(
        os.environ,
        {"KALSHI_API_KEY_ID": "k", "KALSHI_PRIVATE_KEY_PATH": "/tmp/t.pem"},
        clear=False,
    ):
        from backend.markets.providers.kalshi_provider import KalshiProvider

        prov = KalshiProvider(paper_mode=False)
    mock_client = AsyncMock()
    mock_client.place_order = AsyncMock(
        return_value={
            "orders": [
                {
                    "order_id": "ord1",
                    "status": "filled",
                    "filled_count": 3,
                    "fees": 0.12,
                }
            ]
        }
    )
    prov._client = mock_client
    order = NormalizedOrder(
        market_id="FED-26MAY",
        side=OrderSide.YES,
        order_type=OrderType.LIMIT,
        size=Decimal("3"),
        price=Decimal("0.65"),
    )
    result = await prov.place_order(order)
    assert result.status == OrderStatus.FILLED
    assert result.filled_size == Decimal("3")
    assert result.venue_order_id == "ord1"


@pytest.mark.asyncio
async def test_place_order_live_exception():
    with patch.dict(
        os.environ,
        {"KALSHI_API_KEY_ID": "k", "KALSHI_PRIVATE_KEY_PATH": "/tmp/t.pem"},
        clear=False,
    ):
        from backend.markets.providers.kalshi_provider import KalshiProvider

        prov = KalshiProvider(paper_mode=False)
    mock_client = AsyncMock()
    mock_client.place_order = AsyncMock(side_effect=Exception("API error"))
    prov._client = mock_client
    order = NormalizedOrder(
        market_id="FED",
        side=OrderSide.YES,
        order_type=OrderType.LIMIT,
        size=Decimal("2"),
        price=Decimal("0.5"),
    )
    result = await prov.place_order(order)
    assert result.status == OrderStatus.REJECTED


def test_to_kalshi_order_yes(provider):
    order = NormalizedOrder(
        market_id="FED-26MAY-T3.00",
        side=OrderSide.YES,
        order_type=OrderType.LIMIT,
        size=Decimal("2"),
        price=Decimal("0.65"),
        client_order_id="co1",
    )
    payload = provider._to_kalshi_order(order)
    assert payload["ticker"] == "FED-26MAY-T3.00"
    assert payload["side"] == "yes"
    assert payload["action"] == "buy"
    assert payload["yes_price_dollars"] == 0.65
    assert "no_price_dollars" not in payload


def test_to_kalshi_order_no(provider):
    order = NormalizedOrder(
        market_id="FED-26MAY-T3.00",
        side=OrderSide.NO,
        order_type=OrderType.LIMIT,
        size=Decimal("2"),
        price=Decimal("0.37"),
        client_order_id="co2",
    )
    payload = provider._to_kalshi_order(order)
    assert payload["side"] == "no"
    assert payload["no_price_dollars"] == 0.37
    assert "yes_price_dollars" not in payload


def test_map_status(provider):
    assert provider._map_status("filled") == OrderStatus.FILLED
    assert provider._map_status("executed") == OrderStatus.FILLED
    assert provider._map_status("canceled") == OrderStatus.CANCELLED
    assert provider._map_status("cancelled") == OrderStatus.CANCELLED
    assert provider._map_status("rejected") == OrderStatus.REJECTED
    assert provider._map_status("open") == OrderStatus.OPEN
    assert provider._map_status("resting") == OrderStatus.OPEN


def test_extract_order_response(provider):
    # orders list
    resp = {"orders": [{"order_id": "a", "status": "open"}]}
    result = provider._extract_order_response(resp)
    assert result["order_id"] == "a"

    # orders dict
    resp = {"orders": {"order_id": "b"}}
    result = provider._extract_order_response(resp)
    assert result["order_id"] == "b"

    # order key
    resp = {"order": {"order_id": "c"}}
    result = provider._extract_order_response(resp)
    assert result["order_id"] == "c"

    # fallback to response itself
    resp = {"order_id": "d"}
    result = provider._extract_order_response(resp)
    assert result["order_id"] == "d"


@pytest.mark.asyncio
async def test_get_positions():
    with patch.dict(
        os.environ,
        {"KALSHI_API_KEY_ID": "k", "KALSHI_PRIVATE_KEY_PATH": "/tmp/t.pem"},
        clear=False,
    ):
        from backend.markets.providers.kalshi_provider import KalshiProvider

        prov = KalshiProvider(paper_mode=False)
    mock_client = AsyncMock()
    mock_client.get_positions = AsyncMock(
        return_value=[
            {
                "ticker": "FED",
                "side": "yes",
                "count": 5,
                "average_price": 0.65,
                "current_price": 0.70,
            },
            {"ticker": "BTC", "side": "no", "count": 10, "average_price": 0.30},
        ]
    )
    prov._client = mock_client
    positions = await prov.get_positions()
    assert len(positions) == 2
    assert positions[0].side == PositionSide.LONG
    assert positions[0].size == Decimal("5")
    assert positions[0].current_price == Decimal("0.70")
    assert positions[1].side == PositionSide.SHORT
    assert positions[1].current_price is None


@pytest.mark.asyncio
async def test_get_positions_filter_by_market():
    with patch.dict(
        os.environ,
        {"KALSHI_API_KEY_ID": "k", "KALSHI_PRIVATE_KEY_PATH": "/tmp/t.pem"},
        clear=False,
    ):
        from backend.markets.providers.kalshi_provider import KalshiProvider

        prov = KalshiProvider(paper_mode=False)
    mock_client = AsyncMock()
    mock_client.get_positions = AsyncMock(
        return_value=[
            {"ticker": "FED", "side": "yes", "count": 5, "average_price": 0.65},
            {"ticker": "BTC", "side": "no", "count": 10, "average_price": 0.30},
        ]
    )
    prov._client = mock_client
    positions = await prov.get_positions(market_id="FED")
    assert len(positions) == 1
    assert positions[0].market_id == "FED"


@pytest.mark.asyncio
async def test_get_positions_error_returns_empty():
    with patch.dict(
        os.environ,
        {"KALSHI_API_KEY_ID": "k", "KALSHI_PRIVATE_KEY_PATH": "/tmp/t.pem"},
        clear=False,
    ):
        from backend.markets.providers.kalshi_provider import KalshiProvider

        prov = KalshiProvider(paper_mode=False)
    mock_client = AsyncMock()
    mock_client.get_positions = AsyncMock(side_effect=Exception("API down"))
    prov._client = mock_client
    positions = await prov.get_positions()
    assert positions == []


@pytest.mark.asyncio
async def test_search_markets():
    with patch.dict(
        os.environ,
        {"KALSHI_API_KEY_ID": "k", "KALSHI_PRIVATE_KEY_PATH": "/tmp/t.pem"},
        clear=False,
    ):
        from backend.markets.providers.kalshi_provider import KalshiProvider

        prov = KalshiProvider(paper_mode=False)
    mock_client = AsyncMock()
    mock_client.get_markets = AsyncMock(
        return_value={
            "markets": [
                {
                    "ticker": "FED",
                    "title": "Fed rate cut",
                    "category": "economics",
                    "yes_bid_dollars": 0.65,
                    "volume_fp": 1000,
                    "status": "open",
                },
                {
                    "ticker": "BTC",
                    "title": "Bitcoin 100k",
                    "category": "crypto",
                    "yes_bid_dollars": 0.30,
                    "volume_fp": 5000,
                    "status": "open",
                },
            ]
        }
    )
    prov._client = mock_client
    markets = await prov.search_markets(query="fed")
    assert len(markets) == 1
    assert markets[0].market_id == "FED"
    assert markets[0].venue == "kalshi"
    assert markets[0].yes_price == Decimal("0.65")


@pytest.mark.asyncio
async def test_search_markets_with_category():
    with patch.dict(
        os.environ,
        {"KALSHI_API_KEY_ID": "k", "KALSHI_PRIVATE_KEY_PATH": "/tmp/t.pem"},
        clear=False,
    ):
        from backend.markets.providers.kalshi_provider import KalshiProvider

        prov = KalshiProvider(paper_mode=False)
    mock_client = AsyncMock()
    mock_client.get_markets = AsyncMock(
        return_value={
            "markets": [
                {
                    "ticker": "FED",
                    "title": "Fed",
                    "category": "economics",
                    "yes_bid_dollars": 0.65,
                    "status": "open",
                },
                {
                    "ticker": "BTC",
                    "title": "Bitcoin",
                    "category": "crypto",
                    "yes_bid_dollars": 0.30,
                    "status": "open",
                },
            ]
        }
    )
    prov._client = mock_client
    markets = await prov.search_markets(category="crypto")
    assert len(markets) == 1
    assert markets[0].market_id == "BTC"


@pytest.mark.asyncio
async def test_search_markets_error_returns_empty():
    with patch.dict(
        os.environ,
        {"KALSHI_API_KEY_ID": "k", "KALSHI_PRIVATE_KEY_PATH": "/tmp/t.pem"},
        clear=False,
    ):
        from backend.markets.providers.kalshi_provider import KalshiProvider

        prov = KalshiProvider(paper_mode=False)
    mock_client = AsyncMock()
    mock_client.get_markets = AsyncMock(side_effect=Exception("down"))
    prov._client = mock_client
    markets = await prov.search_markets()
    assert markets == []


def test_kalshi_fee():
    from backend.markets.providers.kalshi_provider import _kalshi_fee

    fee = _kalshi_fee(Decimal("0.50"), Decimal("10"))
    assert fee > Decimal("0")
    fee_extreme = _kalshi_fee(Decimal("0.95"), Decimal("10"))
    assert fee_extreme < fee  # lower fee at extremes


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
