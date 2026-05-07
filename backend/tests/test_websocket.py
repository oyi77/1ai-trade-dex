"""
Tests for Polymarket WebSocket client and orderbook cache.
"""

import asyncio
import pytest
from backend.data.polymarket_websocket import (
    PolymarketWebSocket,
    WebSocketConfig,
    ChannelType,
    OrderbookSnapshot,
    TradeEvent,
)
from backend.data.orderbook_cache import OrderbookCache, get_orderbook_cache


@pytest.mark.asyncio
async def test_orderbook_cache_update():
    cache = OrderbookCache(max_age_seconds=30.0)

    bids = [{"price": "0.55", "size": "100"}]
    asks = [{"price": "0.60", "size": "150"}]

    await cache.update("token_123", bids, asks)

    book = await cache.get("token_123")
    assert book is not None
    assert book.token_id == "token_123"
    assert book.mid_price == 0.575
    assert book.best_bid == 0.55
    assert book.best_ask == 0.60


@pytest.mark.asyncio
async def test_orderbook_cache_stale():
    cache = OrderbookCache(max_age_seconds=0.1)

    await cache.update("token_123", [{"price": "0.50", "size": "100"}], [])

    await asyncio.sleep(0.2)

    book = await cache.get("token_123")
    assert book is None


@pytest.mark.asyncio
async def test_orderbook_cache_mid_price():
    cache = OrderbookCache()

    await cache.update(
        "token_123",
        [{"price": "0.50", "size": "100"}],
        [{"price": "0.52", "size": "100"}],
    )

    price = await cache.get_mid_price("token_123")
    assert price == 0.51


@pytest.mark.asyncio
async def test_orderbook_cache_prune():
    cache = OrderbookCache(max_age_seconds=0.1)

    await cache.update("token_1", [{"price": "0.50", "size": "100"}], [])
    await cache.update("token_2", [{"price": "0.60", "size": "100"}], [])

    assert cache.size == 2

    await asyncio.sleep(0.2)

    removed = await cache.prune_stale()
    assert removed == 2
    assert cache.size == 0


def test_websocket_config_market_channel():
    config = WebSocketConfig(
        channel=ChannelType.MARKET, asset_ids=["token_1", "token_2"]
    )

    assert config.channel == ChannelType.MARKET
    assert len(config.asset_ids) == 2
    assert config.heartbeat_interval == 10.0


def test_websocket_config_user_channel():
    config = WebSocketConfig(
        channel=ChannelType.USER,
        condition_ids=["condition_1"],
        api_key="key",
        api_secret="secret",
        api_passphrase="pass",
    )

    assert config.channel == ChannelType.USER
    assert config.api_key == "key"


@pytest.mark.asyncio
async def test_websocket_event_handlers():
    config = WebSocketConfig(channel=ChannelType.MARKET, asset_ids=["token_1"])

    ws = PolymarketWebSocket(config)

    orderbook_called = False
    trade_called = False

    def handle_orderbook(snapshot):
        nonlocal orderbook_called
        orderbook_called = True
        assert snapshot.asset_id == "token_1"

    def handle_trade(trade):
        nonlocal trade_called
        trade_called = True
        assert trade.asset_id == "token_1"

    ws.on_orderbook(handle_orderbook)
    ws.on_trade(handle_trade)

    snapshot = OrderbookSnapshot(
        asset_id="token_1",
        market="market_1",
        bids=[{"price": "0.50", "size": "100"}],
        asks=[{"price": "0.52", "size": "100"}],
        timestamp=1234567890,
    )

    trade = TradeEvent(
        asset_id="token_1", price="0.51", size="50", side="BUY", timestamp=1234567890
    )

    await ws._handle_orderbook(snapshot.__dict__)
    await ws._handle_trade(trade.__dict__)

    assert orderbook_called
    assert trade_called


def test_orderbook_snapshot_properties():
    snapshot = OrderbookSnapshot(
        asset_id="token_1",
        market="market_1",
        bids=[{"price": "0.50", "size": "100"}, {"price": "0.49", "size": "200"}],
        asks=[{"price": "0.52", "size": "150"}, {"price": "0.53", "size": "250"}],
        timestamp=1234567890,
    )

    assert len(snapshot.bids) == 2
    assert len(snapshot.asks) == 2


@pytest.mark.asyncio
async def test_get_orderbook_cache_singleton():
    cache1 = get_orderbook_cache()
    cache2 = get_orderbook_cache()

    assert cache1 is cache2


@pytest.mark.asyncio
async def test_user_websocket_config():
    config = WebSocketConfig(
        channel=ChannelType.USER,
        condition_ids=["condition_1"],
        api_key="test_key",
        api_secret="test_secret",
        api_passphrase="test_pass",
    )

    ws = PolymarketWebSocket(config)

    assert ws.config.channel == ChannelType.USER
    assert ws.config.api_key == "test_key"
    assert len(ws.config.condition_ids) == 1


@pytest.mark.asyncio
async def test_user_order_handler():
    config = WebSocketConfig(
        channel=ChannelType.USER,
        condition_ids=["condition_1"],
        api_key="key",
        api_secret="secret",
        api_passphrase="pass",
    )

    ws = PolymarketWebSocket(config)

    order_received = False

    def handle_order(event):
        nonlocal order_received
        order_received = True
        assert event["id"] == "order_123"
        assert event["status"] == "MATCHED"

    ws.on_user_order(handle_order)

    event = {
        "event_type": "user_order",
        "id": "order_123",
        "status": "MATCHED",
        "price": "0.65",
        "size": "100",
    }

    await ws._handle_user_order(event)

    assert order_received


@pytest.mark.asyncio
async def test_user_trade_handler():
    config = WebSocketConfig(
        channel=ChannelType.USER,
        condition_ids=["condition_1"],
        api_key="key",
        api_secret="secret",
        api_passphrase="pass",
    )

    ws = PolymarketWebSocket(config)

    trade_received = False

    def handle_trade(event):
        nonlocal trade_received
        trade_received = True
        assert event["id"] == "trade_456"
        assert event["status"] == "CONFIRMED"

    ws.on_user_trade(handle_trade)

    event = {
        "event_type": "user_trade",
        "id": "trade_456",
        "status": "CONFIRMED",
        "price": "0.65",
        "size": "100",
    }

    await ws._handle_user_trade(event)

    assert trade_received
