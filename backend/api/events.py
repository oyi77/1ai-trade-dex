"""Event bus and WebSocket health endpoints."""

from fastapi import APIRouter, Depends

from backend.api.auth import require_admin

router = APIRouter(prefix="/events", tags=["events"])


@router.get("/status")
async def event_bus_status(admin: bool = Depends(require_admin)):
    """Get event bus and WebSocket health status."""
    from backend.core.event_bus import event_bus
    health = event_bus.get_health()
    return {
        "status": "ok",
        **health,
    }


@router.get("/strategies")
async def subscribed_strategies(admin: bool = Depends(require_admin)):
    """List all strategies subscribed to WS events."""
    from backend.core.event_bus import event_bus
    return {
        "ws_connected": event_bus.ws_connected,
        "total_tokens": len(event_bus.get_all_subscribed_tokens()),
        "strategies": event_bus.get_subscription_status(),
    }
