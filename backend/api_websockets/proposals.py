"""WebSocket streaming for real-time proposal updates.

Broadcasts proposal status changes to all connected WebSocket clients when
proposals are approved, rejected, or created.
"""

import asyncio
from typing import Dict, Any
from datetime import datetime, timezone
from backend.core.scheduling.task_manager import TaskManager

from loguru import logger

_task_manager: TaskManager | None = None


def set_task_manager(tm: TaskManager) -> None:
    global _task_manager
    _task_manager = tm


def get_task_manager() -> TaskManager | None:
    return _task_manager


async def broadcast_proposal_update(proposal_data: Dict[str, Any]):
    from backend.api.ws_manager_v2 import topic_manager

    message = {
        "type": "proposal_update",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        **proposal_data,
    }

    tm = get_task_manager()
    if tm:
        await tm.create_task(
            topic_manager.broadcast("proposals", message),
            name="broadcast_proposal_update",
        )
    else:
        asyncio.create_task(topic_manager.broadcast("proposals", message))
    logger.debug(
        f"Queued proposal broadcast: {proposal_data.get('strategy_name')} - {proposal_data.get('admin_decision')}"
    )
