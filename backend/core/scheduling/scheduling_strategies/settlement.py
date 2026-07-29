"""Settlement and blockchain verification jobs."""

import asyncio
from datetime import UTC, datetime

from loguru import logger

from backend.config import settings
from backend.models.database import BotState, Trade


async def settlement_job():
    """Check and settle pending trades. Runs every 2 minutes."""
    import asyncio as _aio

    try:
        await _aio.wait_for(_settlement_job_inner(), timeout=120)
    except TimeoutError:
        from backend.core.scheduling.scheduler import log_event

        log_event("error", "Settlement job timed out after 120s")
    except Exception as e:
        from backend.core.scheduling.scheduler import log_event

        log_event("error", f"Settlement job failed: {e}")


async def _settlement_job_inner():
    """Actual settlement logic wrapped with timeout."""
    await asyncio.sleep(0)  # yield control to event loop
    from backend.core.scheduling.scheduler import log_event

    log_event("info", "Checking BTC trade settlements...")

    def _read_pending_count():
        from backend.db.utils import get_db_session

        with get_db_session() as db:
            return db.query(Trade).filter(Trade.settled.is_(False)).count()

    try:
        from backend.core.settlement import (
            reconcile_bot_state,
            settle_pending_trades,
            update_bot_state_with_settlements,
        )

        pending_count = await asyncio.to_thread(_read_pending_count)

        if pending_count == 0:
            log_event("data", "No pending trades to settle")
            return

        log_event("data", f"Processing {pending_count} pending trades")

        from backend.db.utils import get_db_session

        with get_db_session() as db:
            settled = await settle_pending_trades(db)

            if settled:
                await update_bot_state_with_settlements(db, settled)

                wins = sum(1 for t in settled if t.result == "win")
                losses = sum(1 for t in settled if t.result == "loss")
                total_pnl = sum(t.pnl for t in settled if t.pnl is not None)

                log_event(
                    "success",
                    f"Settled {len(settled)} trades: {wins}W/{losses}L, P&L: ${total_pnl:.2f}",
                    {
                        "settled_count": len(settled),
                        "wins": wins,
                        "losses": losses,
                        "pnl": total_pnl,
                    },
                )

                from backend.bot.notification.registry import registry

                for trade in settled:
                    result_prefix = "+" if trade.pnl and trade.pnl > 0 else ""
                    log_event(
                        "data",
                        f"  {trade.event_slug}: {trade.result.upper()} {result_prefix}${trade.pnl:.2f}",
                    )
                    if settings.TELEGRAM_BOT_TOKEN:
                        await registry.send_to("telegram", "trade_settled", str(trade))
            else:
                log_event("info", "No trades ready for settlement")

        # Reconcile in separate session to avoid corruption spreading
        with get_db_session() as recon_db:
            await reconcile_bot_state(recon_db)

    except Exception as e:
        log_event("error", f"Settlement error: {str(e)}")
        logger.exception("Error in settlement_job")


async def verify_settlement_blockchain():
    """Check unsettled trades and update with blockchain-verified settlement data."""
    await asyncio.sleep(0)  # yield control to event loop
    from backend.core.scheduling.scheduler import log_event
    from backend.core.settlement.settlement_helpers import (
        calculate_pnl,
        fetch_resolution_for_trade,
    )

    def _read_unsettled_trades():
        from backend.db.utils import get_db_session

        with get_db_session() as db:
            unsettled = db.query(Trade).filter(Trade.settled.is_(False)).all()
            if not unsettled:
                state = db.query(BotState).first()
                if state:
                    state.settlement_last_check_at = datetime.now(UTC)
                    db.flush()
                return []
            return [
                {
                    "id": t.id,
                    "market_ticker": t.market_ticker,
                    "settled": t.settled,
                    "settlement_value": t.settlement_value,
                    "pnl": t.pnl,
                    "result": t.result,
                    "direction": t.direction,
                    "size": t.size,
                    "entry_price": t.entry_price,
                    "event_slug": t.event_slug,
                    "token_id": t.token_id,
                    "trading_mode": t.trading_mode,
                    "market_type": t.market_type,
                    "outcome": t.outcome,
                }
                for t in unsettled
            ]

    try:
        trade_dicts = await asyncio.to_thread(_read_unsettled_trades)
        if not trade_dicts:
            log_event("data", "Settlement verification: no unsettled trades")
            return

        settled_count = 0
        error_count = 0
        settlements = []

        from backend.db.utils import get_db_session

        with get_db_session() as db:
            unsettled_trades = db.query(Trade).filter(Trade.settled.is_(False)).all()
            trade_map = {t.id: t for t in unsettled_trades}

            for td in trade_dicts:
                trade = trade_map.get(td["id"])
                if not trade:
                    continue
                try:
                    is_resolved, settlement_value = await fetch_resolution_for_trade(
                        trade
                    )

                    if is_resolved and settlement_value is not None:
                        pnl = calculate_pnl(trade, settlement_value)

                        trade.settled = True
                        trade.settlement_value = settlement_value
                        trade.pnl = pnl
                        trade.settlement_time = datetime.now(UTC)
                        trade.blockchain_verified = True

                        if pnl is not None and pnl > 0:
                            trade.result = "win"
                        elif pnl is not None and pnl < 0:
                            trade.result = "loss"
                        else:
                            trade.result = "push"

                        settled_count += 1
                        settlements.append(
                            {
                                "id": trade.id,
                                "market": trade.market_ticker,
                                "result": trade.result,
                                "pnl": pnl,
                            }
                        )

                except Exception as e:
                    error_count += 1
                    logger.warning(
                        f"Settlement verification failed for trade {td['id']}: {e}"
                    )
                    continue

            state = db.query(BotState).first()
            if state:
                state.settlement_last_check_at = datetime.now(UTC)

            db.commit()

        for s in settlements:
            logger.info(
                f"Settlement verified: trade_id={s['id']} market={s['market']} "
                f"result={s['result']} pnl=${s['pnl']:.2f}"
            )

        log_event(
            "success" if settled_count > 0 else "info",
            f"Settlement verified: {settled_count} trades settled, {error_count} errors",
            {
                "settled_count": settled_count,
                "error_count": error_count,
                "total_checked": len(trade_dicts),
            },
        )

    except Exception as e:
        log_event("error", f"Settlement verification job failed: {e}")
        logger.exception("Error in verify_settlement_blockchain")
