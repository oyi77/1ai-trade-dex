"""Test suite for PolymarketProvider."""

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
    with patch.dict(
        os.environ,
        {"POLYMARKET_BUILDER_API_KEY": "k", "POLYMARKET_BUILDER_SECRET": "s"},
        clear=False,
    ):
        from backend.markets.providers.polymarket_provider import PolymarketProvider

        return PolymarketProvider(paper_mode=True)


def test_manifest(provider):
    m = provider.manifest()
    assert m.name == "polymarket"
    assert m.is_live_venue is True
    assert m.supports_paper_mode is True
    assert VenueCapability.LIMIT_ORDERS in m.capabilities
    assert VenueCapability.MARKET_SEARCH in m.capabilities
    assert VenueCapability.STREAMING_FILLS in m.capabilities
    assert "POLYMARKET_BUILDER_API_KEY" in m.required_env_vars


@pytest.mark.asyncio
async def test_place_order_paper_mode(provider):
    order = NormalizedOrder(
        market_id="cond123",
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        size=Decimal("50"),
        price=Decimal("0.65"),
    )
    result = await provider.place_order(order)
    assert result.status == OrderStatus.FILLED
    assert result.filled_size == Decimal("50")
    assert result.filled_avg_price == Decimal("0.65")
    assert result.venue_order_id.startswith("paper_")


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
async def test_cancel_order_paper_mode(provider):
    result = await provider.cancel_order("paper_test")
    assert result is True


@pytest.mark.asyncio
async def test_get_balance_paper_mode(provider):
    bal = await provider.get_balance()
    assert bal.venue == "polymarket"
    assert bal.available_cash == Decimal("10000")
    assert bal.total_equity == Decimal("10000")


@pytest.mark.asyncio
async def test_get_positions_paper_mode(provider):
    positions = await provider.get_positions()
    assert positions == []


@pytest.mark.asyncio
async def test_place_order_live_rejects_no_price():
    with patch.dict(
        os.environ,
        {"POLYMARKET_BUILDER_API_KEY": "k", "POLYMARKET_BUILDER_SECRET": "s"},
        clear=False,
    ):
        from backend.markets.providers.polymarket_provider import PolymarketProvider

        prov = PolymarketProvider(paper_mode=False)
    order = NormalizedOrder(
        market_id="cond123",
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        size=Decimal("10"),
    )
    result = await prov.place_order(order)
    assert result.status == OrderStatus.REJECTED
    assert "limit price" in result.raw["error"].lower()


@pytest.mark.asyncio
async def test_place_order_live_rejects_no_token_id():
    with patch.dict(
        os.environ,
        {"POLYMARKET_BUILDER_API_KEY": "k", "POLYMARKET_BUILDER_SECRET": "s"},
        clear=False,
    ):
        from backend.markets.providers.polymarket_provider import PolymarketProvider

        prov = PolymarketProvider(paper_mode=False)
    order = NormalizedOrder(
        market_id="",
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        size=Decimal("10"),
        price=Decimal("0.5"),
    )
    # Empty market_id => empty token_id => rejected
    token = prov._resolve_token_id(order)
    assert token == ""


def test_resolve_token_id_yes_side(provider):
    order = NormalizedOrder(
        market_id="cond1",
        side=OrderSide.YES,
        order_type=OrderType.LIMIT,
        size=Decimal("1"),
        metadata={"yes_token_id": "tok_yes", "no_token_id": "tok_no"},
    )
    assert provider._resolve_token_id(order) == "tok_yes"


def test_resolve_token_id_no_side(provider):
    order = NormalizedOrder(
        market_id="cond1",
        side=OrderSide.NO,
        order_type=OrderType.LIMIT,
        size=Decimal("1"),
        metadata={"yes_token_id": "tok_yes", "no_token_id": "tok_no"},
    )
    assert provider._resolve_token_id(order) == "tok_no"


def test_resolve_token_id_fallback_to_market_id(provider):
    order = NormalizedOrder(
        market_id="cond_fallback",
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        size=Decimal("1"),
    )
    assert provider._resolve_token_id(order) == "cond_fallback"


def test_resolve_token_id_clob_token_metadata(provider):
    order = NormalizedOrder(
        market_id="cond1",
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        size=Decimal("1"),
        metadata={"clob_token_id": "clob_tok"},
    )
    assert provider._resolve_token_id(order) == "clob_tok"


def test_rejected_helper(provider):
    order = NormalizedOrder(
        market_id="c",
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        size=Decimal("5"),
        client_order_id="co1",
    )
    result = provider._rejected(order, "test reason")
    assert result.status == OrderStatus.REJECTED
    assert result.raw["error"] == "test reason"
    assert result.filled_size == Decimal("0")
    assert result.remaining_size == Decimal("5")
    assert result.client_order_id == "co1"
    assert result.fees_paid == Decimal("0")


@pytest.mark.asyncio
async def test_search_markets_mocks_gamma(provider):
    mock_gamma = [
        {
            "condition_id": "abc",
            "question": "Will X happen?",
            "description": "desc",
            "category": "crypto",
            "outcomePrices": "[0.70, 0.30]",
            "volume": 10000,
            "openInterest": 5000,
            "active": True,
        },
    ]
    import backend.data.gamma as gamma_mod

    with patch.object(gamma_mod, "fetch_markets", return_value=mock_gamma):
        markets = await provider.search_markets(query="happen")
    assert len(markets) == 1
    assert markets[0].market_id == "abc"
    assert markets[0].yes_price == Decimal("0.70")
    assert markets[0].no_price == Decimal("0.30")
    assert markets[0].venue == "polymarket"


@pytest.mark.asyncio
async def test_search_markets_filters_category(provider):
    mock_gamma = [
        {
            "condition_id": "a",
            "question": "Crypto?",
            "category": "crypto",
            "outcomePrices": "[0.5]",
            "volume": 1,
            "active": True,
        },
        {
            "condition_id": "b",
            "question": "Econ?",
            "category": "economics",
            "outcomePrices": "[0.5]",
            "volume": 1,
            "active": True,
        },
    ]
    import backend.data.gamma as gamma_mod

    with patch.object(gamma_mod, "fetch_markets", return_value=mock_gamma):
        markets = await provider.search_markets(category="crypto")
    assert len(markets) == 1
    assert markets[0].market_id == "a"


@pytest.mark.asyncio
async def test_search_markets_error_returns_empty(provider):
    import backend.data.gamma as gamma_mod

    with patch.object(gamma_mod, "fetch_markets", side_effect=Exception("API down")):
        markets = await provider.search_markets()
    assert markets == []


@pytest.mark.asyncio
async def test_get_positions_with_mock_clob():
    with patch.dict(
        os.environ,
        {"POLYMARKET_BUILDER_API_KEY": "k", "POLYMARKET_BUILDER_SECRET": "s"},
        clear=False,
    ):
        from backend.markets.providers.polymarket_provider import PolymarketProvider

        prov = PolymarketProvider(paper_mode=False)

    mock_clob = AsyncMock()
    mock_clob._account = MagicMock()
    mock_clob._account.address = "0x1234"
    mock_clob.get_trader_positions = AsyncMock(
        return_value=[
            {
                "market_id": "m1",
                "outcome": "YES",
                "size": 100,
                "avg_price": 0.65,
                "current_price": 0.70,
                "unrealized_pnl": 5.0,
            },
            {"market_id": "m2", "outcome": "NO", "size": 50, "avg_price": 0.30},
        ]
    )
    mock_clob.__aenter__ = AsyncMock(return_value=mock_clob)
    mock_clob.__aexit__ = AsyncMock(return_value=False)

    with patch(
        "backend.markets.providers.polymarket_provider.clob_from_settings",
        return_value=mock_clob,
    ):
        positions = await prov.get_positions()

    assert len(positions) == 2
    assert positions[0].market_id == "m1"
    assert positions[0].side == PositionSide.LONG
    assert positions[0].size == Decimal("100")
    assert positions[0].current_price == Decimal("0.70")
    assert positions[1].side == PositionSide.SHORT


@pytest.mark.asyncio
async def test_get_positions_filters_by_market_id():
    with patch.dict(
        os.environ,
        {"POLYMARKET_BUILDER_API_KEY": "k", "POLYMARKET_BUILDER_SECRET": "s"},
        clear=False,
    ):
        from backend.markets.providers.polymarket_provider import PolymarketProvider

        prov = PolymarketProvider(paper_mode=False)

    mock_clob = AsyncMock()
    mock_clob._account = MagicMock()
    mock_clob._account.address = "0x1234"
    mock_clob.get_trader_positions = AsyncMock(
        return_value=[
            {"market_id": "m1", "outcome": "YES", "size": 100, "avg_price": 0.65},
            {"market_id": "m2", "outcome": "NO", "size": 50, "avg_price": 0.30},
        ]
    )
    mock_clob.__aenter__ = AsyncMock(return_value=mock_clob)
    mock_clob.__aexit__ = AsyncMock(return_value=False)

    with patch(
        "backend.markets.providers.polymarket_provider.clob_from_settings",
        return_value=mock_clob,
    ):
        positions = await prov.get_positions(market_id="m1")
    assert len(positions) == 1
    assert positions[0].market_id == "m1"


@pytest.mark.asyncio
async def test_get_positions_no_wallet():
    with patch.dict(
        os.environ,
        {"POLYMARKET_BUILDER_API_KEY": "k", "POLYMARKET_BUILDER_SECRET": "s"},
        clear=False,
    ):
        from backend.markets.providers.polymarket_provider import PolymarketProvider

        prov = PolymarketProvider(paper_mode=False)

    mock_clob = AsyncMock()
    mock_clob._account = None
    mock_clob.__aenter__ = AsyncMock(return_value=mock_clob)
    mock_clob.__aexit__ = AsyncMock(return_value=False)

    with patch(
        "backend.markets.providers.polymarket_provider.clob_from_settings",
        return_value=mock_clob,
    ):
        positions = await prov.get_positions()
    assert positions == []


@pytest.mark.asyncio
async def test_get_positions_error_returns_empty():
    with patch.dict(
        os.environ,
        {"POLYMARKET_BUILDER_API_KEY": "k", "POLYMARKET_BUILDER_SECRET": "s"},
        clear=False,
    ):
        from backend.markets.providers.polymarket_provider import PolymarketProvider

        prov = PolymarketProvider(paper_mode=False)

    mock_clob = AsyncMock()
    mock_clob.__aenter__ = AsyncMock(side_effect=Exception("CLOB down"))
    mock_clob.__aexit__ = AsyncMock(return_value=False)

    with patch(
        "backend.markets.providers.polymarket_provider.clob_from_settings",
        return_value=mock_clob,
    ):
        positions = await prov.get_positions()
    assert positions == []


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
