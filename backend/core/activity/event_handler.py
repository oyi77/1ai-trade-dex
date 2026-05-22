"""Activity event handler — processes events into bankroll + positions."""

from __future__ import annotations
import asyncio
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from backend.core.activity.models import ActivityEvent
from loguru import logger

if TYPE_CHECKING:
    from backend.core.activity.tracker import ActivityTracker


class ActivityHandler:
    """Processes activity events → updates bankroll, positions, DB."""

    def __init__(self, tracker: 'ActivityTracker', db_session_factory):
        self._tracker = tracker
        self._db = db_session_factory
        self._tracker.on_event(self.handle_event)
        self._pending_events: list[ActivityEvent] = []

    async def handle_event(self, event: ActivityEvent):
        """Main entry — called by tracker on every event."""
        logger.info(
            f"[ActivityHandler] {event.source}.{event.event_type}: "
            f"{event.amount} {event.token} tx={event.tx_hash or 'n/a'}"
        )

        if event.event_type in ("deposit", "withdrawal"):
            await self._handle_transfer(event)
        elif event.event_type in ("trade_open", "buy", "sell"):
            await self._handle_trade_open(event)
        elif event.event_type == "trade_closed":
            await self._handle_trade_close(event)

    async def _handle_transfer(self, event: ActivityEvent):
        """Record deposit/withdrawal → update bankroll."""
        logger.info(
            f"[{event.source}] {event.event_type.upper()}: {event.amount} {event.token} "
            f"tx={event.tx_hash or 'internal'}"
        )
        # TODO: update bankroll in DB

    async def _handle_trade_open(self, event: ActivityEvent):
        """Record trade_open → create pending Trade in DB."""
        logger.info(
            f"[{event.source}] TRADE OPEN: {event.side} {event.amount} @ {event.price} "
            f"order={event.order_id} tx={event.tx_hash or 'n/a'}"
        )
        # TODO: create Trade(id=None, status=pending, external_order_id=event.order_id)

    async def _handle_trade_close(self, event: ActivityEvent):
        """Record trade_closed → finalize Trade in DB."""
        logger.info(
            f"[{event.source}] TRADE CLOSED: PnL={event.pnl} tx={event.tx_hash or 'n/a'}"
        )
        # TODO: update Trade status=closed, pnl=event.pnl

    def get_pending_events(self, limit: int = 50) -> list[ActivityEvent]:
        return self._tracker.get_recent_events(limit)