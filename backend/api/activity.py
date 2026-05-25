"""Activity API endpoints — real-time wallet activity."""

from fastapi import APIRouter, Depends, Query
from typing import Optional

from backend.core.activity.tracker import ActivityTracker
from backend.core.activity.models import ActivityEvent

router = APIRouter(prefix="/api/v1/activity", tags=["activity"])


def get_tracker() -> ActivityTracker:
    from backend.core.activity import tracker as _tracker
    return _tracker


@router.get("/events")
async def get_events(
    source: Optional[str] = Query(None, description="Filter by source (aster, hyperliquid, lighter, polymarket)"),
    event_type: Optional[str] = Query(None, description="Filter by type (deposit, withdrawal, trade_open, trade_closed)"),
    limit: int = Query(100, ge=1, le=500),
    tracker: ActivityTracker = Depends(get_tracker),
):
    """Get recent activity events from all sources."""
    if source:
        events = tracker.get_events_by_source(source, limit)
    elif event_type:
        events = tracker.get_events_by_type(event_type, limit)
    else:
        events = tracker.get_recent_events(limit)

    return {
        "count": len(events),
        "events": [e.to_dict() for e in events],
    }


@router.get("/summary")
async def get_summary(
    tracker: ActivityTracker = Depends(get_tracker),
):
    """Get aggregated activity summary."""
    events = tracker.get_recent_events(limit=1000)

    deposits = [e for e in events if e.event_type == "deposit"]
    withdrawals = [e for e in events if e.event_type == "withdrawal"]
    trades = [e for e in events if e.event_type in ("trade_open", "trade_closed")]

    return {
        "total_events": len(events),
        "total_deposits": sum(e.amount for e in deposits),
        "total_withdrawals": sum(e.amount for e in withdrawals),
        "total_trades": len(trades),
        "sources": list(set(e.source for e in events)),
        "last_event": events[-1].to_dict() if events else None,
    }