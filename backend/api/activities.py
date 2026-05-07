"""Activity log API endpoints."""

import logging
from typing import Optional
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Query, Depends, WebSocket, WebSocketDisconnect
from sqlalchemy.orm import Session
from pydantic import BaseModel

from backend.models.database import SessionLocal, ActivityLog
from backend.api.auth import require_admin
from backend.core.activity_logger import activity_logger
from backend.api_websockets.activity_stream import broadcast_activity

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/activities", tags=["activities"])


class CreateActivityRequest(BaseModel):
    strategy_name: str
    decision_type: str
    data: dict
    confidence_score: float
    mode: str = "paper"


def get_db():
    from backend.db.utils import get_db_session
    with get_db_session() as db:
        yield db


@router.get("")
async def get_activities(
    limit: int = Query(100, ge=1, le=1000),
    strategy: Optional[str] = Query(None),
    decision_type: Optional[str] = Query(None),
    days: Optional[int] = Query(None, ge=1),
    confidence_min: Optional[float] = Query(None, ge=0.0, le=1.0),
    db: Session = Depends(get_db)
):
    """
    Get activity logs with optional filtering.
    
    Query parameters:
    - limit: Maximum records to return (1-1000, default 100)
    - strategy: Filter by strategy name (e.g., 'btc_momentum')
    - decision_type: Filter by decision type ('entry', 'exit', 'hold', 'adjustment')
    - days: Filter to last N days
    - confidence_min: Minimum confidence score (0.0-1.0)
    """
    try:
        query = db.query(ActivityLog)
        
        if strategy:
            query = query.filter(ActivityLog.strategy_name == strategy)
        
        if decision_type:
            query = query.filter(ActivityLog.decision_type == decision_type)
        
        if days:
            from datetime import timedelta
            cutoff = datetime.now(timezone.utc) - timedelta(days=days)
            query = query.filter(ActivityLog.timestamp >= cutoff)
        
        if confidence_min is not None:
            query = query.filter(ActivityLog.confidence_score >= confidence_min)
        
        query = query.order_by(ActivityLog.timestamp.desc()).limit(limit)
        
        activities = query.all()
        
        result = []
        for activity in activities:
            result.append({
                "id": activity.id,
                "timestamp": activity.timestamp.isoformat(),
                "strategy_name": activity.strategy_name,
                "decision_type": activity.decision_type,
                "data": activity.data,
                "confidence_score": activity.confidence_score,
                "mode": activity.mode,
                "trading_mode": activity.mode
            })
        
        return {
            "activities": result,
            "count": len(result),
            "limit": limit
        }
    except Exception as e:
        logger.error(f"Failed to retrieve activities: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{activity_id}")
async def get_activity_by_id(
    activity_id: int,
    db: Session = Depends(get_db)
):
    """Get a single activity log by ID."""
    try:
        activity = db.query(ActivityLog).filter(ActivityLog.id == activity_id).first()
        
        if not activity:
            raise HTTPException(status_code=404, detail=f"Activity {activity_id} not found")
        
        return {
            "id": activity.id,
            "timestamp": activity.timestamp.isoformat(),
            "strategy_name": activity.strategy_name,
            "decision_type": activity.decision_type,
            "data": activity.data,
            "confidence_score": activity.confidence_score,
            "mode": activity.mode,
            "trading_mode": activity.mode
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to retrieve activity {activity_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("")
async def create_activity(
    request: CreateActivityRequest,
    db: Session = Depends(get_db),
    _admin: None = Depends(require_admin),
):
    """Create a new activity log entry and broadcast to WebSocket clients."""
    try:
        activity_id = activity_logger.log_entry(
            strategy_name=request.strategy_name,
            decision_type=request.decision_type,
            data=request.data,
            confidence=request.confidence_score,
            mode=request.mode,
            db=db
        )
        
        if not activity_id:
            raise HTTPException(status_code=500, detail="Failed to create activity log")
        
        activity = db.query(ActivityLog).filter(ActivityLog.id == activity_id).first()
        
        response_data = {
            "id": activity.id,
            "timestamp": activity.timestamp.isoformat(),
            "strategy_name": activity.strategy_name,
            "decision_type": activity.decision_type,
            "data": activity.data,
            "confidence_score": activity.confidence_score,
            "mode": activity.mode,
            "trading_mode": activity.mode
        }
        
        await broadcast_activity(response_data)
        
        return response_data
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to create activity: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.websocket("/ws")
async def websocket_activities_endpoint(websocket: WebSocket):
    """
    WebSocket endpoint for real-time activity updates.
    
    Connects to /ws/activities (relative to /api/activities prefix = /api/activities/ws)
    Receives activity updates in real-time as they are logged via POST /api/activities.
    """
    from backend.api.ws_manager_v2 import topic_manager
    
    await websocket.accept()
    
    try:
        data = await websocket.receive_json()
        if data.get("action") == "subscribe":
            topic = data.get("topic", "activities")
            await topic_manager.subscribe(websocket, topic)
            await websocket.send_json({"type": "subscribed", "topic": topic})
        
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        await topic_manager.disconnect(websocket)
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
        await topic_manager.disconnect(websocket)
