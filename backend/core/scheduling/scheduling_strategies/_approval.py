"""Signal approval and trade execution functions."""

from datetime import UTC, datetime

from loguru import logger

from backend.config import settings
from backend.core.decisions import record_decision
from backend.core.event_bus import _broadcast_event
from backend.models.database import PendingApproval, Trade

from ._helpers import _get_bankroll_for_mode


async def _process_signal_with_approval(
    signal,
    state,
    db,
    trades_executed: int,
    max_trades: int,
    effective_mode: str = None,
) -> int:
    """Process a trading signal through the configured approval pipeline."""
    from backend.core.scheduling.scheduler import log_event

    mode = effective_mode or settings.TRADING_MODE

    existing_trade = (
        db.query(Trade)
        .filter(
            Trade.event_slug == signal.market.slug,
            Trade.settled.is_(False),
            Trade.trading_mode == mode,
        )
        .first()
    )
    if existing_trade:
        logger.debug(f"Skipping {signal.market.slug}: already has open trade")
        return trades_executed

    if trades_executed >= max_trades:
        return trades_executed

    approval_mode = settings.SIGNAL_APPROVAL_MODE

    existing_pending = (
        db.query(PendingApproval)
        .filter(
            PendingApproval.market_id == signal.market.market_id,
            PendingApproval.status == "pending",
        )
        .first()
    )

    if existing_pending:
        if approval_mode == "manual":
            logger.debug(f"Skipping {signal.market.slug}: already has pending approval")
            return trades_executed
        else:
            existing_pending.status = "expired"
            db.flush()
            logger.debug(
                f"Auto-expired stale pending approval for {signal.market.slug} (mode={approval_mode})"
            )

    min_confidence = settings.AUTO_APPROVE_MIN_CONFIDENCE

    MAX_TRADE_FRACTION = settings.KELLY_FRACTION
    MIN_TRADE_SIZE = 5.0
    bankroll = _get_bankroll_for_mode(state, mode)
    trade_size = min(signal.suggested_size, bankroll * MAX_TRADE_FRACTION)
    trade_size = max(trade_size, MIN_TRADE_SIZE)

    if bankroll < MIN_TRADE_SIZE:
        log_event("warning", f"Bankroll too low: ${bankroll:.2f}")
        return trades_executed

    approval_signal = {
        "market_id": signal.market.market_id,
        "market_title": f"BTC {signal.market.window_start.strftime('%H:%M')} - {signal.market.window_end.strftime('%H:%M')} UTC",
        "side": signal.direction.upper(),
        "price": (
            signal.market.up_price
            if signal.direction == "up"
            else signal.market.down_price
        ),
        "size": trade_size,
        "confidence": signal.confidence,
        "model_probability": signal.model_probability,
        "market_probability": signal.market_probability,
        "edge": signal.edge,
        "direction": signal.direction,
        "slug": signal.market.slug,
        "up_token_id": signal.market.up_token_id,
        "down_token_id": signal.market.down_token_id,
    }

    if approval_mode == "auto_deny":
        record_decision(
            db,
            "crypto_oracle",
            signal.market.market_id,
            "SKIP",
            confidence=signal.confidence,
            signal_data={
                "direction": signal.direction,
                "model_probability": signal.model_probability,
                "market_probability": signal.market_probability,
                "edge": signal.edge,
                "btc_price": getattr(signal, "btc_price", None),
                "sources": ["crypto_oracle_scanner", "market_maker", "whale_tracker"],
            },
            reason="auto-deny mode: signal rejected",
        )
        log_event("info", f"Auto-denied signal for {signal.market.slug}")
        return trades_executed

    elif approval_mode == "auto_approve":
        if signal.confidence >= min_confidence:
            return await _execute_trade(
                signal, state, db, trade_size, trades_executed, mode=mode
            )
        else:
            log_event(
                "info",
                f"Auto-approve: skipping low-confidence signal ({signal.confidence:.2f} < {min_confidence}) for {signal.market.slug}",
            )
            record_decision(
                db,
                "crypto_oracle",
                signal.market.market_id,
                "SKIP",
                confidence=signal.confidence,
                signal_data={
                    "direction": signal.direction,
                    "model_probability": signal.model_probability,
                    "market_probability": signal.market_probability,
                    "edge": signal.edge,
                    "btc_price": getattr(signal, "btc_price", None),
                    "sources": [
                        "crypto_oracle_scanner",
                        "market_maker",
                        "whale_tracker",
                    ],
                },
                reason=f"auto-approve: confidence {signal.confidence:.2f} below threshold {min_confidence}",
            )
            return trades_executed

    return await _queue_for_approval(
        signal, state, db, trade_size, approval_signal, trades_executed
    )


async def _execute_trade(
    signal, state, db, trade_size, trades_executed: int, mode: str = None
) -> int:
    """Execute a BTC trade by delegating to strategy_executor.execute_decision()."""
    from backend.core.scheduling.scheduler import log_event
    from backend.core.strategy_executor import execute_decision

    entry_price = (
        signal.market.up_price if signal.direction == "up" else signal.market.down_price
    )
    token_id = (
        signal.market.up_token_id
        if signal.direction == "up"
        else signal.market.down_token_id
    )

    decision = {
        "market_ticker": signal.market.market_id,
        "slug": signal.market.slug,
        "event_slug": signal.market.slug,
        "direction": signal.direction,
        "size": trade_size,
        "entry_price": entry_price,
        "edge": signal.edge,
        "confidence": signal.confidence,
        "model_probability": signal.model_probability,
        "token_id": token_id,
        "platform": settings.DEFAULT_VENUE,
        "reasoning": f"edge {signal.edge:.3f} >= threshold, {signal.direction} @ {entry_price:.0%}",
    }

    result = await execute_decision(decision, "crypto_oracle", mode=mode)
    if result is None:
        return trades_executed

    trades_executed += 1

    try:
        from backend.bot.notification.registry import registry

        if settings.TELEGRAM_BOT_TOKEN:
            await registry.send_to("telegram", "btc_signal", str(signal))
    except Exception:
        logger.exception(
            f"[scheduling_strategies] BTC signal notification failed for {getattr(signal, 'market', None)}"
        )

    mode_label = f"[{mode.upper()}] " if mode != "paper" else ""
    log_event(
        "trade",
        f"{mode_label}BTC {signal.direction.upper()} ${trade_size:.0f} @ {entry_price:.0%} | {signal.market.slug}",
        {
            "slug": signal.market.slug,
            "direction": signal.direction,
            "size": trade_size,
            "edge": signal.edge,
            "entry_price": entry_price,
            "btc_price": getattr(signal, "btc_price", None),
        },
    )

    return trades_executed


async def _queue_for_approval(
    signal, state, db, trade_size, approval_signal, trades_executed: int
) -> int:
    """Queue a signal for manual approval."""
    from backend.core.scheduling.scheduler import log_event

    pending = PendingApproval(
        market_id=signal.market.market_id,
        direction=signal.direction.upper(),
        size=trade_size,
        confidence=signal.confidence,
        signal_data=approval_signal,
        status="pending",
    )
    db.add(pending)
    db.flush()

    try:
        record_decision(
            db,
            "crypto_oracle",
            signal.market.market_id,
            "PENDING",
            confidence=signal.confidence,
            signal_data={
                "direction": signal.direction,
                "model_probability": signal.model_probability,
                "market_probability": signal.market_probability,
                "edge": signal.edge,
                "btc_price": getattr(signal, "btc_price", None),
                "pending_id": pending.id,
                "trade_size": trade_size,
                "sources": ["crypto_oracle_scanner", "market_maker", "whale_tracker"],
            },
            reason=f"queued for manual approval (conf {signal.confidence:.2f})",
        )
    except Exception as _de:
        logger.warning(f"Decision logging (PENDING) failed: {_de}")

    try:
        _broadcast_event(
            "signal_found",
            {
                "market_ticker": signal.market.market_id,
                "market_title": f"BTC {signal.market.window_start.strftime('%H:%M')} - {signal.market.window_end.strftime('%H:%M')} UTC",
                "direction": signal.direction,
                "model_probability": signal.model_probability,
                "market_probability": signal.market_probability,
                "edge": signal.edge,
                "confidence": signal.confidence,
                "suggested_size": trade_size,
                "reasoning": "Signal queued for approval",
                "timestamp": datetime.now(UTC).isoformat(),
                "category": "trading",
                "btc_price": getattr(signal, "btc_price", None),
                "window_end": (
                    signal.market.window_end.isoformat()
                    if signal.market.window_end
                    else None
                ),
                "actionable": True,
                "event_slug": signal.market.slug,
            },
        )
    except Exception:
        logger.exception(
            f"[scheduling_strategies] Event broadcast 'signal_found' failed for {getattr(signal, 'market', None)}"
        )

    log_event(
        "info",
        f"Queued signal for approval: {signal.market.slug} (conf {signal.confidence:.2f})",
    )

    return trades_executed
