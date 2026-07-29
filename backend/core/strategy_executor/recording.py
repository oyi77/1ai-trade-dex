"""Trade recording — BotState update, Trade/Signal creation, event broadcast."""

import time
from datetime import datetime, timezone
from typing import Optional

from loguru import logger
from sqlalchemy import func, and_

from backend.core.validation import TradeValidator
from backend.core.event_bus import _broadcast_event
from backend.models.database import Trade, Signal, TradeAttempt


def _commit_with_retry(db, max_attempts: int = 3) -> bool:
    """Commit DB session with retry on OperationalError."""
    from sqlalchemy.exc import OperationalError

    for attempt in range(max_attempts):
        try:
            db.commit()
            return True
        except OperationalError:
            if attempt < max_attempts - 1:
                db.rollback()
                continue
            raise
    return False


def _first_numeric_attr(d: dict, keys: tuple) -> Optional[float]:
    """Return the first numeric value found in *d* for any *keys*."""
    for k in keys:
        v = d.get(k)
        if v is not None:
            try:
                return float(v)
            except (TypeError, ValueError):
                pass
    return None


def _update_botstate_after_trade(
    db, mode: str, fill_price: float = 0.0, size: float = 0.0, role: str = ""
) -> None:
    """Update bankroll and trade count on BotState after a successful trade.

    Uses the appropriate bankroll column based on mode (paper_bankroll for paper,
    bankroll for live/testnet). Protected by ``_botstate_threading_lock``.
    """
    from backend.models.database import BotState as QBS

    state = db.query(QBS).filter_by(mode=mode).first()
    if not state:
        logger.warning("[strategy_executor] No BotState for mode=%s", mode)
        return

    # Pick the right bankroll column based on trading mode
    bankroll_col = "paper_bankroll" if mode == "paper" else "bankroll"
    current = getattr(state, bankroll_col, 0.0) or 0.0

    # Bankroll adjustment: paper/testnet always deducts entry cost.
    # For live, role determines direction (taker=cost, maker=rebate).
    if mode == "paper" or mode == "testnet":
        setattr(state, bankroll_col, current - size)
    elif role == "taker":
        setattr(state, bankroll_col, current - size)
    elif role == "maker":
        setattr(state, bankroll_col, current + size)

    state.total_trades = (state.total_trades or 0) + 1

    # Update mode-specific trade counter
    trade_count_col = f"{mode}_trades" if mode in ("paper", "testnet", "live") else None
    if trade_count_col and hasattr(state, trade_count_col):
        current_trades = getattr(state, trade_count_col, 0) or 0
        setattr(state, trade_count_col, current_trades + 1)


def _record_unexpected_attempt_failure(
    db, decision, strategy_name, mode, reason, attempt_id=None
):
    """Best-effort persistence for unexpected failures during execution."""
    try:
        from uuid import uuid4

        attempt = TradeAttempt(
            attempt_id=attempt_id or str(uuid4()),
            strategy_name=strategy_name,
            trading_mode=mode,
            market_ticker=decision.get("market_ticker", ""),
            direction=decision.get("direction", ""),
            confidence=float(decision.get("confidence", 0.0)),
            requested_size=float(decision.get("size", 0.0)),
            status="FAILED",
            phase="execution",
            reason_code="UNEXPECTED_ERROR",
            reason=reason,
        )
        db.add(attempt)
        db.commit()
    except Exception as log_err:
        import traceback as _tb
        logger.warning(
            "[strategy_executor] Failed to record unexpected failure: %s\n%s", log_err, _tb.format_exc()
        )
        try:
            db.rollback()
        except Exception:
            pass


def _record_trade(
    db,
    decision: dict,
    strategy_name: str,
    mode: str,
    pf,
    clob_order_id,
    fill_price: float,
    entry_price: float,
    filled_size,
    fee: Optional[float],
    role: str,
    maker_size,
    taker_size,
    attempt_recorder,
) -> Optional[dict]:
    """Create Trade + Signal + broadcast events. Shared by paper and live paths.

    Args:
        db: DB session.
        decision: Trade decision dict.
        strategy_name: Name of the strategy.
        mode: Trading mode (paper/testnet/live).
        pf: PreflightResult from _preflight_checks.
        clob_order_id: Optional CLOB order ID for live fills.
        fill_price: Filled price after slippage.
        entry_price: Original entry price from decision.
        filled_size: Actual filled size.
        fee: Fee in USD.
        role: Trade role (maker/taker).
        maker_size: Size classified as maker.
        taker_size: Size classified as taker.
        attempt_recorder: TradeAttemptRecorder instance.

    Returns:
        Trade model instance on success, or None if validation failed.
    """
    market_ticker = decision.get("market_ticker", "")
    direction = decision.get("direction", "")
    confidence = float(decision.get("confidence", 0.0))
    model_probability = float(decision.get("model_probability", confidence))
    token_id = decision.get("token_id")
    platform = decision.get("platform", "polymarket")
    reasoning = decision.get("reasoning", "")
    market_type = decision.get("market_type", "btc")
    edge = float(decision.get("edge", 0.0))

    adjusted_size = pf.adjusted_size if pf is not None else filled_size

    slippage = abs(fill_price - entry_price) / entry_price if entry_price > 0 else 0.0

    trade_data = {
        "market_ticker": market_ticker,
        "platform": platform,
        "direction": direction,
        "entry_price": fill_price,
        "size": adjusted_size,
        "model_probability": model_probability,
        "market_price_at_entry": entry_price,
        "edge_at_entry": edge,
        "trading_mode": mode,
        "confidence": confidence,
        "result": "pending",
    }

    try:
        TradeValidator.validate_trade_data(trade_data)
    except Exception as e:
        logger.error(f"[{strategy_name}] Trade validation failed: {e}")
        if attempt_recorder:
            attempt_recorder.record_rejected(
                f"Trade validation failed: {e}",
                phase="validation",
                reason_code="REJECTED_TRADE_VALIDATION",
                adjusted_size=adjusted_size,
            )
        db.commit()
        return None

    trade = Trade(
        market_ticker=market_ticker,
        platform=platform,
        direction=direction,
        entry_price=fill_price,
        size=adjusted_size,
        model_probability=model_probability,
        market_price_at_entry=entry_price,
        edge_at_entry=edge,
        trading_mode=mode,
        strategy=strategy_name,
        confidence=confidence,
        clob_order_id=clob_order_id,
        filled_size=filled_size,
        fill_price=fill_price,
        fee=fee,
        slippage=slippage,
        market_type=market_type,
        market_end_date=getattr(pf, "market_end_date", None) if pf else None,
        token_id=token_id,
        condition_id=decision.get("condition_id") or decision.get("slug"),
        role=role,
        maker_size=maker_size,
        taker_size=taker_size,
        arb_bundle_id=decision.get("arb_bundle_id"),
        arb_leg_index=decision.get("arb_leg_index"),
        arb_leg_count=decision.get("arb_leg_count"),
    )

    db.add(trade)
    db.flush()

    # --- Signal record ---
    signal = Signal(
        market_ticker=market_ticker,
        platform=platform,
        market_type=market_type,
        direction=direction,
        market_price=fill_price,
        model_probability=model_probability,
        edge=edge,
        confidence=confidence,
        suggested_size=adjusted_size,
        reasoning=reasoning if reasoning else None,
        execution_mode=mode,
        token_id=token_id,
        executed=True,
        track_name=strategy_name,
    )
    db.add(signal)

    # --- Attempt success ---
    if attempt_recorder:
        attempt_recorder.record_executed(
            trade_id=trade.id,
            reason="Trade executed",
            filled_size=filled_size,
            fill_price=fill_price,
            fee=fee,
            slippage_bps=slippage * 10000,
        )

    # --- Broadcast ---
    try:
        _broadcast_event(
            "trade_executed",
            {
                "trade_id": trade.id,
                "market_ticker": market_ticker,
                "direction": direction,
                "size": adjusted_size,
                "fill_price": fill_price,
                "role": role,
                "mode": mode,
            },
        )
    except Exception:
        logger.opt(exception=True).warning(
            "[strategy_executor] Failed to broadcast trade event"
        )

    db.commit()
    return trade