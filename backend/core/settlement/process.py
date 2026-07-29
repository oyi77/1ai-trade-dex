"""
Process settled trades — update records, broadcast events, backfill decision logs,
and trigger learning hooks. Extracted from settlement_helpers.py.
"""

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session, sessionmaker

from backend.models.database import (
    Trade,
    Signal,
    SettlementEvent,
    DecisionLog,
    TransactionEvent,
)
from backend.config import settings
from backend.core.settlement.calculate_pnl import calculate_pnl
from backend.core.settlement.resolution import (
    fetch_polymarket_resolution,
    _fetch_kalshi_resolution,
)
from loguru import logger

# Import functions moved to weather.py
from backend.core.settlement.weather import (
    _try_calibrate_weather,
    _record_weather_observation,
)


async def process_settled_trade(
    trade: Trade,
    is_settled: bool,
    settlement_value: Optional[float],
    pnl: Optional[float],
    db: Session,
) -> bool:
    """
    Process a settled trade - update trade record, broadcast event, create settlement event,
    backfill decision log, and update signal.

    Returns True if trade was successfully processed and added to settled_trades list.
    """
    if not is_settled or settlement_value is None:
        return False

    if getattr(trade, "settled", False) and trade.pnl is not None:
        logger.debug(
            f"[process.process_settled_trade] Trade {trade.id} already settled (pnl={trade.pnl}), skipping"
        )
        return False

    trade.settled = True
    if settlement_value not in (0.0, 1.0):
        logger.error(
            f"[settlement] Invalid settlement_value={settlement_value} for trade {trade.id} "
            f"({trade.market_ticker}). Binary markets must be 0.0 or 1.0. Rejecting."
        )
        return False
    trade.settlement_value = settlement_value
    trade.pnl = pnl
    trade.settlement_time = datetime.now(timezone.utc)
    trade.settlement_source = "market_resolution"
    if pnl is not None and pnl > 0:
        trade.result = "win"
    elif pnl is not None and pnl < 0:
        trade.result = "loss"
    else:
        trade.result = "push"

    # Broadcast event
    try:
        from backend.core.event_bus import _broadcast_event

        _broadcast_event(
            "trade_settled",
            {
                "trade_id": trade.id,
                "market_ticker": trade.market_ticker,
                "result": trade.result,
                "pnl": trade.pnl,
                "mode": getattr(trade, "trading_mode", "paper"),
            },
        )
    except Exception as e:
        logger.debug(
            f"[process.process_settled_trade] {type(e).__name__}: Broadcast event failed: {e}",
            exc_info=True,
        )

    # Create settlement event
    platform = getattr(trade, "platform", "polymarket") or "polymarket"
    resolved_outcome = "up" if settlement_value == 1.0 else "down"
    db.add(
        SettlementEvent(
            trade_id=trade.id,
            market_ticker=trade.market_ticker,
            resolved_outcome=resolved_outcome,
            pnl=pnl,
            source=platform,
        )
    )

    # Backfill DecisionLog outcome for this trade
    try:
        outcome = (
            "WIN"
            if trade.result == "win"
            else ("LOSS" if trade.result == "loss" else "PUSH")
        )
        # Try to get strategy from TradeContext
        trade_ctx = (
            db.query(TradeContext).filter(TradeContext.trade_id == trade.id).first()
        )
        dl_query = db.query(DecisionLog).filter(
            DecisionLog.market_ticker == trade.market_ticker,
            DecisionLog.outcome.is_(None),
            DecisionLog.decision == "BUY",
        )
        if trade_ctx and trade_ctx.strategy:
            dl_query = dl_query.filter(DecisionLog.strategy == trade_ctx.strategy)
        decisions = dl_query.all()
        for decision in decisions:
            decision.outcome = outcome
    except Exception as e:
        logger.opt(exception=True).debug(
            "[process.process_settled_trade] {}: DecisionLog outcome backfill failed for {}: {!r}",
            type(e).__name__,
            trade.market_ticker,
            e,
        )

    # Update linked signal
    if trade.signal_id:
        linked_signal = db.query(Signal).filter(Signal.id == trade.signal_id).first()
        if linked_signal:
            actual_outcome = "up" if settlement_value == 1.0 else "down"
            linked_signal.actual_outcome = actual_outcome
            linked_signal.outcome_correct = linked_signal.direction == actual_outcome
            linked_signal.settlement_value = settlement_value
            linked_signal.settled_at = datetime.now(timezone.utc)
            market_type = getattr(trade, "market_type", "btc") or "btc"
            if market_type == "weather" and linked_signal.sources:
                await _try_calibrate_weather(linked_signal, settlement_value)

            if market_type == "weather":
                try:
                    await _record_weather_observation(trade, settlement_value, db)
                except Exception as e:
                    logger.opt(exception=True).debug(
                        "[process.process_settled_trade] {}: Weather calibration update skipped for {}: {!r}",
                        type(e).__name__,
                        trade.market_ticker,
                        e,
                    )

    # Write outcome to BigBrain (unified memory)
    try:
        from backend.clients.bigbrain import get_bigbrain

        brain = get_bigbrain()
        await brain.write_trade_outcome(
            {
                "strategy": getattr(trade, "strategy", "unknown"),
                "market": trade.market_ticker,
                "direction": trade.direction,
                "result": trade.result,
                "pnl": pnl,
                "edge": getattr(trade, "edge_at_entry", 0.0),
                "confidence": getattr(trade, "confidence", 0.5),
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        )
    except Exception as e:
        logger.opt(exception=True).debug(
            "[process.process_settled_trade] {}: BigBrain write_trade_outcome failed for trade {}: {!r}",
            type(e).__name__,
            trade.id,
            e,
        )

    # Record calibration outcome for model validation
    try:
        from backend.core.learning.calibration_tracker import calibration_tracker

        calibration_tracker.record_outcome(db, trade.market_ticker, settlement_value)
    except Exception as e:
        logger.opt(exception=True).debug(
            "[process.process_settled_trade] {}: Calibration record failed for {}: {!r}",
            type(e).__name__,
            trade.market_ticker,
            e,
        )

    # Flush settlement state before optional learner work so any learner-session
    # rollback/savepoint cleanup cannot erase the main settlement changes.
    db.flush()

    # Trigger realtime RL learner — fire-and-forget, never blocks settlement
    try:
        from backend.core.learning.online_learner import OnlineLearner

        learner = OnlineLearner()
        learner_session_factory = sessionmaker(
            bind=db.connection(),
            autocommit=False,
            autoflush=False,
            join_transaction_mode="create_savepoint",
        )
        learner_db = learner_session_factory()
        try:
            learner_trade = learner_db.query(Trade).filter(Trade.id == trade.id).first()
            if learner_trade is not None:
                learner.on_trade_settled(learner_trade, learner_db)
        except Exception:
            learner_db.rollback()
            raise
        finally:
            learner_db.close()
    except Exception as e:
        logger.warning(
            "[process.process_settled_trade] {}: online_learner hook failed for trade {}: {}",
            type(e).__name__,
            getattr(trade, "id", "?"),
            e,
        )

    # Trade forensics: analyze losing trades for patterns (non-blocking)
    if trade.result == "loss":
        try:
            from backend.core.trade_forensics import trade_forensics

            await trade_forensics.analyze_losing_trade(trade.id)
        except Exception as e:
            logger.opt(exception=True).debug(
                "[process] Trade forensics failed for trade {}: {!r}",
                trade.id,
                e,
            )

    if trade.strategy:
        try:
            from backend.core.strategy_performance_registry import (
                strategy_performance_registry,
            )

            strategy_performance_registry.update_from_settlement(trade.strategy, db=db)
        except Exception as e:
            logger.opt(exception=True).debug(
                "[process] Performance registry update failed for {}: {!r}",
                trade.strategy,
                e,
            )

    # Record TransactionEvent for settlement P&L (ledger entry)
    try:
        event_type = "settlement_win" if trade.result == "win" else "settlement_loss"
        trade_mode = getattr(trade, "trading_mode", "paper") or "paper"
        bot = db.query(BotState).filter_by(mode=trade_mode).first()
        prior_balance = bot.bankroll if bot else 0.0
        estimated_balance = prior_balance + pnl
        event = TransactionEvent(
            type=event_type,
            amount=pnl,
            balance_after=estimated_balance,
            context={
                "trade_id": trade.id,
                "strategy": trade.strategy,
                "market_ticker": trade.market_ticker,
                "direction": trade.direction,
            },
            note=f"Trade {trade.id} settled {trade.result} (P&L: {pnl:.2f})",
        )
        db.add(event)
    except Exception as e:
        logger.opt(exception=True).debug(
            "[process] TransactionEvent recording failed for trade {}: {!r}",
            trade.id,
            e,
        )

    # Record outcome to strategy_outcomes table
    try:
        from backend.core.outcome_repository import record_outcome

        record_outcome(trade, db)
    except Exception as e:
        logger.opt(exception=True).debug(
            "[process.process_settled_trade] {}: outcome_repository.record_outcome failed for {}: {!r}",
            type(e).__name__,
            trade.market_ticker,
            e,
        )

    return True


async def check_market_settlement(
    trade: Trade,
) -> tuple[bool, float | None, float | None]:
    """
    Check if a trade's market has settled.

    Returns: (is_settled, settlement_value, pnl)
    """
    platform = getattr(trade, "platform", "polymarket") or "polymarket"

    if platform == "kalshi":
        is_resolved, settlement_value = await _fetch_kalshi_resolution(
            trade.market_ticker
        )
    elif platform == "lighter":
        is_resolved, settlement_value = False, None
    else:
        is_resolved, settlement_value = await fetch_polymarket_resolution(
            trade.market_ticker,
            event_slug=trade.event_slug,
            condition_id=getattr(trade, "condition_id", None),
        )

    if not is_resolved or settlement_value is None:
        return False, None, None

    pnl = calculate_pnl(trade, settlement_value)

    mapped_dir = "UP" if trade.direction in ("up", "yes") else "DOWN"
    outcome = "UP" if settlement_value == 1.0 else "DOWN"
    result = "WIN" if mapped_dir == outcome else "LOSS"

    logger.info(
        f"Trade {trade.id} settled: {mapped_dir} @ {trade.entry_price:.0%} -> "
        f"{result} P&L: ${pnl:+.2f}"
    )

    return True, settlement_value, pnl
