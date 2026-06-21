"""Activity event handler — processes events into bankroll + positions."""

from __future__ import annotations
from typing import TYPE_CHECKING

from backend.core.activity.models import ActivityEvent
from loguru import logger

if TYPE_CHECKING:
    from backend.core.activity.tracker import ActivityTracker


class ActivityHandler:
    """Processes activity events → updates bankroll, positions, DB."""

    def __init__(self, tracker: "ActivityTracker", db_session_factory):
        self._tracker = tracker
        self._db = db_session_factory
        self._tracker.on_event(self.handle_event)

    async def handle_event(self, event: ActivityEvent):
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
            logger.opt(exception=True).warning(
                f"[ActivityHandler] Failed to persist event {event.id}: {e}"
            )

    async def _handle_transfer(self, event: ActivityEvent):
        """Record deposit/withdrawal via the centralized BotStateLedger."""
        logger.info(
            f"[{event.source}] {event.event_type.upper()}: {event.amount} {event.token} "
            f"tx={event.tx_hash or 'internal'}"
        )
        try:
            from backend.db.utils import get_db_session
            from backend.core.wallet.botstate_ledger import BotStateLedger
            from backend.models.database import BotState, TransactionEvent

            with get_db_session() as db:
                state = db.query(BotState).filter_by(mode="live").first()
                if not state:
                    logger.warning("[ActivityHandler] No live BotState found")
                    return

                if event.event_type == "deposit":
                    BotStateLedger.record_deposit(
                        db=db,
                        mode="live",
                        amount=float(event.amount),
                        source=event.source or "blockchain_activity",
                    )
                elif event.event_type == "withdrawal":
                    BotStateLedger.record_withdrawal(
                        db=db,
                        mode="live",
                        amount=float(event.amount),
                        source=event.source or "blockchain_activity",
                    )

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
                    f"[ActivityHandler] Bankroll updated: {state.bankroll:.2f}, "
                    f"live_initial: {state.live_initial_bankroll:.2f}"
                )
        except Exception as e:
            logger.opt(exception=True).warning(
                f"[ActivityHandler] Failed to update bankroll: {e}"
            )

    async def _handle_trade_open(self, event: ActivityEvent):
        logger.info(
            f"[{event.source}] TRADE OPEN: {event.side} {event.amount} @ {event.price} "
            f"order={event.order_id} tx={event.tx_hash or 'n/a'}"
        )
        try:
            from backend.db.utils import get_db_session
            from backend.models.database import Trade

            with get_db_session() as db:
                market_ticker = (
                    event.raw_data.get("market_ticker")
                    if isinstance(event.raw_data, dict)
                    else None
                )
                if not market_ticker:
                    return
                from backend.core.trade_forensics import classify_trade_role

                role, maker_size, taker_size = await classify_trade_role(
                    platform=event.platform or event.source or "polymarket",
                    mode="live",
                    clob_order_id=event.order_id,
                    price=event.price or 0.0,
                    size=event.amount,
                    direction=(
                        "up" if (event.side or "").lower() in ("buy", "up") else "down"
                    ),
                    decision=event.raw_data if isinstance(event.raw_data, dict) else {},
                    db_session=db,
                )

                trade = Trade(
                    market_ticker=market_ticker,
                    strategy=event.raw_data.get("strategy", event.source),
                    trading_mode="live",
                    direction=event.side or "UNKNOWN",
                    entry_price=event.price or 0.0,
                    size=event.amount,
                    status="open",
                    confidence=event.raw_data.get("confidence", 0.5),
                    clob_order_id=event.order_id,
                    role=role,
                    maker_size=maker_size,
                    taker_size=taker_size,
                )
                db.add(trade)
                db.commit()
                logger.info(
                    f"[ActivityHandler] Trade created: id={trade.id}, {trade.direction} {trade.size}"
                )
        except Exception as e:
            logger.opt(exception=True).warning(
                f"[ActivityHandler] Failed to create trade: {e}"
            )

    async def _handle_trade_close(self, event: ActivityEvent):
        logger.info(
            f"[{event.source}] TRADE CLOSED: PnL={event.pnl} tx={event.tx_hash or 'n/a'}"
        )
        try:
            from backend.db.utils import get_db_session
            from backend.models.database import Trade

            with get_db_session() as db:
                # Find open trade by clob_order_id or most recent open trade for this source
                trade = (
                    db.query(Trade)
                    .filter(
                        Trade.clob_order_id == event.order_id,
                        Trade.status == "open",
                        Trade.trading_mode == "live",
                    )
                    .order_by(Trade.created_at.desc())
                    .first()
                )

                if trade:
                    trade.status = "settled"
                    trade.settled = True
                    trade.exit_price = event.price
                    trade.pnl = event.pnl
                    trade.result = "win" if (event.pnl or 0) > 0 else "loss"
                    db.commit()
                    logger.info(
                        f"[ActivityHandler] Trade {trade.id} closed: PnL={event.pnl}"
                    )
                else:
                    logger.warning(
                        f"[ActivityHandler] No open trade found for order_id={event.order_id}"
                    )
        except Exception as e:
            logger.opt(exception=True).warning(
                f"[ActivityHandler] Failed to close trade: {e}"
            )

    def get_pending_events(self, limit: int = 50) -> list[ActivityEvent]:
        return self._tracker.get_recent_events(limit)
