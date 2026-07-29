# event_log.py — extracted from scheduler.py
"""Scheduler sub-module: event_log."""

from datetime import datetime, timedelta, timezone
from loguru import logger
from typing import List, Optional
import threading

event_log: List[dict] = []

MAX_LOG_SIZE = 200

_event_log_lock = threading.Lock()

def log_event(event_type: str, message: str, data: dict = None):
    """Log an event for terminal display."""
    event = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "type": event_type,
        "message": message,
        "data": data or {},
    }
    with _event_log_lock:
        event_log.append(event)

        while len(event_log) > MAX_LOG_SIZE:
            event_log.pop(0)

    log_func = {
        "error": logger.error,
        "warning": logger.warning,
        "success": logger.info,
        "info": logger.info,
        "data": logger.debug,
        "trade": logger.info,
    }.get(event_type, logger.info)

    log_func(f"[{event_type.upper()}] {message}")

def get_recent_events(limit: int = 50) -> List[dict]:
    """Get recent events for terminal display."""
    with _event_log_lock:
        return list(event_log[-limit:])