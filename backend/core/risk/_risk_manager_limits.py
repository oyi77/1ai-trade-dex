"""RiskManager limits mixin — allocation, confidence, floors, concentration."""

from __future__ import annotations

import json
import time
from contextlib import nullcontext
from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple

from sqlalchemy import func, or_

from loguru import logger

from backend.config import settings
from backend.db.utils import get_db_session
from backend.models.database import Trade, BotState, for_update
from backend.monitoring.hft_metrics import record_signal, db_query_duration
from backend.monitoring.metrics import increment_risk_rejection
from backend.core.risk.correlation_monitor import CorrelationMonitor

from backend.core.risk._risk_manager_types import (
    RiskDecision,
    EdgeFilterError,
    DrawdownStatus,
    IMMUTABLE_SAFETY_RULES,
    _not_backfill_settlement_source,
)



class RiskManagerLimitsMixin:
    """Mixin — method implementations live on RiskManager."""

    def _count_enabled_strategies(self, db, mode: Optional[str] = None) -> Optional[int]:
        """Count the number of enabled strategies in StrategyConfig."""
        try:
            from backend.models.database import StrategyConfig

            query = db.query(StrategyConfig).filter(StrategyConfig.enabled.is_(True))
            if mode:
                query = query.filter(StrategyConfig.mode == mode)
            enabled_count = query.count()
            return int(enabled_count)
        except Exception as e:
            logger.opt(exception=True).error(
                "[risk_manager._count_enabled_strategies] {}: {}",
                type(e).__name__,
                e,
            )
            return None

    def _get_strategy_allocation(
        self, strategy_name: str, bankroll: float, db, mode: Optional[str] = None
    ) -> float:
        """Get strategy allocation using AGI allocation if available, otherwise equal-weight fallback."""
        # Check if AGI bankroll allocation is enabled
        if getattr(self.s, "AGI_BANKROLL_ALLOCATION_ENABLED", False):
            # Try to get AGI allocation from BotState.misc_data
            try:
                state = db.query(BotState).first()
                if state and state.misc_data:
                    misc = json.loads(state.misc_data)
                    allocations = misc.get("allocations", {})
                    if strategy_name in allocations:
                        allocation = float(allocations[strategy_name])
                        max_position = bankroll * float(
                            getattr(self.s, "MAX_POSITION_FRACTION", 0.25) or 0.25
                        )
                        return min(allocation, max_position)
            except Exception:
                logger.exception(
                    "[risk_manager._get_strategy_allocation] AGI allocation read failed"
                )

        # Fallback: equal-weight allocation
        enabled_count = self._count_enabled_strategies(db, mode)
        max_pos_frac = float(getattr(self.s, "MAX_POSITION_FRACTION", 0.25) or 0.25)
        if enabled_count is None or enabled_count == 0:
            # DB error or no enabled strategies - use MAX_POSITION_FRACTION as safe fallback
            if enabled_count is None:
                logger.warning(
                    "[risk_manager._get_strategy_allocation] DB error counting strategies, using MAX_POSITION_FRACTION fallback"
                )
            return bankroll * max_pos_frac

        # Calculate equal share
        max_total_frac = float(
            getattr(self.s, "MAX_TOTAL_EXPOSURE_FRACTION", 0.70) or 0.70
        )
        max_total_exposure = bankroll * max_total_frac
        equal_share = max_total_exposure / enabled_count

        # Cap at MAX_POSITION_FRACTION
        max_position = bankroll * max_pos_frac
        return min(equal_share, max_position)

    def _strategy_allocation_cap(
        self, strategy_name: str, db, mode: str
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
                "[risk_manager._strategy_allocation_cap] allocation lookup failed"
            )
            return None

    def _get_confidence_threshold(
        self, trading_mode: str, strategy_name: Optional[str] = None
    ) -> float:
        """Get confidence threshold for trade approval, respecting regime routing."""
        is_paper = (trading_mode or "").lower() in ("paper", "shadow")
        if is_paper:
            base_confidence = getattr(
                self.s,
                "PAPER_AUTO_APPROVE_MIN_CONFIDENCE",
                self.s.AUTO_APPROVE_MIN_CONFIDENCE,
            )
        else:
            base_confidence = getattr(
                self.s, "MIN_CONFIDENCE", self.s.AUTO_APPROVE_MIN_CONFIDENCE
            )

        if getattr(self.s, "REGIME_ROUTING_ENABLED", False):
            regime_multiplier = self._get_regime_multiplier(strategy_name)
            threshold = base_confidence * regime_multiplier
        else:
            threshold = base_confidence

        return min(threshold, 0.95)

    def check_drawdown_floors(
        self, bankroll: float, db=None, mode: Optional[str] = None
    ) -> Tuple[bool, Optional[str]]:
        """Check if daily/weekly loss floors have been breached.

        Args:
            bankroll: Current bankroll amount
            db: Database session (optional)
            mode: Trading mode (optional)

        Returns:
            Tuple of (floor_breached, action_taken) where action_taken describes what happened
        """
        owns_db = db is None
        ctx = get_db_session() if owns_db else nullcontext(db)
        try:
            with ctx as db:
                effective_mode = mode or self.s.TRADING_MODE
                now = datetime.now(timezone.utc)
                day_start = now - timedelta(hours=24)
                week_start = now - timedelta(days=7)

                # Calculate daily and weekly PnL
                daily_pnl = (
                    db.query(
                        func.coalesce(
                            func.sum(func.coalesce(Trade.pnl, -Trade.size)), 0.0
                        )
                    )
                    .filter(
                        Trade.settled.is_(True),
                        Trade.settlement_time >= day_start,
                        Trade.trading_mode == effective_mode,
                        _not_backfill_settlement_source(),
                    )
                    .scalar()
                    or 0.0
                )

                weekly_pnl = (
                    db.query(
                        func.coalesce(
                            func.sum(func.coalesce(Trade.pnl, -Trade.size)), 0.0
                        )
                    )
                    .filter(
                        Trade.settled.is_(True),
                        Trade.settlement_time >= week_start,
                        Trade.trading_mode == effective_mode,
                        _not_backfill_settlement_source(),
                    )
                    .scalar()
                    or 0.0
                )

                # Use the higher of current bankroll or effective initial bankroll
                effective_initial = self.s.INITIAL_BANKROLL
                if db is not None:
                    state = db.query(BotState).filter_by(mode=effective_mode).first()
                    if state is not None:
                        if (
                            effective_mode == "paper"
                            and state.paper_initial_bankroll is not None
                        ):
                            effective_initial = float(state.paper_initial_bankroll)
                        elif (
                            effective_mode == "testnet"
                            and state.testnet_initial_bankroll is not None
                        ):
                            effective_initial = float(state.testnet_initial_bankroll)
                base_bankroll = max(bankroll, effective_initial)

                # Check daily loss floor
                daily_floor = base_bankroll * self.s.DAILY_LOSS_FLOOR_PCT
                if daily_pnl < daily_floor:
                    # Pause all strategies for 24 hours
                    pause_until = now + timedelta(hours=24)

                    # Store pause timestamp in BotState.misc_data
                    if db is not None:
                        state = for_update(
                            db, db.query(BotState).filter_by(mode=effective_mode)
                        ).first()
                        if state is None:
                            state = BotState(mode=effective_mode, misc_data={})
                            db.add(state)

                        state.misc_data = state.misc_data or {}
                        state.misc_data["pause_until"] = pause_until.isoformat()
                        db.commit()

                    # Emit SSE event
                    self._publish_event(
                        "daily_loss_floor_triggered",
                        {
                            "bankroll": bankroll,
                            "daily_pnl": daily_pnl,
                            "daily_floor_pct": self.s.DAILY_LOSS_FLOOR_PCT,
                            "daily_floor_amount": daily_floor,
                            "pause_until": pause_until.isoformat(),
                            "action": "all_strategies_paused",
                        },
                    )

                    return True, "all_strategies_paused_24h"

                # Check weekly loss floor
                weekly_floor = base_bankroll * self.s.WEEKLY_LOSS_FLOOR_PCT
                if weekly_pnl < weekly_floor:
                    # Revert to PAPER mode for 7 days
                    paper_until = now + timedelta(days=7)

                    # Store paper mode timestamp in BotState.misc_data
                    if db is not None:
                        state = for_update(
                            db, db.query(BotState).filter_by(mode=effective_mode)
                        ).first()
                        if state is None:
                            state = BotState(mode=effective_mode, misc_data={})
                            db.add(state)

                        state.misc_data = state.misc_data or {}
                        state.misc_data["paper_until"] = paper_until.isoformat()
                        db.commit()

                    # Emit SSE event
                    self._publish_event(
                        "weekly_loss_floor_triggered",
                        {
                            "bankroll": bankroll,
                            "weekly_pnl": weekly_pnl,
                            "weekly_floor_pct": self.s.WEEKLY_LOSS_FLOOR_PCT,
                            "weekly_floor_amount": weekly_floor,
                            "paper_until": paper_until.isoformat(),
                            "action": "reverted_to_paper_mode",
                        },
                    )

                    return True, "reverted_to_paper_mode_7d"

                return False, None

        except Exception as e:
            logger.opt(exception=True).error(
                "[risk_manager.check_drawdown_floors] {}: {}",
                type(e).__name__,
                e,
            )
            return False, f"error_during_floor_check: {type(e).__name__}"
        finally:
            if owns_db:
                db.close()

    def _publish_event(self, event_type: str, payload: dict):
        """Publish SSE event via event bus."""
        try:
            from backend.core.event_bus import publish_event

            publish_event(event_type, payload)
        except ImportError:
            logger.warning(
                f"[risk_manager] Event bus not available, skipping SSE event: {event_type}"
            )
        except Exception as e:
            logger.opt(exception=True).error(
                "[risk_manager._publish_event] {}: {}",
                type(e).__name__,
                e,
            )

    def _check_strategy_drawdown(
        self, strategy_name: str, db, mode: str
    ) -> Optional[float]:
        """Return total PnL for a strategy in the last 24h (negative = loss), or None on error."""
        try:
            now = datetime.now(timezone.utc)
            day_start = now - timedelta(hours=24)
            pnl = (
                db.query(
                    func.coalesce(func.sum(func.coalesce(Trade.pnl, 0.0)), 0.0)
                )
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
                type(e).__name__,
                e,
            )
            return None

    def check_concentration(
        self, market_ticker: str, trade_size: float, bankroll: float, db, mode: str
    ) -> Optional[str]:
        """G-18: Block if total exposure to same event exceeds MAX_CONCENTRATION_PCT of bankroll."""
        try:
            profile_pct = getattr(self.s, "MAX_CONCENTRATION_PCT", 0.30) or 0.30
            max_concentration_pct = float(profile_pct) if bankroll >= 500 else 1.0
            logger.debug(
                f"[risk_manager.check_concentration] Checking ticker={market_ticker} size=${trade_size:.2f} "
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
                "[risk_manager.check_concentration] {}: {}",
                type(e).__name__,
                e,
            )
            return None

