"""Activity tracker — dispatches events from all sources to handlers."""

from __future__ import annotations
import asyncio
import random
from typing import Callable

from backend.core.activity.models import ActivityEvent
from loguru import logger


class ActivityTracker:
    """Central dispatcher for all platform activity events."""

    def __init__(self):
        self._sources: dict[str, "BaseActivitySource"] = {}
        self._handlers: list[Callable] = []
        self._events: list[ActivityEvent] = []
        self._max_events = 1000

    def register_source(self, name: str, source: "BaseActivitySource"):
        """Register a platform activity source."""
        self._sources[name] = source
        source.on_activity(self._on_event)
        logger.info(f"[ActivityTracker] Registered source: {name}")

    def on_event(self, handler: Callable):
        """Register an event handler."""
        self._handlers.append(handler)

    async def start_all(self):
        """Start all registered sources with staggered jitter to avoid burst."""
        for i, (name, source) in enumerate(self._sources.items()):
            try:
                await source.start()
                # Stagger: 0.5-3s jitter between each source start
                if i < len(self._sources) - 1:
                    jitter = random.uniform(0.5, 3.0)
                    await asyncio.sleep(jitter)
            except Exception as e:
                logger.error(f"[ActivityTracker] Failed to start {name}: {e}")

    async def stop_all(self):
        """Stop all sources."""
        for name, source in self._sources.items():
            try:
                await source.stop()
            except Exception as e:
                logger.error(f"[ActivityTracker] Failed to stop {name}: {e}")

    async def _on_event(self, event: ActivityEvent):
        """Internal — called by any source."""
        self._events.append(event)
        if len(self._events) > self._max_events:
            self._events = self._events[-self._max_events :]

        for handler in self._handlers:
            try:
                if asyncio.iscoroutinefunction(handler):
                    await handler(event)
                else:
                    handler(event)
            except Exception as e:
                logger.error(f"[ActivityTracker] Handler error: {e}")

        logger.debug(
            f"[ActivityTracker] {event.source}.{event.event_type}: {event.amount} {event.token}"
        )

    def get_recent_events(self, limit: int = 100) -> list[ActivityEvent]:
        """Get recent events for API."""
        return self._events[-limit:]

    def get_events_by_type(
        self, event_type: str, limit: int = 50
    ) -> list[ActivityEvent]:
        return [e for e in self._events if e.event_type == event_type][-limit:]

    def get_events_by_source(self, source: str, limit: int = 50) -> list[ActivityEvent]:
        return [e for e in self._events if e.source == source][-limit:]
