"""
Concentration and position-limit validation including cross-market correlation.
"""
from datetime import datetime, timedelta, timezone
from typing import Optional

import time
from loguru import logger
from sqlalchemy import func

from backend.models.database import Trade
from backend.monitoring.hft_metrics import record_signal
from backend.monitoring.metrics import increment_risk_rejection


def check_concentration(
    settings_obj,
    market_ticker: str,
    trade_size: float,
    bankroll: float,
    db,
    mode: str,
    correlation_monitor=None,
) -> Optional[str]:
    """G-18: Block if total exposure to same event exceeds MAX_CONCENTRATION_PCT of bankroll.

    Returns rejection reason string or None if passed.
    """
    try:
        profile_pct = getattr(settings_obj, "MAX_CONCENTRATION_PCT", 0.30) or 0.30
        max_concentration_pct = float(profile_pct) if bankroll >= 500 else 1.0
        logger.debug(
            f"[risk_manager.check_concentration] Checking ticker={market_ticker} size=${trade_size:.2f} "
            f"against dynamic concentration limit={max_concentration_pct:.0%} of bankroll (${bankroll:.2f})"
        )

        # Cross-market correlation check via CorrelationMonitor
        if correlation_monitor and market_ticker:
            corr_result = correlation_monitor.check_correlation(
                bankroll=bankroll,
                market_ticker=market_ticker,
                trade_size=trade_size,
                event_slug=None,
                db=db,
                mode=mode,
            )
            if not corr_result.allowed:
                return corr_result.reason

        # Get event_slug for this market to group by event
        event_slug = None
        existing = (
            db.query(Trade.event_slug)
            .filter(
                Trade.market_ticker == market_ticker,
                Trade.settled.is_(False),
                Trade.trading_mode == mode,
            )
            .first()
        )
        if existing and existing[0]:
            event_slug = existing[0]

        if event_slug:
            event_exposure = (
                db.query(func.coalesce(func.sum(Trade.size), 0.0))
                .filter(
                    Trade.event_slug == event_slug,
                    Trade.settled.is_(False),
                    Trade.trading_mode == mode,
                )
                .scalar()
                or 0.0
            )
        else:
            event_exposure = (
                db.query(func.coalesce(func.sum(Trade.size), 0.0))
                .filter(
                    Trade.market_ticker == market_ticker,
                    Trade.settled.is_(False),
                    Trade.trading_mode == mode,
                )
                .scalar()
                or 0.0
            )

        max_allowed = bankroll * max_concentration_pct
        if float(event_exposure) + trade_size > max_allowed:
            return (
                f"concentration: event exposure ${float(event_exposure):.2f} + "
                f"${trade_size:.2f} > {max_concentration_pct:.0%} of bankroll (${max_allowed:.2f})"
            )
        return None
    except Exception as e:
        logger.opt(exception=True).error(
            "[risk_manager.check_concentration] {}: {}",
            type(e).__name__, e,
        )
        return None


def check_category_circuit_breaker(
    settings_obj,
    category: str,
    db,
    mode: str,
) -> Optional[str]:
    """G-17: Check if a market category has exceeded consecutive loss limit.

    Returns rejection reason or None.
    """
    try:
        limit = int(getattr(settings_obj, "CATEGORY_CONSECUTIVE_LOSS_LIMIT", 3) or 3)
        cooldown_min = int(getattr(settings_obj, "CATEGORY_COOLDOWN_MINUTES", 120) or 120)

        now = datetime.now(timezone.utc)
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

        all_losses = all(t.result == "loss" for t in recent_trades)
        if not all_losses:
            return None

        latest_loss_time = recent_trades[0].settlement_time
        if latest_loss_time and latest_loss_time.tzinfo is None:
            latest_loss_time = latest_loss_time.replace(tzinfo=timezone.utc)

        cooldown_end = latest_loss_time + timedelta(minutes=cooldown_min)
        if now < cooldown_end:
            remaining = (cooldown_end - now).total_seconds() / 60
            logger.info(
                "[risk_manager] Category circuit breaker: {} has {} consecutive losses, "
                "paused for {:.0f} more minutes",
                category, limit, remaining,
            )
            return (
                f"category '{category}' circuit breaker: "
                f"{limit} consecutive losses, paused {remaining:.0f}min"
            )
        return None
    except Exception as e:
        logger.opt(exception=True).error(
            "[risk_manager._check_category_circuit_breaker] {}: {}",
            type(e).__name__, e,
        )
        return None
