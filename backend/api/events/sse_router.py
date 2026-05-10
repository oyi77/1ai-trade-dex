"""SSE Event Router with channel-based filtering.

This module implements channel-aware event routing for the SSE endpoint,
allowing clients to subscribe to specific event channels.
"""
import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Set

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

from backend.api.auth import authorize_realtime_access
from backend.config import settings
from backend.core.event_bus import event_bus

logger = logging.getLogger("trading_bot")

# Event type to channels mapping
EVENT_CHANNEL_MAP = {
    "trade_executed": ["dashboard", "control_room"],
    "settlement_completed": ["dashboard", "overview"],
    "strategy_health_killed": ["dashboard", "admin"],
    "autonomous_promotion": ["dashboard", "agi_control"],
    "arbitrage_fired": ["dashboard", "control_room"],
    "regime_shift": ["dashboard", "agi_control"],
    "chromosome_flagged": ["agi_control"],
    "strategy_param_mutated": ["agi_control", "admin"],
    "genome_killed": ["agi_control"],
    "genome_promoted": ["agi_control"],
    # New event from shadow_validation
    "genome_ready_for_paper": ["dashboard", "agi_control"],
}

router = APIRouter(tags=["events"])


def _get_channels_for_event(event_type: str) -> Set[str]:
    """Get the set of channels for a given event type."""
    return set(EVENT_CHANNEL_MAP.get(event_type, []))


def _should_send_event(event_type: str, requested_channels: Set[str]) -> bool:
    """Determine if an event should be sent based on channel filtering."""
    if not requested_channels:
        # No channels specified = send all events (backward compatibility)
        return True

    event_channels = _get_channels_for_event(event_type)
    return bool(event_channels & requested_channels)


@router.get("/api/events/stream")
@router.get("/api/v1/events/stream")
async def events_stream(
    request: Request,
    token: str = "",
    channels: str = Query(
        "",
        description="Comma-separated list of channels to subscribe to (e.g., 'dashboard,agi_control')"
    )
):
    """Server-Sent Events stream for real-time trade notifications with channel filtering.

    Clients can subscribe to specific channels to receive only relevant events.
    If no channels parameter is provided, all events are sent (backward compatible).
    """
    if not authorize_realtime_access(token=token or None, admin_session=request.cookies.get("admin_session")):
        raise HTTPException(status_code=401, detail="Unauthorized")

    # Parse requested channels
    requested_channels = set(c.strip() for c in channels.split(",") if c.strip()) if channels else set()

    queue: asyncio.Queue = asyncio.Queue(maxsize=100)
    event_bus.subscribe(queue)

    async def generate():
        # Send filtered history on connect
        for event in event_bus.get_history():
            event_type = event.get("type", "")
            if _should_send_event(event_type, requested_channels):
                yield f"data: {json.dumps(event)}\n\n"

        # Send connected heartbeat immediately
        yield f"data: {json.dumps({'type': 'connected', 'timestamp': datetime.now(timezone.utc).isoformat()})}\n\n"

        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=30.0)
                    event_type = event.get("type", "")

                    # Apply channel filtering
                    if _should_send_event(event_type, requested_channels):
                        yield f"data: {json.dumps(event)}\n\n"

                except asyncio.TimeoutError:
                    # heartbeat keepalive
                    yield ": keepalive\n\n"
        finally:
            event_bus.unsubscribe(queue)

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
            "Access-Control-Allow-Origin": ", ".join(settings.CORS_ORIGINS.split(",")) if settings.CORS_ORIGINS else "*",
            "Access-Control-Allow-Headers": "*",
            "Access-Control-Allow-Methods": "GET, OPTIONS",
        },
    )


@router.get("/status")
async def event_bus_status():
    from backend.core.event_bus import event_bus
    return {"status": "ok", **event_bus.get_health()}


@router.get("/strategies")
async def subscribed_strategies():
    from backend.core.event_bus import event_bus
    return {
        "ws_connected": event_bus.ws_connected,
        "total_tokens": len(event_bus.get_all_subscribed_tokens()),
        "strategies": event_bus.get_subscription_status(),
    }
