"""WebSocket activity streaming for real-time strategy decision updates.

Broadcasts activity log entries to all connected WebSocket clients when new
activities are logged via POST /api/activities.
"""

import logging
import asyncio
from typing import Dict, Any
from datetime import datetime, timezone
from backend.core.task_manager import TaskManager

logger = logging.getLogger(__name__)

_task_manager: TaskManager | None = None


def set_task_manager(tm: TaskManager) -> None:
    global _task_manager
    _task_manager = tm


def get_task_manager() -> TaskManager | None:
    return _task_manager


async def broadcast_activity(activity_data: Dict[str, Any]):
    from backend.api.ws_manager_v2 import topic_manager

    message = {
        "type": "activity_update",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        **activity_data
    }

    tm = get_task_manager()
    if tm:
        await tm.create_task(topic_manager.broadcast("activities", message), name="broadcast_activity")
    else:
        asyncio.create_task(topic_manager.broadcast("activities", message))
    logger.debug(f"Queued activity broadcast: {activity_data.get('strategy_name')} - {activity_data.get('decision_type')}")
