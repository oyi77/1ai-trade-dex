"""Activity tracker — dispatches events from all sources to handlers."""

from __future__ import annotations
import asyncio
from typing import Callable, TYPE_CHECKING

if TYPE_CHECKING:
    from backend.core.activity.sources.base import BaseActivitySource

from backend.core.activity.models import ActivityEvent
from loguru import logger


class ActivityTracker:
    """Central dispatcher for all platform activity events."""

    def __init__(self):
        self._sources: dict[str, 'BaseActivitySource'] = {}
        self._handlers: list[Callable] = []
        self._events: list[ActivityEvent] = []
        self._max_events = 1000

    def register_source(self, name: str, source: 'BaseActivitySource'):
        """Register a platform activity source."""
        self._sources[name] = source
        source.on_activity(self._on_event)
        logger.info(f"[ActivityTracker] Registered source: {name}")

    def register_handler(self, handler: Callable[[ActivityEvent], None]):
        """Register a callback for new events."""
        if handler not in self._handlers:
            self._handlers.append(handler)
            logger.debug("[ActivityTracker] Registered new event handler")

    def unregister_handler(self, handler: Callable[[ActivityEvent], None]):
        """Remove a callback."""
        if handler in self._handlers:
            self._handlers.remove(handler)

    def _on_event(self, event: ActivityEvent):
        """Internal callback when a source generates an event."""
        # 1. Add to local history
        self._events.append(event)
        if len(self._events) > self._max_events:
            self._events.pop(0)

        # 2. Dispatch to all listeners
        for h in self._handlers:
            try:
                h(event)
            except Exception as e:
                logger.error(f"[ActivityTracker] Handler error on {event.event_type}: {e}")

    async def start_all(self):
        """Start polling on all registered sources."""
        if not self._sources:
            return
        logger.info(f"[ActivityTracker] Starting {len(self._sources)} sources")
        await asyncio.gather(*(s.start() for s in self._sources.values()))

    async def stop_all(self):
        """Stop polling on all sources."""
        logger.info("[ActivityTracker] Stopping sources")
        await asyncio.gather(*(s.stop() for s in self._sources.values()))

    def get_recent_events(self, limit: int = 50) -> list[ActivityEvent]:
        return self._events[-limit:]

    def get_events_by_source(self, source: str, limit: int = 50) -> list[ActivityEvent]:
        return [e for e in self._events if e.source == source][-limit:]
