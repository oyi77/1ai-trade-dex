"""WebSocket routes for real-time updates."""

import asyncio
from datetime import datetime, timezone

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect

from backend.api.auth import authorize_realtime_access
from backend.api.connection_limits import connection_limiter
from backend.api.ws_manager_v2 import topic_manager

from loguru import logger
router = APIRouter(tags=["websockets"])

@router.websocket("/ws/markets")
async def ws_markets(websocket: WebSocket, token: str = Query(None)):
    """WebSocket endpoint for live market price updates."""
    if not authorize_realtime_access(
        token=token,
        admin_session=websocket.cookies.get("admin_session"),
    ):
        await websocket.close(code=1008, reason="Unauthorized")
        return

    allowed, error_msg = await connection_limiter.check_ws_limit(websocket)
    if not allowed:
        await websocket.close(code=1008, reason=error_msg)
        return

    await websocket.accept()

    try:
        data = await websocket.receive_json()
        if data.get("action") == "subscribe":
            topic = data.get("topic", "markets")
            await topic_manager.subscribe(websocket, topic)
            await websocket.send_json({"type": "subscribed", "topic": topic})

        while True:
            await asyncio.sleep(30)
            await websocket.send_json({"type": "heartbeat"})
    except WebSocketDisconnect:
        await topic_manager.disconnect(websocket)
    except Exception as e:
        logger.exception(
            f"[api.websockets.ws_markets] {type(e).__name__}: Market WebSocket error: {e}"
        )
        await topic_manager.disconnect(websocket)
    finally:
        await connection_limiter.release_ws_connection(websocket)


@router.websocket("/ws/whales")
async def ws_whales(websocket: WebSocket, token: str = Query(None)):
    """WebSocket endpoint for whale trade notifications."""
    if not authorize_realtime_access(
        token=token,
        admin_session=websocket.cookies.get("admin_session"),
    ):
        await websocket.close(code=1008, reason="Unauthorized")
        return

    allowed, error_msg = await connection_limiter.check_ws_limit(websocket)
    if not allowed:
        await websocket.close(code=1008, reason=error_msg)
        return

    await websocket.accept()

    try:
        data = await websocket.receive_json()
        if data.get("action") == "subscribe":
            topic = data.get("topic", "whales")
            await topic_manager.subscribe(websocket, topic)
            await websocket.send_json({"type": "subscribed", "topic": topic})

        while True:
            await asyncio.sleep(30)
            await websocket.send_json({"type": "heartbeat"})
    except WebSocketDisconnect:
        await topic_manager.disconnect(websocket)
    except Exception as e:
        logger.exception(
            f"[api.websockets.ws_whales] {type(e).__name__}: Whale WebSocket error: {e}"
        )
        await topic_manager.disconnect(websocket)
    finally:
        await connection_limiter.release_ws_connection(websocket)


@router.websocket("/ws/activities")
async def ws_activities(websocket: WebSocket, token: str = Query(None)):
    if not authorize_realtime_access(
        token=token,
        admin_session=websocket.cookies.get("admin_session"),
    ):
        await websocket.close(code=1008, reason="Unauthorized")
        return

    allowed, error_msg = await connection_limiter.check_ws_limit(websocket)
    if not allowed:
        await websocket.close(code=1008, reason=error_msg)
        return

    await websocket.accept()

    try:
        data = await websocket.receive_json()
        if data.get("action") == "subscribe":
            topic = data.get("topic", "activities")
            await topic_manager.subscribe(websocket, topic)
            await websocket.send_json({"type": "subscribed", "topic": topic})

        while True:
            await asyncio.sleep(30)
            await websocket.send_json({"type": "heartbeat"})
    except WebSocketDisconnect:
        await topic_manager.disconnect(websocket)
    except Exception as e:
        logger.exception(f"[api.websockets.ws_activities] {type(e).__name__}: Activity WebSocket error: {e}")
        await topic_manager.disconnect(websocket)
    finally:
        await connection_limiter.release_ws_connection(websocket)


@router.websocket("/ws/brain")
async def ws_brain(websocket: WebSocket, token: str = ""):
    if not authorize_realtime_access(
        token=token or None,
        admin_session=websocket.cookies.get("admin_session"),
    ):
        await websocket.close(code=1008, reason="Unauthorized")
        return

    allowed, error_msg = await connection_limiter.check_ws_limit(websocket)
    if not allowed:
        await websocket.close(code=1008, reason=error_msg)
        return

    await websocket.accept()

    try:
        data = await websocket.receive_json()
        if data.get("action") == "subscribe":
            topic = data.get("topic", "brain")
            await topic_manager.subscribe(websocket, topic)
            await websocket.send_json({"type": "subscribed", "topic": topic})

        while True:
            await asyncio.sleep(30)
            await websocket.send_json({"type": "heartbeat"})
    except WebSocketDisconnect:
        await topic_manager.disconnect(websocket)
    except Exception as e:
        logger.exception(f"[api.websockets.ws_brain] {type(e).__name__}: Brain WebSocket error: {e}")
        await topic_manager.disconnect(websocket)
    finally:
        await connection_limiter.release_ws_connection(websocket)


@router.websocket("/ws/events")
async def websocket_events(websocket: WebSocket, token: str = ""):
    if not authorize_realtime_access(
        token=token or None,
        admin_session=websocket.cookies.get("admin_session"),
    ):
        await websocket.close(code=1008, reason="Unauthorized")
        return

    allowed, error_msg = await connection_limiter.check_ws_limit(websocket)
    if not allowed:
        await websocket.close(code=1008, reason=error_msg)
        return

    await websocket.accept()

    try:
        data = await websocket.receive_json()
        if data.get("action") == "subscribe":
            topic = data.get("topic", "events")
            await topic_manager.subscribe(websocket, topic)

            await websocket.send_json(
                {
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "type": "subscribed",
                    "topic": topic,
                    "message": "Connected to BTC trading bot",
                }
            )

            from backend.core.scheduler import get_recent_events

            for event in get_recent_events(20):
                await websocket.send_json(event)

            last_event_count = len(get_recent_events(200))
            while True:
                await asyncio.sleep(2)

                current_events = get_recent_events(200)
                if len(current_events) > last_event_count:
                    new_events = current_events[last_event_count - len(current_events) :]
                    for event in new_events:
                        await websocket.send_json(event)
                    last_event_count = len(current_events)

                await websocket.send_json(
                    {
                        "type": "heartbeat",
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    }
                )

    except WebSocketDisconnect:
        await topic_manager.disconnect(websocket)
    except Exception as e:
        logger.exception(
            f"[api.websockets.websocket_events] {type(e).__name__}: Events WebSocket error: {e}"
        )
        await topic_manager.disconnect(websocket)
    finally:
        await connection_limiter.release_ws_connection(websocket)


@router.websocket("/ws/dashboard-data")
async def websocket_stats(websocket: WebSocket, token: str = ""):
    if not authorize_realtime_access(
        token=token or None,
        admin_session=websocket.cookies.get("admin_session"),
    ):
        await websocket.close(code=1008, reason="Unauthorized")
        return

    allowed, error_msg = await connection_limiter.check_ws_limit(websocket)
    if not allowed:
        await websocket.close(code=1008, reason=error_msg)
        return

    await websocket.accept()

    try:
        data = await websocket.receive_json()
        if data.get("action") == "subscribe":
            topic = data.get("topic", "stats")
            await topic_manager.subscribe(websocket, topic)
            await websocket.send_json({"type": "subscribed", "topic": topic})

        while True:
            await asyncio.sleep(60)
    except WebSocketDisconnect:
        logger.info("Stats WebSocket disconnected")
        await topic_manager.disconnect(websocket)
    except Exception as e:
        logger.exception(
            f"[api.websockets.websocket_stats] {type(e).__name__}: Stats WebSocket error: {e}"
        )
        await topic_manager.disconnect(websocket)
    finally:
        await connection_limiter.release_ws_connection(websocket)


@router.websocket("/ws/livestream")
async def websocket_livestream(websocket: WebSocket, token: str = ""):
    if not authorize_realtime_access(
        token=token or None,
        admin_session=websocket.cookies.get("admin_session"),
    ):
        await websocket.close(code=1008, reason="Unauthorized")
        return

    allowed, error_msg = await connection_limiter.check_ws_limit(websocket)
    if not allowed:
        await websocket.close(code=1008, reason=error_msg)
        return

    await websocket.accept()

    try:
        await topic_manager.subscribe(websocket, "livestream")
        await websocket.send_json({"type": "subscribed", "topic": "livestream"})

        from backend.api_websockets.livestream import broadcast_livestream_snapshot
        await broadcast_livestream_snapshot()

        while True:
            await asyncio.sleep(60)
    except WebSocketDisconnect:
        logger.info("Livestream WebSocket disconnected")
        await topic_manager.disconnect(websocket)
    except Exception as e:
        logger.exception(
            f"[api.websockets.websocket_livestream] {type(e).__name__}: Livestream WebSocket error: {e}"
        )
        await topic_manager.disconnect(websocket)
    finally:
        await connection_limiter.release_ws_connection(websocket)
