"""Tests for SSE event router with channel filtering."""
import asyncio
from unittest.mock import AsyncMock, MagicMock
import pytest

from backend.api.events.sse_router import EVENT_CHANNEL_MAP
from backend.core.event_bus import event_bus


def test_event_channel_map_contains_all_required_events():
    """Test that EVENT_CHANNEL_MAP contains all required event types."""
    required_events = {
        "trade_executed",
        "settlement_completed",
        "strategy_health_killed",
        "autonomous_promotion",
        "arbitrage_fired",
        "regime_shift",
        "chromosome_flagged",
        "strategy_param_mutated",
        "genome_killed",
        "genome_promoted",
        "genome_ready_for_paper",  # New event from shadow_validation
    }

    assert required_events.issubset(EVENT_CHANNEL_MAP.keys()), \
        f"Missing required events: {required_events - EVENT_CHANNEL_MAP.keys()}"


def test_event_channel_map_channels():
    """Test that EVENT_CHANNEL_MAP has correct channel mappings."""
    # Test specific mappings
    assert set(EVENT_CHANNEL_MAP["trade_executed"]) == {"dashboard", "control_room"}
    assert set(EVENT_CHANNEL_MAP["settlement_completed"]) == {"dashboard", "overview"}
    assert set(EVENT_CHANNEL_MAP["strategy_health_killed"]) == {"dashboard", "admin"}
    assert set(EVENT_CHANNEL_MAP["autonomous_promotion"]) == {"dashboard", "agi_control"}
    assert set(EVENT_CHANNEL_MAP["arbitrage_fired"]) == {"dashboard", "control_room"}
    assert set(EVENT_CHANNEL_MAP["regime_shift"]) == {"dashboard", "agi_control"}
    assert set(EVENT_CHANNEL_MAP["chromosome_flagged"]) == {"agi_control"}
    assert set(EVENT_CHANNEL_MAP["strategy_param_mutated"]) == {"agi_control", "admin"}
    assert set(EVENT_CHANNEL_MAP["genome_killed"]) == {"agi_control"}
    assert set(EVENT_CHANNEL_MAP["genome_promoted"]) == {"agi_control"}
    assert set(EVENT_CHANNEL_MAP["genome_ready_for_paper"]) == {"dashboard", "agi_control"}


@pytest.mark.asyncio
async def test_sse_stream_with_channels_filter():
    """Test that subscribing with channels filter receives only matching events."""
    # Clear event history
    event_bus._history.clear()

    # Add test events to history
    test_events = [
        {"type": "trade_executed", "data": {"trade_id": 1}},
        {"type": "autonomous_promotion", "data": {"strategy_id": 1}},
        {"type": "chromosome_flagged", "data": {"chromosome_id": 1}},
        {"type": "unknown_event", "data": {"test": 1}},
    ]

    for event in test_events:
        event_bus._history.append(event)

    # Mock the request and queue
    mock_request = MagicMock()
    mock_request.is_disconnected = AsyncMock(return_value=False)

    # Create a queue and subscribe it
    queue = asyncio.Queue()
    event_bus.subscribe(queue)

    # Simulate the generate function with channel filtering
    from backend.api.events.sse_router import _should_send_event

    requested_channels = {"dashboard", "control_room"}

    # Check which events should be sent
    filtered_events = []
    for event in test_events:
        event_type = event.get("type", "")
        if _should_send_event(event_type, requested_channels):
            filtered_events.append(event)

    # Should receive trade_executed (dashboard,control_room) and autonomous_promotion (dashboard,agi_control)
    # Both match the requested channels (dashboard is in both)
    assert len(filtered_events) == 2
    received_types = {event["type"] for event in filtered_events}
    assert received_types == {"trade_executed", "autonomous_promotion"}

    # Cleanup
    event_bus.unsubscribe(queue)


@pytest.mark.asyncio
async def test_sse_stream_without_channels_filter():
    """Test that subscribing without channels filter receives all events."""
    # Clear event history
    event_bus._history.clear()

    # Add test events to history
    test_events = [
        {"type": "trade_executed", "data": {"trade_id": 1}},
        {"type": "autonomous_promotion", "data": {"strategy_id": 1}},
        {"type": "chromosome_flagged", "data": {"chromosome_id": 1}},
        {"type": "unknown_event", "data": {"test": 1}},
    ]

    for event in test_events:
        event_bus._history.append(event)

    from backend.api.events.sse_router import _should_send_event

    requested_channels = set()  # No channels specified

    # Check which events should be sent
    filtered_events = []
    for event in test_events:
        event_type = event.get("type", "")
        if _should_send_event(event_type, requested_channels):
            filtered_events.append(event)

    # Should receive all events when no channels specified
    assert len(filtered_events) == 4


@pytest.mark.asyncio
async def test_sse_stream_with_unknown_channel():
    """Test that subscribing with unknown channel receives no events."""
    # Clear event history
    event_bus._history.clear()

    # Add test events to history
    test_events = [
        {"type": "trade_executed", "data": {"trade_id": 1}},
        {"type": "autonomous_promotion", "data": {"strategy_id": 1}},
    ]

    for event in test_events:
        event_bus._history.append(event)

    from backend.api.events.sse_router import _should_send_event

    requested_channels = {"unknown_channel"}

    # Check which events should be sent
    filtered_events = []
    for event in test_events:
        event_type = event.get("type", "")
        if _should_send_event(event_type, requested_channels):
            filtered_events.append(event)

    # Should receive no events for unknown channel
    assert len(filtered_events) == 0


@pytest.mark.asyncio
async def test_sse_stream_feature_flag_disabled():
    """Test that when feature flag is disabled, all events pass through."""
    # This test is more about the concept - the actual implementation
    # doesn't use the feature flag for filtering since filtering is
    # based on the presence of channels parameter

    # Clear event history
    event_bus._history.clear()

    # Add test events to history
    test_events = [
        {"type": "trade_executed", "data": {"trade_id": 1}},
        {"type": "autonomous_promotion", "data": {"strategy_id": 1}},
    ]

    for event in test_events:
        event_bus._history.append(event)

    from backend.api.events.sse_router import _should_send_event

    # When no channels specified, all events pass through
    # (this simulates the feature flag being disabled)
    requested_channels = set()

    # Check which events should be sent
    filtered_events = []
    for event in test_events:
        event_type = event.get("type", "")
        if _should_send_event(event_type, requested_channels):
            filtered_events.append(event)

    # Should receive all events
    assert len(filtered_events) == 2


@pytest.mark.asyncio
async def test_sse_stream_multiple_channels():
    """Test that subscribing to multiple channels works correctly."""
    # Clear event history
    event_bus._history.clear()

    # Add test events to history
    test_events = [
        {"type": "trade_executed", "data": {"trade_id": 1}},  # dashboard, control_room
        {"type": "autonomous_promotion", "data": {"strategy_id": 1}},  # dashboard, agi_control
        {"type": "chromosome_flagged", "data": {"chromosome_id": 1}},  # agi_control only
        {"type": "settlement_completed", "data": {"settlement_id": 1}},  # dashboard, overview
    ]

    for event in test_events:
        event_bus._history.append(event)

    from backend.api.events.sse_router import _should_send_event

    # Subscribe to dashboard and agi_control
    requested_channels = {"dashboard", "agi_control"}

    # Check which events should be sent
    filtered_events = []
    for event in test_events:
        event_type = event.get("type", "")
        if _should_send_event(event_type, requested_channels):
            filtered_events.append(event)

    # Should receive trade_executed, autonomous_promotion, chromosome_flagged, settlement_completed
    # (all except those that don't match any of the requested channels)
    assert len(filtered_events) == 4  # All these events match dashboard or agi_control
    expected_types = {"trade_executed", "autonomous_promotion", "chromosome_flagged", "settlement_completed"}
    received_types = {event["type"] for event in filtered_events}
    assert received_types == expected_types
