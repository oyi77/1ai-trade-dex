"""
APEX-specific pre-trade risk evaluation.
"""

from typing import Optional

from .models import RiskDecision


def evaluate_apex_signal(signal, ctx) -> RiskDecision:
    """APEX-specific pre-trade risk evaluation.

    Checks edge freshness, confidence gate, position limits,
    correlation, drawdown, and bankroll sizing.
    """
    from backend.core.edge.edge_model import Signal

    if not isinstance(signal, Signal):
        return RiskDecision(
            allowed=False,
            reason=f"apex: invalid signal type {type(signal)}",
            adjusted_size=0.0,
        )

    # 1. Edge freshness — reject expired edges
    for edge in signal.source_edges:
        if edge.is_expired:
            return RiskDecision(
                allowed=False,
                reason=f"apex: edge expired for {signal.market_id}",
                adjusted_size=0.0,
            )

    # 2. Confidence gate
    min_confidence = float(getattr(settings, "APEX_MIN_CONFIDENCE", 0.3))
    if signal.confidence < min_confidence:
        return RiskDecision(
            allowed=False,
            reason=f"apex: confidence {signal.confidence:.2f} < {min_confidence}",
            adjusted_size=0.0,
        )

    # 3. Position limits
    max_concurrent = int(getattr(settings, "APEX_MAX_CONCURRENT", 5))
    try:
        from backend.models.database import Trade

        open_count = (
            ctx.db.query(Trade)
            .filter(
                Trade.settled.is_(False),
                Trade.trading_mode == ctx.mode,
                Trade.strategy == "apex",
            )
            .count()
        )
        if open_count >= max_concurrent:
            return RiskDecision(
                allowed=False,
                reason=f"apex: {open_count} positions >= max {max_concurrent}",
                adjusted_size=0.0,
            )
    except Exception:
        logger.warning("[apex:risk] Could not check concurrent positions, allowing through")

    # 4. Drawdown check
    mode = ctx.mode or getattr(settings, "TRADING_MODE", "paper")
    from .drawdown import _daily_loss_exceeded

    if _daily_loss_exceeded(db=ctx.db, mode=mode):
        return RiskDecision(
            allowed=False,
            reason="apex: daily loss limit exceeded",
            adjusted_size=0.0,
        )

    # 5. Bankroll sizing — adjust size based on current bankroll
    from .drawdown import _get_bankroll

    bankroll = _get_bankroll(ctx.db, mode)
    max_pct = float(getattr(settings, "APEX_BANKROLL_PCT", 0.08))
    adjusted_size = min(signal.size_usd, bankroll * max_pct)
    adjusted_size = max(adjusted_size, float(getattr(settings, "MIN_ORDER_USDC", 1.0)))

    # 6. Correlation check
    try:
        category = signal.metadata.get("category", "unknown")
        from .concentration import check_concentration

        check_result = check_concentration(
            market_ticker=signal.market_id,
            category=category,
            db=ctx.db,
            mode=mode,
            size=adjusted_size,
            bankroll=bankroll,
        )
        if check_result:
            logger.warning(f"[apex:risk] Concentration check: {check_result}")
            return RiskDecision(
                allowed=False,
                reason=f"apex: concentration limit — {check_result}",
                adjusted_size=0.0,
            )
    except Exception:
        logger.warning("[apex:risk] Could not check concentration limits, allowing through")

    return RiskDecision(
        allowed=True,
        reason="apex: all risk checks passed",
        adjusted_size=adjusted_size,
    )