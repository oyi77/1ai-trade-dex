"""QA tests for TopicWebSocketManager.

Scenario 1: Topic-based broadcast only reaches subscribers
Scenario 2: Disconnect removes client from all topics
"""

import asyncio
import pytest
from unittest.mock import AsyncMock
from backend.api.ws_manager_v2 import TopicWebSocketManager


@pytest.fixture
def manager():
    """Create a fresh TopicWebSocketManager for each test."""
    return TopicWebSocketManager()


@pytest.fixture
def mock_websockets():
    """Create mock WebSocket clients."""
    ws1 = AsyncMock()
    ws2 = AsyncMock()
    ws3 = AsyncMock()
    return ws1, ws2, ws3


@pytest.mark.asyncio
async def test_topic_broadcast_only_reaches_subscribers(manager, mock_websockets):
    """Scenario 1: Topic-based broadcast only reaches subscribers.

    Setup:
    - Create manager with 3 mock WebSocket clients
    - Subscribe client1 to "markets", client2 to "whales", client3 to both

    Action:
    - Broadcast message to "markets" topic

    Expected:
    - Only client1 and client3 received the message
    - client2 did not receive it
    """
    ws1, ws2, ws3 = mock_websockets

    # Subscribe clients to topics
    await manager.subscribe(ws1, "markets")
    await manager.subscribe(ws2, "whales")
    await manager.subscribe(ws3, "markets")
    await manager.subscribe(ws3, "whales")

    # Broadcast to "markets" topic
    test_message = {"type": "market_update", "data": "test"}
    await manager.broadcast("markets", test_message)

    # Give async tasks time to complete
    await asyncio.sleep(0.1)

    # Verify only markets subscribers received the message
    ws1.send_json.assert_called_once_with(test_message)
    ws2.send_json.assert_not_called()
    ws3.send_json.assert_called_once_with(test_message)

    print("✓ Scenario 1 PASSED: Only topic subscribers received broadcast")
    return True


@pytest.mark.asyncio
async def test_disconnect_removes_from_all_topics(manager, mock_websockets):
    """Scenario 2: Disconnect removes client from all topics.

    Setup:
    - Subscribe client to 3 topics

    Action:
    - Call disconnect(client)

    Expected:
    - Client removed from all topic subscription sets
    - Subsequent broadcasts to those topics don't reach the client
    """
    ws1, ws2, ws3 = mock_websockets

    # Subscribe ws1 to 3 topics
    await manager.subscribe(ws1, "markets")
    await manager.subscribe(ws1, "whales")
    await manager.subscribe(ws1, "stats")

    # Verify subscriptions exist
    assert manager.get_topic_subscriber_count("markets") == 1
    assert manager.get_topic_subscriber_count("whales") == 1
    assert manager.get_topic_subscriber_count("stats") == 1

    # Disconnect the client
    await manager.disconnect(ws1)

    # Verify client removed from all topics
    assert manager.get_topic_subscriber_count("markets") == 0
    assert manager.get_topic_subscriber_count("whales") == 0
    assert manager.get_topic_subscriber_count("stats") == 0

    # Verify empty topics are cleaned up
    all_topics = manager.get_all_topics()
    assert len(all_topics) == 0

    # Broadcast to each topic and verify ws1 doesn't receive
    ws1.send_json.reset_mock()
    await manager.broadcast("markets", {"type": "test"})
    await manager.broadcast("whales", {"type": "test"})
    await manager.broadcast("stats", {"type": "test"})
    await asyncio.sleep(0.1)

    ws1.send_json.assert_not_called()

    print("✓ Scenario 2 PASSED: Client cleanly removed from all topics")
    return True


@pytest.mark.asyncio
async def test_multiple_subscribers_per_topic(manager, mock_websockets):
    """Verify multiple clients can subscribe to same topic."""
    ws1, ws2, ws3 = mock_websockets

    # All subscribe to same topic
    await manager.subscribe(ws1, "markets")
    await manager.subscribe(ws2, "markets")
    await manager.subscribe(ws3, "markets")

    assert manager.get_topic_subscriber_count("markets") == 3

    # Broadcast reaches all
    test_message = {"type": "test"}
    await manager.broadcast("markets", test_message)
    await asyncio.sleep(0.1)

    ws1.send_json.assert_called_once_with(test_message)
    ws2.send_json.assert_called_once_with(test_message)
    ws3.send_json.assert_called_once_with(test_message)

    print("✓ Multiple subscribers test PASSED")
    return True


@pytest.mark.asyncio
async def test_unsubscribe_removes_from_topic(manager, mock_websockets):
    """Verify unsubscribe removes client from specific topic only."""
    ws1, ws2, ws3 = mock_websockets

    # Subscribe to multiple topics
    await manager.subscribe(ws1, "markets")
    await manager.subscribe(ws1, "whales")

    # Unsubscribe from one topic
    await manager.unsubscribe(ws1, "markets")

    # Verify still subscribed to whales
    assert manager.get_topic_subscriber_count("markets") == 0
    assert manager.get_topic_subscriber_count("whales") == 1

    # Broadcast to markets - ws1 shouldn't receive
    ws1.send_json.reset_mock()
    await manager.broadcast("markets", {"type": "test"})
    await asyncio.sleep(0.1)
    ws1.send_json.assert_not_called()

    # Broadcast to whales - ws1 should receive
    await manager.broadcast("whales", {"type": "test"})
    await asyncio.sleep(0.1)
    ws1.send_json.assert_called_once()

    print("✓ Unsubscribe test PASSED")
    return True


@pytest.mark.asyncio
async def test_stale_connection_cleanup(manager, mock_websockets):
    """Verify stale connections are removed on send failure."""
    ws1, ws2, ws3 = mock_websockets

    # Subscribe all to same topic
    await manager.subscribe(ws1, "markets")
    await manager.subscribe(ws2, "markets")
    await manager.subscribe(ws3, "markets")

    # Make ws1 fail on send
    ws1.send_json.side_effect = Exception("Connection closed")

    # Broadcast - ws1 should be removed on failure
    await manager.broadcast("markets", {"type": "test"})
    await asyncio.sleep(0.1)

    # Verify ws1 removed from subscriptions
    assert manager.get_topic_subscriber_count("markets") == 2

    # Verify ws2 and ws3 still subscribed
    ws2.send_json.assert_called_once()
    ws3.send_json.assert_called_once()

    print("✓ Stale connection cleanup test PASSED")
    return True
