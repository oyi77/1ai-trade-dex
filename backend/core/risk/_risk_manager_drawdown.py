"""RiskManager drawdown mixin — drawdown, daily-loss, side-lock."""

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



class RiskManagerDrawdownMixin:
    """Mixin — method implementations live on RiskManager."""

    def check_drawdown(
        self, bankroll: float, db=None, mode: Optional[str] = None
    ) -> DrawdownStatus:
        owns_db = db is None
        ctx = get_db_session() if owns_db else nullcontext(db)
        try:
            with ctx as db:
                effective_mode = mode or self.s.TRADING_MODE
                now = datetime.now(timezone.utc)
                day_start = now - timedelta(hours=24)
                week_start = now - timedelta(days=7)

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

                # Use the higher of current bankroll or effective initial bankroll to prevent
                # death spiral: depleted bankroll → tiny limit → can't trade → can't recover.
                # Reads DB-backed initial (which includes top-ups) when available.
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
                daily_limit = base_bankroll * self.s.DAILY_DRAWDOWN_LIMIT_PCT
                weekly_limit = base_bankroll * self.s.WEEKLY_DRAWDOWN_LIMIT_PCT

                breach_reason = ""
                is_breached = False

                if daily_pnl <= -daily_limit:
                    is_breached = True
                    breach_reason = f"24h loss ${abs(daily_pnl):.2f} exceeds {self.s.DAILY_DRAWDOWN_LIMIT_PCT * 100:.0f}% limit (${daily_limit:.2f})"
                elif weekly_pnl <= -weekly_limit:
                    is_breached = True
                    breach_reason = f"7d loss ${abs(weekly_pnl):.2f} exceeds {self.s.WEEKLY_DRAWDOWN_LIMIT_PCT * 100:.0f}% limit (${weekly_limit:.2f})"

                return DrawdownStatus(
                    daily_pnl=daily_pnl,
                    weekly_pnl=weekly_pnl,
                    daily_limit_pct=self.s.DAILY_DRAWDOWN_LIMIT_PCT,
                    weekly_limit_pct=self.s.WEEKLY_DRAWDOWN_LIMIT_PCT,
                    is_breached=is_breached,
                    breach_reason=breach_reason,
                )
        except Exception as e:
            logger.opt(exception=True).error(
                "[risk_manager.check_drawdown] {}: {}",
                type(e).__name__,
                e,
            )
            return DrawdownStatus(
                0.0,
                0.0,
                self.s.DAILY_DRAWDOWN_LIMIT_PCT,
                self.s.WEEKLY_DRAWDOWN_LIMIT_PCT,
                True,
                "DB error during drawdown check",
            )
        finally:
            if owns_db:
                db.close()

    def _daily_loss_exceeded(self, db=None, mode: Optional[str] = None) -> bool:
        owns_db = db is None
        ctx = get_db_session() if owns_db else nullcontext(db)
        try:
            with ctx as db:
                effective_mode = mode or self.s.TRADING_MODE
                now = datetime.now(timezone.utc)
                today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
                daily_pnl = (
                    db.query(
                        func.coalesce(
                            func.sum(func.coalesce(Trade.pnl, -Trade.size)), 0.0
                        )
                    )
                    .filter(
                        Trade.settled.is_(True),
                        Trade.timestamp >= today_start,
                        Trade.trading_mode == effective_mode,
                        _not_backfill_settlement_source(),
                    )
                    .scalar()
                    or 0.0
                )
                # Percentage-based daily loss limit: scales with bankroll.
                # Falls back to flat DAILY_LOSS_LIMIT if DAILY_LOSS_LIMIT_PCT is not set.
                daily_loss_limit_pct = getattr(self.s, "DAILY_LOSS_LIMIT_PCT", None)
                if daily_loss_limit_pct:
                    bankroll = self._get_bankroll(db, effective_mode)
                    daily_limit = bankroll * daily_loss_limit_pct
                else:
                    daily_limit = self.s.DAILY_LOSS_LIMIT
                return daily_pnl <= -daily_limit
        except Exception as e:
            logger.opt(exception=True).error(
                "[risk_manager._daily_loss_exceeded] {}: {}",
                type(e).__name__,
                e,
            )
            return True
        finally:
            if owns_db:
                db.close()

    def check_side_lock(
        self, market_ticker: str, direction: str, db=None, mode: Optional[str] = None
    ) -> Optional[str]:
        """Returns the conflicting side if an opposing-side, unsettled trade exists for the given market.
        Returns None if no side-lock is present.
        """
        from backend.models.database import Trade

        owns_db = db is None
        ctx = get_db_session() if owns_db else nullcontext(db)
        try:
            with ctx as db:
                effective_mode = mode or self.s.TRADING_MODE
                # Opposing side: if direction is 'YES', look for 'NO', and vice versa
                side_field = getattr(Trade, "side", None) or getattr(
                    Trade, "direction", None
                )
                # Attempt both 'YES/NO' and 'BUY/SELL' as supported
                side_yes = [
                    s for s in ["YES", "BUY"] if direction.upper().startswith(s[:1])
                ]
                if side_yes:
                    opp_sides = ["NO", "SELL"]
                else:
                    opp_sides = ["YES", "BUY"]
                conflict = (
                    db.query(Trade)
                    .filter(
                        Trade.market_ticker == market_ticker,
                        Trade.settled.is_(False),
                        Trade.trading_mode == effective_mode,
                        side_field.in_(opp_sides),
                    )
                    .first()
                )
                if conflict is not None:
                    return getattr(
                        conflict, "side", getattr(conflict, "direction", None)
                    )
                return None
        except Exception as e:
            logger.opt(exception=True).error(
                "[risk_manager.check_side_lock] {}: {}",
                type(e).__name__,
                e,
            )
            return "error"
        finally:
            if owns_db:
                db.close()

    def _has_unsettled_trade(
        self,
        market_ticker: str,
        db=None,
        mode: Optional[str] = None,
        direction: Optional[str] = None,
        strategy_name: Optional[str] = None,
    ) -> bool:
        owns_db = db is None
        ctx = get_db_session() if owns_db else nullcontext(db)
        try:
            with ctx as db:
                effective_mode = mode or self.s.TRADING_MODE
                query = db.query(func.count(Trade.id)).filter(
                    Trade.market_ticker == market_ticker,
                    Trade.settled.is_(False),
                    Trade.trading_mode == effective_mode,
                )
                if strategy_name:
                    query = query.filter(Trade.strategy == strategy_name)
                # Per-direction check: YES and NO positions can coexist on the same market
                if direction is not None:
                    query = query.filter(Trade.direction == direction)
                count = query.scalar() or 0
                return count > 0
        except Exception as e:
            logger.opt(exception=True).error(
                "[risk_manager._has_unsettled_trade] {}: {}",
                type(e).__name__,
                e,
            )
            return True
        finally:
            if owns_db:
                db.close()

