"""
Strategy allocation and position sizing — per-strategy budget and confidence thresholds.
"""
import json
from typing import Optional

from loguru import logger
from sqlalchemy import func

from backend.models.database import BotState, StrategyConfig, Trade


def count_enabled_strategies(db, mode: Optional[str] = None) -> Optional[int]:
    """Count the number of enabled strategies in StrategyConfig."""
    try:
        query = db.query(StrategyConfig).filter(StrategyConfig.enabled.is_(True))
        if mode:
            query = query.filter(StrategyConfig.mode == mode)
        return int(query.count())
    except Exception as e:
        logger.opt(exception=True).error(
            "[risk_manager._count_enabled_strategies] {}: {}", type(e).__name__, e,
        )
        return None


def get_strategy_allocation(
    settings_obj,
    strategy_name: str,
    bankroll: float,
    db,
    mode: Optional[str] = None,
) -> float:
    """Get strategy allocation using AGI allocation if available, else equal-weight fallback."""
    import json
    from backend.models.database import BotState

    # Check if AGI bankroll allocation is enabled
    if getattr(settings_obj, "AGI_BANKROLL_ALLOCATION_ENABLED", False):
        try:
            state = db.query(BotState).first()
            if state and state.misc_data:
                misc = json.loads(state.misc_data)
                allocations = misc.get("allocations", {})
                if strategy_name in allocations:
                    allocation = float(allocations[strategy_name])
                    max_position = bankroll * float(
                        getattr(settings_obj, "MAX_POSITION_FRACTION", 0.25) or 0.25
                    )
                    return min(allocation, max_position)
        except Exception:
            logger.exception(
                "[risk_manager._get_strategy_allocation] AGI allocation read failed"
            )

    # Fallback: equal-weight allocation
    enabled_count = count_enabled_strategies(db, mode)
    max_pos_frac = float(getattr(settings_obj, "MAX_POSITION_FRACTION", 0.25) or 0.25)
    if enabled_count is None or enabled_count == 0:
        if enabled_count is None:
            logger.warning(
                "[risk_manager._get_strategy_allocation] DB error counting strategies, using MAX_POSITION_FRACTION fallback"
            )
        return bankroll * max_pos_frac

    max_total_frac = float(getattr(settings_obj, "MAX_TOTAL_EXPOSURE_FRACTION", 0.70) or 0.70)
    max_total_exposure = bankroll * max_total_frac
    equal_share = max_total_exposure / enabled_count
    max_position = bankroll * max_pos_frac
    return min(equal_share, max_position)


def strategy_allocation_cap(strategy_name: str, db, mode: str) -> Optional[float]:
    """Return remaining allocation budget for a strategy, or None if no allocation exists."""
    try:
        state = db.query(BotState).first()
        if not state or not state.misc_data:
            return None
        misc = json.loads(state.misc_data)
        allocations = misc.get("allocations", {})
        if strategy_name not in allocations:
            return None
        total_budget = float(allocations[strategy_name])
        strategy_exposure = (
            db.query(func.coalesce(func.sum(Trade.size), 0.0))
            .filter(
                Trade.strategy == strategy_name,
                Trade.settled.is_(False),
                Trade.trading_mode == mode,
            )
            .scalar()
            or 0.0
        )
        remaining = total_budget - float(strategy_exposure)
        return max(0.0, remaining)
    except Exception:
        logger.exception(
            "[risk_manager._strategy_allocation_cap] allocation lookup failed"
        )
        return None


def get_confidence_threshold(
    settings_obj, trading_mode: str, strategy_name: Optional[str] = None
) -> float:
    """Get confidence threshold for trade approval, respecting regime routing."""
    is_paper = (trading_mode or "").lower() in ("paper", "shadow")
    if is_paper:
        base_confidence = getattr(
            settings_obj,
            "PAPER_AUTO_APPROVE_MIN_CONFIDENCE",
            settings_obj.AUTO_APPROVE_MIN_CONFIDENCE,
        )
    else:
        base_confidence = getattr(
            settings_obj, "MIN_CONFIDENCE", settings_obj.AUTO_APPROVE_MIN_CONFIDENCE
        )

    if getattr(settings_obj, "REGIME_ROUTING_ENABLED", False):
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
        return 1.0


def check_strategy_drawdown(
    settings_obj, strategy_name: str, db, mode: str
) -> Optional[float]:
    """Return total PnL for a strategy in the last 24h (negative = loss), or None on error."""
    try:
        from datetime import datetime, timedelta, timezone
        now = datetime.now(timezone.utc)
        day_start = now - timedelta(hours=24)
        pnl = (
            db.query(func.coalesce(func.sum(func.coalesce(Trade.pnl, 0.0)), 0.0))
            .filter(
                Trade.strategy == strategy_name,
                Trade.settled.is_(True),
                Trade.settlement_time >= day_start,
                Trade.trading_mode == mode,
                _not_backfill_settlement_source(),
            )
            .scalar()
            or 0.0
        )
        return float(pnl)
    except Exception as e:
        logger.opt(exception=True).error(
            "[risk_manager._check_strategy_drawdown] {}: {}",
            type(e).__name__, e,
        )
        return None


def _not_backfill_settlement_source():
    from sqlalchemy import or_
    return or_(
        Trade.settlement_source.is_(None),
        ~Trade.settlement_source.op("LIKE")("backfill_%"),
    )
