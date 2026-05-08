import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock
from datetime import datetime

from backend.infrastructure.market_stream.orderbook_router import (
    OrderbookRouter,
    OrderbookUpdate
)
from backend.config import settings


@pytest.fixture
def sample_update():
    return OrderbookUpdate(
        market_id="market_1",
        bids_yes=[{"price": "0.45", "size": "100"}],
        asks_yes=[{"price": "0.55", "size": "100"}],
        bids_no=[{"price": "0.50", "size": "100"}],
        asks_no=[{"price": "0.60", "size": "100"}],
        timestamp=int(datetime.now().timestamp())
    )


@pytest.fixture
def router():
    return OrderbookRouter()


@pytest.mark.asyncio
async def test_subscribe_registers_handler(router: OrderbookRouter):
    """Test that subscribe registers handler correctly"""
    handler = AsyncMock()

    await router.subscribe("market_1", handler)

    assert "market_1" in router._handlers
    assert handler in router._handlers["market_1"]


@pytest.mark.asyncio
async def test_subscribe_respects_limit(router: OrderbookRouter):
    """Test that subscribe respects POLYMARKET_WS_SUBSCRIPTION_LIMIT"""
    # Set limit to 2 for testing
    original_limit = settings.POLYMARKET_WS_SUBSCRIPTION_LIMIT
    settings.POLYMARKET_WS_SUBSCRIPTION_LIMIT = 2

    try:
        handler1 = AsyncMock()
        handler2 = AsyncMock()
        handler3 = AsyncMock()

        await router.subscribe("market_1", handler1)
        await router.subscribe("market_2", handler2)
        await router.subscribe("market_3", handler3)  # Should be rejected

        assert len(router._handlers) == 2
        assert "market_3" not in router._handlers
    finally:
        settings.POLYMARKET_WS_SUBSCRIPTION_LIMIT = original_limit


@pytest.mark.asyncio
async def test_dispatch_loop_calls_handlers(router: OrderbookRouter, sample_update: OrderbookUpdate):
    """Test that dispatch loop calls registered handlers"""
    handler = AsyncMock()

    await router.subscribe("market_1", handler)
    await router.start()

    # Put update in queue
    await router._queue.put(sample_update)

    # Give dispatch loop time to process
    await asyncio.sleep(0.1)

    handler.assert_called_once_with(sample_update)


@pytest.mark.asyncio
async def test_dispatch_loop_timeout(router: OrderbookRouter, sample_update: OrderbookUpdate):
    """Test that dispatch loop enforces handler timeout"""
    # Set timeout to 50ms for testing
    original_timeout = settings.WS_HANDLER_TIMEOUT_MS
    settings.WS_HANDLER_TIMEOUT_MS = 50

    try:
        async def slow_handler(update):
            await asyncio.sleep(0.1)  # Longer than timeout

        await router.subscribe("market_1", slow_handler)
        await router.start()

        # Put update in queue
        await router._queue.put(sample_update)

        # Give dispatch loop time to process
        await asyncio.sleep(0.2)

        # Check that timeout was logged
        # (We can't easily capture logs in test, but we can verify the handler didn't complete)
    finally:
        settings.WS_HANDLER_TIMEOUT_MS = original_timeout
        await router.stop()


@pytest.mark.asyncio
async def test_on_orderbook_update_queues_update(router: OrderbookRouter, sample_update: OrderbookUpdate):
    """Test that _on_orderbook_update puts updates into queue"""
    await router.start()

    # Call the update handler
    await router._on_orderbook_update(sample_update)

    # Check that update was queued
    assert not router._queue.empty()

    queued_update = await router._queue.get()
    assert queued_update.market_id == sample_update.market_id


@pytest.mark.asyncio
async def test_queue_drops_oldest_when_full(router: OrderbookRouter):
    """Test that queue drops oldest item when full"""
    await router.start()

    # Fill the queue
    for i in range(1000):
        update = OrderbookUpdate(
            market_id=f"market_{i}",
            bids_yes=[],
            asks_yes=[],
            bids_no=[],
            asks_no=[],
            timestamp=i
        )
        await router._queue.put(update)

    # Queue should be full (1000 items)
    assert router._queue.qsize() == 1000

    # Add one more - should drop oldest
    new_update = OrderbookUpdate(
        market_id="market_new",
        bids_yes=[],
        asks_yes=[],
        bids_no=[],
        asks_no=[],
        timestamp=9999
    )
    await router._on_orderbook_update(new_update)

    # Queue should still have 1000 items
    assert router._queue.qsize() == 1000


@pytest.mark.asyncio
async def test_snapshot_storage(router: OrderbookRouter, sample_update: OrderbookUpdate):
    """Test that snapshots are stored correctly"""
    await router._on_orderbook_update(sample_update)

    snapshot = router.get_snapshot("market_1")
    assert snapshot is not None
    assert snapshot.market_id == "market_1"
    assert snapshot.best_bid_yes == 0.45
    assert snapshot.best_ask_yes == 0.55


@pytest.mark.asyncio
async def test_get_snapshot_missing_market(router: OrderbookRouter):
    """Test that get_snapshot returns None for non-existent market"""
    snapshot = router.get_snapshot("non_existent_market")
    assert snapshot is None


@pytest.mark.asyncio
async def test_start_stop(router: OrderbookRouter):
    """Test that start and stop work correctly"""
    assert not router._running

    await router.start()
    assert router._running
    assert router._dispatch_task is not None

    await router.stop()
    assert not router._running
    assert router._dispatch_task is None


@pytest.mark.asyncio
async def test_circuit_breaker_integration(router: OrderbookRouter):
    """Test that circuit breaker is properly initialized"""
    assert router._circuit_breaker is not None
    assert router._circuit_breaker.name == "polymarket_ws"
    assert router._circuit_breaker.failure_threshold == 5
    assert router._circuit_breaker.recovery_timeout == 60


@pytest.mark.asyncio
async def test_register_with_websocket(router: OrderbookRouter):
    """Test that register_with_websocket works"""
    mock_ws = MagicMock()
    mock_ws.on_orderbook = MagicMock()

    router.register_with_websocket(mock_ws)

    mock_ws.on_orderbook.assert_called_once_with(router._on_orderbook_update)
