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

    async def handle_event(self, event: ActivityEvent):
        """Main entry — called by tracker on every event."""
        logger.info(
            f"[ActivityHandler] {event.source}.{event.event_type}: "
            f"{event.amount} {event.token} tx={event.tx_hash or 'n/a'}"
        )

        # Persist event to DB
        await self._persist_event(event)

        if event.event_type in ("deposit", "withdrawal"):
            await self._handle_transfer(event)
        elif event.event_type in ("trade_open", "buy", "sell"):
            await self._handle_trade_open(event)
        elif event.event_type == "trade_closed":
            await self._handle_trade_close(event)

    async def _persist_event(self, event: ActivityEvent):
        """Save event to activity_events table for historical queries."""
        try:
            from backend.db.utils import get_db_session
            from backend.models.database import ActivityEventRecord

            with get_db_session() as db:
                record = ActivityEventRecord(
                    id=event.id,
                    source=event.source,
                    event_type=event.event_type,
                    wallet_address=event.wallet_address,
                    platform=event.platform,
                    amount=event.amount,
                    token=event.token,
                    tx_hash=event.tx_hash,
                    timestamp=event.timestamp,
                    trade_id=event.trade_id,
                    order_id=event.order_id,
                    side=event.side,
                    price=event.price,
                    fee=event.fee,
                    pnl=event.pnl,
                    market_ticker=event.market_ticker,
                    raw_data=event.raw_data,
                )
                db.add(record)
                db.commit()
        except Exception as e:
            logger.opt(exception=True).warning(f"[ActivityHandler] Failed to persist event {event.id}: {e}")

    async def _handle_transfer(self, event: ActivityEvent):
        """Record deposit/withdrawal → update bankroll + live_initial_bankroll."""
        logger.info(
            f"[{event.source}] {event.event_type.upper()}: {event.amount} {event.token} "
            f"tx={event.tx_hash or 'internal'}"
        )
        try:
            from backend.db.utils import get_db_session
            from backend.models.database import BotState, TransactionEvent

            with get_db_session() as db:
                state = db.query(BotState).filter_by(mode="live").first()
                if not state:
                    logger.warning("[ActivityHandler] No live BotState found")
                    return

                old_bankroll = state.bankroll or 0.0

                if event.event_type == "deposit":
                    state.live_initial_bankroll = (state.live_initial_bankroll or 0.0) + event.amount
                    state.bankroll = old_bankroll + event.amount
                elif event.event_type == "withdrawal":
                    state.live_initial_bankroll = max(0.0, (state.live_initial_bankroll or 0.0) - event.amount)
                    state.bankroll = max(0.0, old_bankroll - event.amount)

                state.total_deposits = (state.total_deposits or 0.0) + (event.amount if event.event_type == "deposit" else 0.0)
                state.total_withdrawals = (state.total_withdrawals or 0.0) + (event.amount if event.event_type == "withdrawal" else 0.0)

                # Record transaction event
                tx_event = TransactionEvent(
                    type=event.event_type,
                    amount=event.amount,
                    balance_after=state.bankroll,
                    context={
                        "source": event.source,
                        "token": event.token,
                        "tx_hash": event.tx_hash,
                        "auto_updated_live_initial": True,
                    },
                    note=f"{event.event_type.title()} from {event.source} (auto-tracked)",
                )
                db.add(tx_event)
                db.commit()

                logger.info(
                    f"[ActivityHandler] Bankroll updated: {old_bankroll:.2f} → {state.bankroll:.2f}, "
                    f"live_initial: {state.live_initial_bankroll:.2f}"
                )
        except Exception as e:
            logger.opt(exception=True).warning(f"[ActivityHandler] Failed to update bankroll: {e}")

    async def _handle_trade_open(self, event: ActivityEvent):
        """Record trade_open → create pending Trade in DB."""
        logger.info(
            f"[{event.source}] TRADE OPEN: {event.side} {event.amount} @ {event.price} "
            f"order={event.order_id} tx={event.tx_hash or 'n/a'}"
        )
        try:
            from backend.db.utils import get_db_session
            from backend.models.database import Trade

            with get_db_session() as db:
                trade = Trade(
                    market_ticker=event.market_ticker or event.raw_data.get("market_ticker", "UNKNOWN"),
                    strategy=event.raw_data.get("strategy", event.source),
                    trading_mode="live",
                    direction=event.side or "UNKNOWN",
                    entry_price=event.price or 0.0,
                    size=event.amount,
                    status="open",
                    confidence=event.raw_data.get("confidence", 0.5),
                    external_order_id=event.order_id,
                )
                db.add(trade)
                db.commit()
                logger.info(f"[ActivityHandler] Trade created: id={trade.id}, {trade.direction} {trade.size}")
        except Exception as e:
            logger.opt(exception=True).warning(f"[ActivityHandler] Failed to create trade: {e}")

    async def _handle_trade_close(self, event: ActivityEvent):
        """Record trade_closed → finalize Trade in DB."""
        logger.info(
            f"[{event.source}] TRADE CLOSED: PnL={event.pnl} tx={event.tx_hash or 'n/a'}"
        )
        try:
            from backend.db.utils import get_db_session
            from backend.models.database import Trade

            with get_db_session() as db:
                # Find open trade by external_order_id or most recent open trade for this source
                trade = db.query(Trade).filter(
                    Trade.external_order_id == event.order_id,
                    Trade.status == "open",
                    Trade.trading_mode == "live",
                ).order_by(Trade.created_at.desc()).first()

                if trade:
                    trade.status = "settled"
                    trade.settled = True
                    trade.exit_price = event.price
                    trade.pnl = event.pnl
                    trade.result = "win" if (event.pnl or 0) > 0 else "loss"
                    db.commit()
                    logger.info(f"[ActivityHandler] Trade {trade.id} closed: PnL={event.pnl}")
                else:
                    logger.warning(f"[ActivityHandler] No open trade found for order_id={event.order_id}")
        except Exception as e:
            logger.opt(exception=True).warning(f"[ActivityHandler] Failed to close trade: {e}")

    def get_pending_events(self, limit: int = 50) -> list[ActivityEvent]:
        return self._tracker.get_recent_events(limit)