"""
Strategy allocation — per-strategy capital allocation, budget tracking, remaining capacity.
"""

from typing import Optional, Tuple
import json
from loguru import logger

from backend.config import settings
from backend.db.utils import get_db_session
from backend.models.database import BotState, StrategyConfig, Trade
from sqlalchemy import func


def _count_enabled_strategies(db, mode: Optional[str] = None) -> Optional[int]:
    """Count the number of enabled strategies in StrategyConfig."""
    try:
        query = db.query(StrategyConfig).filter(StrategyConfig.enabled.is_(True))
        if mode:
            query = query.filter(StrategyConfig.mode == mode)
        enabled_count = query.count()
        return int(enabled_count)
    except Exception as e:
        logger.opt(exception=True).error(
            "[risk.allocation._count_enabled_strategies] {}: {}",
            type(e).__name__,
            e,
        )
        return None


def _get_strategy_allocation(
    strategy_name: str, bankroll: float, db, mode: Optional[str] = None
) -> float:
    """Get strategy allocation using AGI allocation if available, otherwise equal-weight fallback."""
    # Check if AGI bankroll allocation is enabled
    if getattr(settings, "AGI_BANKROLL_ALLOCATION_ENABLED", False):
        # Try to get AGI allocation from BotState.misc_data
        try:
            state = db.query(BotState).first()
            if state and state.misc_data:
                misc = json.loads(state.misc_data)
                allocations = misc.get("allocations", {})
                if strategy_name in allocations:
                    allocation = float(allocations[strategy_name])
                    max_position = bankroll * float(
                        getattr(settings, "MAX_POSITION_FRACTION", 0.25) or 0.25
                    )
                    return min(allocation, max_position)
        except Exception:
            logger.exception(
                "[risk.allocation._get_strategy_allocation] AGI allocation read failed"
            )

    # Fallback: equal-weight allocation
    enabled_count = _count_enabled_strategies(db, mode)
    max_pos_frac = float(getattr(settings, "MAX_POSITION_FRACTION", 0.25) or 0.25)
    if enabled_count is None or enabled_count == 0:
        # DB error or no enabled strategies - use MAX_POSITION_FRACTION as safe fallback
        if enabled_count is None:
            logger.warning(
                "[risk.allocation._get_strategy_allocation] DB error counting strategies, using MAX_POSITION_FRACTION fallback"
            )
        return bankroll * max_pos_frac

    # Calculate equal share
    max_total_frac = float(
        getattr(settings, "MAX_TOTAL_EXPOSURE_FRACTION", 0.70) or 0.70
    )
    max_total_exposure = bankroll * max_total_frac
    equal_share = max_total_exposure / enabled_count

    # Cap at MAX_POSITION_FRACTION
    max_position = bankroll * max_pos_frac
    return min(equal_share, max_position)


def _strategy_allocation_cap(
    strategy_name: str, db, mode: str
) -> Optional[float]:
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
            "[risk.allocation._strategy_allocation_cap] allocation lookup failed"
        )
        return None


def _validate_trade_strategy_allocation(
    strategy_name: Optional[str],
    adjusted: float,
    max_capacity: float,
    bankroll: float,
    db,
    effective_mode: str,
) -> Tuple[float, float, Optional[str]]:
    """Per-strategy allocation check. Returns (adjusted_size, max_capacity, rejection_reason)."""
    if strategy_name and db is not None:
        strategy_allocation = _get_strategy_allocation(
            strategy_name, bankroll, db, effective_mode
        )
        # Check remaining budget (total allocation minus open exposure)
        remaining_cap = _strategy_allocation_cap(strategy_name, db, effective_mode)
        if remaining_cap is not None and remaining_cap <= 0:
            from backend.monitoring.metrics import increment_risk_rejection
            from backend.monitoring.hft_metrics import record_signal

            record_signal(
                strategy=strategy_name, signal_type="rejected_allocation_exhausted"
            )
            increment_risk_rejection(
                strategy=strategy_name, reason="allocation_exhausted"
            )
            return adjusted, 0.0, f"allocation exhausted for {strategy_name}"
        effective_cap = (
            remaining_cap if remaining_cap is not None else strategy_allocation
        )
        # Use the tighter of strategy allocation and remaining budget
        adjusted = min(adjusted, effective_cap)
        max_capacity = min(max_capacity, effective_cap)
        logger.info(
            f"[risk.allocation] Strategy {strategy_name} allocation: ${strategy_allocation:.2f}, "
            f"remaining: ${effective_cap:.2f}, adjusted size: ${adjusted:.2f}"
        )
    return adjusted, max_capacity, None