"""
Event bus for SSE broadcasting and internal event-driven dispatch.

This module provides a centralized event system for broadcasting
events to all connected SSE subscribers AND dispatching typed events
to backend handler callbacks. It replaces the module-level globals
_event_subscribers and _event_history that were in main.py.
"""
import asyncio
import logging
from collections import defaultdict, deque
from datetime import datetime, timezone
from typing import Dict, Any, List, Callable, Awaitable


logger = logging.getLogger(__name__)

# Type alias for event handler callbacks
EventHandler = Callable[[str, Dict[str, Any]], Awaitable[None]]


class EventBus:
    """
    Centralized event system for SSE broadcasting and internal dispatch.

    Manages two channels:
    1. SSE subscriber queues (frontend dashboard)
    2. Typed handler callbacks (backend modules)

    This is a module-level instance (not a singleton pattern) for simplicity.
    """

    def __init__(self, history_maxlen: int = 50):
        """
        Initialize the event bus.

        Args:
            history_maxlen: Maximum number of events to keep in history
        """
        self._subscribers: List[asyncio.Queue] = []
        self._history: deque = deque(maxlen=history_maxlen)
        self._handlers: Dict[str, List[EventHandler]] = defaultdict(list)

    def subscribe(self, queue: asyncio.Queue) -> None:
        """
        Subscribe a queue to receive events.

        Args:
            queue: AsyncQueue to push events to
        """
        self._subscribers.append(queue)
        logger.debug(f"New subscriber added. Total subscribers: {len(self._subscribers)}")

    def unsubscribe(self, queue: asyncio.Queue) -> bool:
        """
        Unsubscribe a queue from receiving events.

        Args:
            queue: AsyncQueue to remove

        Returns:
            True if removed, False if not found
        """
        try:
            self._subscribers.remove(queue)
            logger.debug(f"Subscriber removed. Total subscribers: {len(self._subscribers)}")
            return True
        except ValueError:
            logger.warning("Attempted to remove non-existent subscriber")
            return False

    def subscribe_handler(self, event_type: str, handler: EventHandler) -> None:
        self._handlers[event_type].append(handler)
        logger.debug(
            "Handler registered for '%s' (%d total)", event_type, len(self._handlers[event_type])
        )

    def unsubscribe_handler(self, event_type: str, handler: EventHandler) -> None:
        try:
            self._handlers[event_type].remove(handler)
        except ValueError:
            pass

    def publish(self, event_type: str, data: Dict[str, Any]) -> None:
        payload = {
            "type": event_type,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "data": data,
        }
        self._history.append(payload)

        for queue in self._subscribers[:]:
            try:
                queue.put_nowait(payload)
            except asyncio.QueueFull:
                logger.warning(f"Dropping event for slow subscriber: {event_type}")

        handlers = self._handlers.get(event_type, [])
        for handler in handlers:
            try:
                asyncio.ensure_future(handler(event_type, data))
            except Exception as exc:
                logger.warning("Event handler failed for '%s': %s", event_type, exc)

    def get_history(self) -> List[Dict[str, Any]]:
        """
        Get the event history.

        Returns:
            List of historical events (most recent first)
        """
        return list(self._history)

    def subscriber_count(self) -> int:
        """Get the number of active subscribers."""
        return len(self._subscribers)


# Module-level instance (simple, not singleton pattern)
# This is imported throughout the codebase for event broadcasting
event_bus = EventBus()


# For backward compatibility with old code that imports these functions
def publish_event(event_type: str, data: Dict[str, Any]) -> None:
    """Publish an event to all subscribers (convenience function)."""
    event_bus.publish(event_type, data)


def subscribe_handler(event_type: str, handler: EventHandler) -> None:
    """Register an async handler for a specific event type."""
    event_bus.subscribe_handler(event_type, handler)


def get_event_history() -> List[Dict[str, Any]]:
    """Get the event history (convenience function)."""
    return event_bus.get_history()


# Backward compatibility: _broadcast_event was the old name
# This function is imported by signals.py, settlement.py, scheduler.py, weather_signals.py
def _broadcast_event(event_type: str, data: Dict[str, Any]) -> None:
    """Legacy broadcast function name - delegates to publish_event."""
    publish_event(event_type, data)
