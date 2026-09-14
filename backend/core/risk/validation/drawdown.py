"""
Drawdown checking — daily/weekly PnL, loss floors, and breaker logic.
"""

from contextlib import nullcontext
from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple

from backend.config import settings
from backend.db.utils import get_db_session
from backend.models.database import BotState, Trade, for_update
from backend.monitoring.hft_metrics import db_query_duration
from backend.monitoring.metrics import increment_risk_rejection
from ..models import DrawdownStatus, _not_backfill_settlement_source


def check_drawdown(
    bankroll: float, db=None, mode: Optional[str] = None
) -> DrawdownStatus:
    owns_db = db is None
    ctx = get_db_session() if owns_db else nullcontext(db)
    try:
        with ctx as db:
            effective_mode = mode or settings.TRADING_MODE
            now = datetime.now(timezone.utc)
            day_start = now - timedelta(hours=24)
            week_start = now - timedelta(days=7)

            import time

            _qstart = time.monotonic()
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
            try:
                db_query_duration.labels(query_type="daily_pnl").observe(
                    time.monotonic() - _qstart
                )
            except Exception:
                logger.exception("[risk.drawdown] failed to observe db_query_duration")

            _qstart = time.monotonic()
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
            try:
                db_query_duration.labels(query_type="weekly_pnl").observe(
                    time.monotonic() - _qstart
                )
            except Exception:
                logger.exception("[risk.drawdown] failed to observe db_query_duration")

            # Use the higher of current bankroll or effective initial bankroll to prevent
            # death spiral: depleted bankroll → tiny limit → can't trade → can't recover.
            # Reads DB-backed initial (which includes top-ups) when available.
            effective_initial = settings.INITIAL_BANKROLL
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
            daily_limit = base_bankroll * settings.DAILY_DRAWDOWN_LIMIT_PCT
            weekly_limit = base_bankroll * settings.WEEKLY_DRAWDOWN_LIMIT_PCT

            breach_reason = ""
            is_breached = False

            if daily_pnl <= -daily_limit:
                is_breached = True
                breach_reason = f"24h loss ${abs(daily_pnl):.2f} exceeds {settings.DAILY_DRAWDOWN_LIMIT_PCT * 100:.0f}% limit (${daily_limit:.2f})"
            elif weekly_pnl <= -weekly_limit:
                is_breached = True
                breach_reason = f"7d loss ${abs(weekly_pnl):.2f} exceeds {settings.WEEKLY_DRAWDOWN_LIMIT_PCT * 100:.0f}% limit (${weekly_limit:.2f})"

            return DrawdownStatus(
                daily_pnl=daily_pnl,
                weekly_pnl=weekly_pnl,
                daily_limit_pct=settings.DAILY_DRAWDOWN_LIMIT_PCT,
                weekly_limit_pct=settings.WEEKLY_DRAWDOWN_LIMIT_PCT,
                is_breached=is_breached,
                breach_reason=breach_reason,
            )
    except Exception as e:
        logger.opt(exception=True).error(
            "[risk.drawdown.check_drawdown] {}: {}",
            type(e).__name__,
            e,
        )
        return DrawdownStatus(
            0.0,
            0.0,
            settings.DAILY_DRAWDOWN_LIMIT_PCT,
            settings.WEEKLY_DRAWDOWN_LIMIT_PCT,
            True,
            "DB error during drawdown check",
        )
    finally:
        if owns_db:
            db.close()


def _daily_loss_exceeded(db=None, mode: Optional[str] = None) -> bool:
    owns_db = db is None
    ctx = get_db_session() if owns_db else nullcontext(db)
    try:
        with ctx as db:
            effective_mode = mode or settings.TRADING_MODE
            now = datetime.now(timezone.utc)
            today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
            import time

            _qstart = time.monotonic()
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
            try:
                db_query_duration.labels(query_type="daily_loss_pnl").observe(
                    time.monotonic() - _qstart
                )
            except Exception:
                logger.exception("[risk.drawdown] failed to observe db_query_duration")
            # Percentage-based daily loss limit: scales with bankroll.
            # Falls back to flat DAILY_LOSS_LIMIT if DAILY_LOSS_LIMIT_PCT is not set.
            daily_loss_limit_pct = getattr(settings, "DAILY_LOSS_LIMIT_PCT", None)
            if daily_loss_limit_pct:
                bankroll = _get_bankroll(db, effective_mode)
                daily_limit = bankroll * daily_loss_limit_pct
            else:
                daily_limit = settings.DAILY_LOSS_LIMIT
            return daily_pnl <= -daily_limit
    except Exception as e:
        logger.opt(exception=True).error(
            "[risk.drawdown._daily_loss_exceeded] {}: {}",
            type(e).__name__,
            e,
        )
        return True
    finally:
        if owns_db:
            db.close()


def _get_bankroll(db, mode: str) -> float:
    import time

    _qstart = time.monotonic()
    state = db.query(BotState).filter_by(mode=mode).first()
    try:
        db_query_duration.labels(query_type="get_bankroll").observe(
            time.monotonic() - _qstart
        )
    except Exception:
        logger.exception("[risk.drawdown.get_bankroll] failed to observe db_query_duration")
    if state and state.bankroll is not None:
        return float(state.bankroll)
    return settings.INITIAL_BANKROLL


def check_drawdown_floors(
    bankroll: float, db=None, mode: Optional[str] = None
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
            effective_mode = mode or settings.TRADING_MODE
            now = datetime.now(timezone.utc)
            day_start = now - timedelta(hours=24)
            week_start = now - timedelta(days=7)

            # Calculate daily and weekly PnL
            import time

            _qstart = time.monotonic()
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
            try:
                db_query_duration.labels(query_type="floor_daily_pnl").observe(
                    time.monotonic() - _qstart
                )
            except Exception:
                logger.exception("[risk.drawdown.floors] failed to observe db_query_duration")

            _qstart = time.monotonic()
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
            try:
                db_query_duration.labels(query_type="floor_weekly_pnl").observe(
                    time.monotonic() - _qstart
                )
            except Exception:
                logger.exception("[risk.drawdown.floors] failed to observe db_query_duration")

            # Use the higher of current bankroll or effective initial bankroll
            effective_initial = settings.INITIAL_BANKROLL
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
            daily_floor = base_bankroll * settings.DAILY_LOSS_FLOOR_PCT
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
                _publish_event(
                    "daily_loss_floor_triggered",
                    {
                        "bankroll": bankroll,
                        "daily_pnl": daily_pnl,
                        "daily_floor_pct": settings.DAILY_LOSS_FLOOR_PCT,
                        "daily_floor_amount": daily_floor,
                        "pause_until": pause_until.isoformat(),
                        "action": "all_strategies_paused",
                    },
                )

                return True, "all_strategies_paused_24h"

            # Check weekly loss floor
            weekly_floor = base_bankroll * settings.WEEKLY_LOSS_FLOOR_PCT
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
                _publish_event(
                    "weekly_loss_floor_triggered",
                    {
                        "bankroll": bankroll,
                        "weekly_pnl": weekly_pnl,
                        "weekly_floor_pct": settings.WEEKLY_LOSS_FLOOR_PCT,
                        "weekly_floor_amount": weekly_floor,
                        "paper_until": paper_until.isoformat(),
                        "action": "reverted_to_paper_mode",
                    },
                )

                return True, "reverted_to_paper_mode_7d"

            return False, None

    except Exception as e:
        logger.opt(exception=True).error(
            "[risk.drawdown.check_drawdown_floors] {}: {}",
            type(e).__name__,
            e,
        )
        return False, f"error_during_floor_check: {type(e).__name__}"
    finally:
        if owns_db:
            db.close()


def _publish_event(event_type: str, payload: dict):
    """Publish SSE event via event bus."""
    try:
        from backend.core.event_bus import publish_event

        publish_event(event_type, payload)
    except ImportError:
        logger.warning(
            f"[risk.drawdown] Event bus not available, skipping SSE event: {event_type}"
        )
    except Exception as e:
        logger.opt(exception=True).error(
            "[risk.drawdown._publish_event] {}: {}",
            type(e).__name__,
            e,
        )


from sqlalchemy import func