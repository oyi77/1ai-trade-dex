"""
Confidence thresholds and regime routing — min confidence, regime multipliers.
"""

from typing import Optional

from backend.config import settings
from loguru import logger


def _get_confidence_threshold(
    trading_mode: str, strategy_name: Optional[str] = None
) -> float:
    """Get confidence threshold for trade approval, respecting regime routing."""
    is_paper = (trading_mode or "").lower() in ("paper", "shadow")
    if is_paper:
        base_confidence = getattr(
            settings,
            "PAPER_AUTO_APPROVE_MIN_CONFIDENCE",
            settings.AUTO_APPROVE_MIN_CONFIDENCE,
        )
    else:
        base_confidence = getattr(
            settings, "MIN_CONFIDENCE", settings.AUTO_APPROVE_MIN_CONFIDENCE
        )

    if getattr(settings, "REGIME_ROUTING_ENABLED", False):
        regime_multiplier = _get_regime_multiplier(strategy_name)
        threshold = base_confidence * regime_multiplier
    else:
        threshold = base_confidence

    return min(threshold, 0.95)


def _get_regime_multiplier(strategy_name: Optional[str] = None) -> float:
    """Get current regime confidence multiplier from RegimeConfidenceRouter."""
    try:
        from backend.application.meta.regime_router import RegimeConfidenceRouter

        router = RegimeConfidenceRouter()
        return router.get_multiplier(strategy_name or "")
    except ImportError:
        # Fallback to default multiplier if regime router not available
        return 1.0


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
                "[risk.confidence] Category circuit breaker: {} has {} consecutive losses, "
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
            "[risk.confidence._check_category_circuit_breaker] {}: {}",
            type(e).__name__,
            e,
        )
        return None