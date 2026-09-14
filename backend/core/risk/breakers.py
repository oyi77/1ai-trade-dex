"""
Circuit breaker validation — daily loss, drawdown, and category breakers.
"""

from typing import Optional

from backend.config import settings
from loguru import logger

from .models import _not_backfill_settlement_source


def _breaker_enabled_for_mode(breaker: str, mode: str) -> bool:
    """Check whether a circuit breaker is enabled for the given trading mode.

    breaker: "drawdown" or "daily_loss"
    mode: "paper", "testnet", or "live"

    Paper mode defaults to breaker-disabled so it can run infinitely for
    backtest, frontest, and improvement loops. Testnet and live default
    to breaker-enabled for capital safety.
    """
    if breaker == "drawdown":
        config = settings.DRAWDOWN_BREAKER_ENABLED_PER_MODE
    elif breaker == "daily_loss":
        config = settings.DAILY_LOSS_LIMIT_ENABLED_PER_MODE
    else:
        return True
    return config.get(mode, True)


def _validate_trade_daily_loss_breaker(
    effective_mode: str, db, strategy_name: Optional[str]
) -> Optional[str]:
    """Check daily loss circuit breaker. Returns rejection reason or None."""
    if not _breaker_enabled_for_mode("daily_loss", effective_mode):
        logger.debug(
            "[risk.breakers] Daily loss breaker disabled for mode=%s — skipping",
            effective_mode,
        )
        return None
    from .drawdown import _daily_loss_exceeded

    if _daily_loss_exceeded(db=db, mode=effective_mode):
        from backend.monitoring.metrics import increment_risk_rejection
        from backend.monitoring.hft_metrics import record_signal

        record_signal(
            strategy=strategy_name or "unknown", signal_type="rejected_daily_loss"
        )
        increment_risk_rejection(
            strategy=strategy_name or "unknown", reason="daily_loss"
        )
        return "daily loss limit hit"
    return None


def _validate_trade_drawdown_breaker(
    bankroll: float, db, effective_mode: str, strategy_name: Optional[str]
) -> Optional[str]:
    """Check drawdown breaker. Returns rejection reason or None."""
    if not _breaker_enabled_for_mode("drawdown", effective_mode):
        logger.debug(
            "[risk.breakers] Drawdown breaker disabled for mode=%s — skipping",
            effective_mode,
        )
        return None
    from .drawdown import check_drawdown

    drawdown = check_drawdown(bankroll, db=db, mode=effective_mode)
    if drawdown.is_breached:
        from backend.monitoring.metrics import increment_risk_rejection
        from backend.monitoring.hft_metrics import record_signal

        record_signal(
            strategy=strategy_name or "unknown", signal_type="rejected_drawdown"
        )
        increment_risk_rejection(
            strategy=strategy_name or "unknown", reason="drawdown"
        )
        return f"drawdown breaker: {drawdown.breach_reason}"
    return None


def _validate_trade_category_breaker(
    category: Optional[str], db, effective_mode: str, strategy_name: Optional[str]
) -> Optional[str]:
    """Check category circuit breaker. Returns rejection reason or None."""
    if not (category and db is not None):
        return None
    cat_cooldown = _check_category_circuit_breaker(category, db, effective_mode)
    if cat_cooldown:
        from backend.monitoring.metrics import increment_risk_rejection
        from backend.monitoring.hft_metrics import record_signal

        record_signal(
            strategy=strategy_name or "unknown",
            signal_type="rejected_category_breaker",
        )
        increment_risk_rejection(
            strategy=strategy_name or "unknown", reason="category_breaker"
        )
        return cat_cooldown
    return None


def _check_category_circuit_breaker(
    category: str, db, mode: str
) -> Optional[str]:
    """G-17: Check if a market category has exceeded consecutive loss limit.

    If a category has > N consecutive losses, pause trading in that category
    for CATEGORY_COOLDOWN_MINUTES (default 120).

    Returns a rejection reason string if the category is paused, None otherwise.
    """
    try:
        limit = int(getattr(settings, "CATEGORY_CONSECUTIVE_LOSS_LIMIT", 3) or 3)
        cooldown_min = int(getattr(settings, "CATEGORY_COOLDOWN_MINUTES", 120) or 120)

        from datetime import datetime, timezone

        now = datetime.now(timezone.utc)
        # Look at recent trades in this category
        from backend.models.database import Trade

        recent_trades = (
            db.query(Trade)
            .filter(
                Trade.category == category,
                Trade.settled.is_(True),
                Trade.trading_mode == mode,
                Trade.result.in_(["win", "loss"]),
            )
            .order_by(Trade.settlement_time.desc())
            .limit(limit)
            .all()
        )

        if len(recent_trades) < limit:
            return None

        # Check if all recent trades are losses
        all_losses = all(t.result == "loss" for t in recent_trades)
        if not all_losses:
            return None

        # Check if cooldown has elapsed since the most recent loss
        latest_loss_time = recent_trades[0].settlement_time
        if latest_loss_time and latest_loss_time.tzinfo is None:
            latest_loss_time = latest_loss_time.replace(tzinfo=timezone.utc)

        from datetime import timedelta

        cooldown_end = latest_loss_time + timedelta(minutes=cooldown_min)
        if now < cooldown_end:
            remaining = (cooldown_end - now).total_seconds() / 60
            logger.info(
                "[risk.breakers] Category circuit breaker: {} has {} consecutive losses, "
                "paused for {:.0f} more minutes",
                category,
                limit,
                remaining,
            )
            return (
                f"category '{category}' circuit breaker: "
                f"{limit} consecutive losses, paused {remaining:.0f}min"
            )

        return None

    except Exception as e:
        logger.opt(exception=True).error(
            "[risk.breakers._check_category_circuit_breaker] {}: {}",
            type(e).__name__,
            e,
        )
        return None