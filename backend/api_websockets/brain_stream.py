"""WebSocket streaming for Brain Graph real-time updates.

Broadcasts events when:
- New signal arrives (strategy execution)
- Debate starts/ends (Bull/Bear/Judge)
- Trade executed
- Proposal generated
"""

import logging
import asyncio
from typing import Dict, Any
from datetime import datetime, timezone
from backend.core.task_manager import TaskManager

logger = logging.getLogger(__name__)

# Global task manager instance (set by main.py on startup)
_task_manager: TaskManager | None = None


def set_task_manager(tm: TaskManager) -> None:
    """Set the global task manager instance."""
    global _task_manager
    _task_manager = tm


def get_task_manager() -> TaskManager | None:
    """Get the global task manager instance."""
    return _task_manager


async def broadcast_signal_received(signal_data: Dict[str, Any]):
    from backend.api.ws_manager_v2 import topic_manager

    message = {
        "type": "signal_received",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "node": signal_data.get("source", "unknown"),
        "data": signal_data
    }
    tm = get_task_manager()
    if tm:
        await tm.create_task(topic_manager.broadcast("brain", message), name="broadcast_signal_received")
    else:
        asyncio.create_task(topic_manager.broadcast("brain", message))
    logger.debug(f"Queued signal_received broadcast: {signal_data.get('source')}")


async def broadcast_debate_started(market_id: str, nodes: list):
    from backend.api.ws_manager_v2 import topic_manager

    message = {
        "type": "debate_started",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "nodes": nodes,
        "market_id": market_id
    }
    tm = get_task_manager()
    if tm:
        await tm.create_task(topic_manager.broadcast("brain", message), name="broadcast_debate_started")
    else:
        asyncio.create_task(topic_manager.broadcast("brain", message))
    logger.debug(f"Queued debate_started broadcast: {market_id}")


async def broadcast_debate_ended(market_id: str, consensus: float, confidence: float):
    from backend.api.ws_manager_v2 import topic_manager

    message = {
        "type": "debate_ended",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "market_id": market_id,
        "consensus": consensus,
        "confidence": confidence
    }
    tm = get_task_manager()
    if tm:
        await tm.create_task(topic_manager.broadcast("brain", message), name="broadcast_debate_ended")
    else:
        asyncio.create_task(topic_manager.broadcast("brain", message))
    logger.debug(f"Queued debate_ended broadcast: {market_id}")


async def broadcast_trade_executed(trade_data: Dict[str, Any]):
    from backend.api.ws_manager_v2 import topic_manager

    message = {
        "type": "trade_executed",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "node": "trade_executor",
        "data": trade_data
    }
    tm = get_task_manager()
    if tm:
        await tm.create_task(topic_manager.broadcast("brain", message), name="broadcast_trade_executed")
    else:
        asyncio.create_task(topic_manager.broadcast("brain", message))
    logger.debug(f"Queued trade_executed broadcast: trade_id={trade_data.get('id')}")


async def broadcast_proposal_generated(proposal_data: Dict[str, Any]):
    from backend.api.ws_manager_v2 import topic_manager

    message = {
        "type": "proposal_generated",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "node": "proposal_generator",
        "data": proposal_data
    }
    tm = get_task_manager()
    if tm:
        await tm.create_task(topic_manager.broadcast("brain", message), name="broadcast_proposal_generated")
    else:
        asyncio.create_task(topic_manager.broadcast("brain", message))
    logger.debug(f"Queued proposal_generated broadcast: {proposal_data.get('strategy_name')}")


async def broadcast_node_status_change(node_id: str, status: str):
    from backend.api.ws_manager_v2 import topic_manager

    message = {
        "type": "node_status_change",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "node_id": node_id,
        "status": status
    }
    tm = get_task_manager()
    if tm:
        await tm.create_task(topic_manager.broadcast("brain", message), name="broadcast_node_status_change")
    else:
        asyncio.create_task(topic_manager.broadcast("brain", message))
    logger.debug(f"Queued node_status_change broadcast: {node_id} -> {status}")


async def broadcast_edge_activation(from_node: str, to_node: str, active: bool):
    from backend.api.ws_manager_v2 import topic_manager

    message = {
        "type": "edge_activation",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "from_node": from_node,
        "to_node": to_node,
        "active": active
    }
    tm = get_task_manager()
    if tm:
        await tm.create_task(topic_manager.broadcast("brain", message), name="broadcast_edge_activation")
    else:
        asyncio.create_task(topic_manager.broadcast("brain", message))
    logger.debug(f"Queued edge_activation broadcast: {from_node} -> {to_node} (active={active})")
