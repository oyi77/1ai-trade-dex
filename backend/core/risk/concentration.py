"""
Concentration and exposure limits — cross-market correlation, position sizing, max exposure.
"""

from typing import Optional, Tuple

from backend.config import settings
from backend.core.risk.correlation_monitor import CorrelationMonitor
from loguru import logger

from .models import _not_backfill_settlement_source


def _validate_trade_concentration(
    size: float,
    bankroll: float,
    current_exposure: float,
    market_ticker: Optional[str],
    db,
    effective_mode: str,
    strategy_name: Optional[str],
) -> Tuple[float, float, Optional[str]]:
    """Cross-market correlation check + concentration limits. Returns (adjusted_size, max_capacity, rejection_reason)."""
    # Cross-market correlation check — block if clustered exposure > 30% of bankroll
    if market_ticker and db is not None:
        corr_monitor = CorrelationMonitor(settings)
        corr_result = corr_monitor.check_correlation(
            bankroll=bankroll,
            market_ticker=market_ticker,
            trade_size=size,
            event_slug=None,  # market_ticker is a string; event_slug must be passed separately
            db=db,
            mode=effective_mode,
        )
        if not corr_result.allowed:
            from backend.monitoring.metrics import increment_risk_rejection
            from backend.monitoring.hft_metrics import record_signal

            record_signal(
                strategy=strategy_name or "unknown",
                signal_type="rejected_correlation",
            )
            increment_risk_rejection(
                strategy=strategy_name or "unknown", reason="correlation"
            )
            return 0.0, 0.0, corr_result.reason

    # Live bankroll = PM portfolio value (includes locked positions);
    # available cash = portfolio minus open exposure.
    if effective_mode == "live":
        available_cash = max(0.0, bankroll - current_exposure)
        max_position = available_cash * settings.MAX_POSITION_FRACTION
    else:
        max_position = bankroll * settings.MAX_POSITION_FRACTION
    max_capacity = max_position
    adjusted = min(size, max_position)

    # Global max trade size ceiling (immutable safety rule)
    adjusted = min(adjusted, settings.MAX_TRADE_SIZE)
    max_capacity = min(max_capacity, settings.MAX_TRADE_SIZE)

    # Paper/testnet bankroll is available cash because entry execution
    # deducts stake immediately; total exposure limits must use equity
    # (cash + already-open stake), otherwise existing positions shrink the
    # denominator and can permanently block new trades. Live bankroll is
    # PM portfolio value, which already includes locked positions.
    exposure_base = (
        bankroll if effective_mode == "live" else bankroll + current_exposure
    )
    # Use immutable safety rule for max total exposure
    from .models import IMMUTABLE_SAFETY_RULES

    max_exposure = exposure_base * IMMUTABLE_SAFETY_RULES["max_total_exposure"]["default"]
    exposure_room = max(0.0, max_exposure - current_exposure)
    max_capacity = min(max_capacity, exposure_room)
    if current_exposure + adjusted > max_exposure:
        adjusted = exposure_room
        if adjusted <= 0:
            from backend.monitoring.metrics import increment_risk_rejection
            from backend.monitoring.hft_metrics import record_signal

            record_signal(
                strategy=strategy_name or "unknown", signal_type="rejected_exposure"
            )
            increment_risk_rejection(
                strategy=strategy_name or "unknown", reason="exposure"
            )
            return 0.0, 0.0, "max exposure reached"

    return adjusted, max_capacity, None


def check_concentration(
    market_ticker: str,
    trade_size: float,
    bankroll: float,
    db,
    mode: str,
    category: Optional[str] = None,
    size: Optional[float] = None,
) -> Optional[str]:
    """G-18: Block if total exposure to same event exceeds MAX_CONCENTRATION_PCT of bankroll."""
    try:
        profile_pct = getattr(settings, "MAX_CONCENTRATION_PCT", 0.30) or 0.30
        max_concentration_pct = float(profile_pct) if bankroll >= 500 else 1.0
        logger.debug(
            f"[risk.concentration] Checking ticker={market_ticker} size=${trade_size:.2f} "
            f"against dynamic concentration limit={max_concentration_pct:.0%} of bankroll (${bankroll:.2f})"
        )
        # Get event_slug for this market to group by event
        from backend.models.database import Trade as T

        event_slug = None
        existing = (
            db.query(T.event_slug)
            .filter(
                T.market_ticker == market_ticker,
                T.settled.is_(False),
                T.trading_mode == mode,
            )
            .first()
        )
        if existing and existing[0]:
            event_slug = existing[0]

        if event_slug:
            event_exposure = (
                db.query(func.coalesce(func.sum(T.size), 0.0))
                .filter(
                    T.event_slug == event_slug,
                    T.settled.is_(False),
                    T.trading_mode == mode,
                )
                .scalar()
                or 0.0
            )
        else:
            event_exposure = (
                db.query(func.coalesce(func.sum(T.size), 0.0))
                .filter(
                    T.market_ticker == market_ticker,
                    T.settled.is_(False),
                    T.trading_mode == mode,
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
            "[risk.concentration.check_concentration] {}: {}",
            type(e).__name__,
            e,
        )
        return None


from sqlalchemy import func