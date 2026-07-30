"""
Drawdown and loss validation — daily/weekly PnL checks and circuit breakers.
"""
from datetime import datetime, timedelta, timezone
from typing import Optional

from contextlib import nullcontext
from loguru import logger
from sqlalchemy import func

from backend.config import settings as default_settings
from backend.db.utils import get_db_session
from backend.models.database import BotState, Trade, for_update
from backend.monitoring.hft_metrics import record_signal
from backend.monitoring.metrics import increment_risk_rejection
from backend.core.risk.models import DrawdownStatus


def _not_backfill_settlement_source():
    from sqlalchemy import or_
    return or_(
        Trade.settlement_source.is_(None),
        ~Trade.settlement_source.op("LIKE")("backfill_%"),
    )


def get_bankroll(settings_obj, db, mode: str) -> float:
    """Fetch current bankroll for the given trading mode."""
    import time
    _qstart = time.monotonic()
    state = db.query(BotState).filter_by(mode=mode).first()
    try:
        from backend.monitoring.hft_metrics import db_query_duration
        db_query_duration.labels(query_type="get_bankroll").observe(
            time.monotonic() - _qstart
        )
    except Exception:
        logger.exception(
            "[risk_manager.get_bankroll] failed to observe db_query_duration metric"
        )
    if state and state.bankroll is not None:
        return float(state.bankroll)
    return settings_obj.INITIAL_BANKROLL


def check_drawdown(
    settings_obj,
    bankroll: float,
    db=None,
    mode: Optional[str] = None,
) -> DrawdownStatus:
    """Check current drawdown status against daily and weekly limits."""
    owns_db = db is None
    ctx = get_db_session() if owns_db else nullcontext(db)
    try:
        with ctx as db:
            effective_mode = mode or settings_obj.TRADING_MODE
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
            # death spiral: depleted bankroll -> tiny limit -> can't trade -> can't recover.
            effective_initial = settings_obj.INITIAL_BANKROLL
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
            daily_limit = base_bankroll * settings_obj.DAILY_DRAWDOWN_LIMIT_PCT
            weekly_limit = base_bankroll * settings_obj.WEEKLY_DRAWDOWN_LIMIT_PCT

            breach_reason = ""
            is_breached = False
            if daily_pnl <= -daily_limit:
                is_breached = True
                breach_reason = (
                    f"24h loss ${abs(daily_pnl):.2f} exceeds "
                    f"{settings_obj.DAILY_DRAWDOWN_LIMIT_PCT * 100:.0f}% limit (${daily_limit:.2f})"
                )
            elif weekly_pnl <= -weekly_limit:
                is_breached = True
                breach_reason = (
                    f"7d loss ${abs(weekly_pnl):.2f} exceeds "
                    f"{settings_obj.WEEKLY_DRAWDOWN_LIMIT_PCT * 100:.0f}% limit (${weekly_limit:.2f})"
                )

            return DrawdownStatus(
                daily_pnl=daily_pnl,
                weekly_pnl=weekly_pnl,
                daily_limit_pct=settings_obj.DAILY_DRAWDOWN_LIMIT_PCT,
                weekly_limit_pct=settings_obj.WEEKLY_DRAWDOWN_LIMIT_PCT,
                is_breached=is_breached,
                breach_reason=breach_reason,
            )
    except Exception as e:
        logger.opt(exception=True).error(
            "[risk_manager.check_drawdown] {}: {}",
            type(e).__name__, e,
        )
        return DrawdownStatus(
            0.0, 0.0,
            settings_obj.DAILY_DRAWDOWN_LIMIT_PCT,
            settings_obj.WEEKLY_DRAWDOWN_LIMIT_PCT,
            True,
            "DB error during drawdown check",
        )
    finally:
        if owns_db:
            db.close()


def daily_loss_exceeded(settings_obj, db=None, mode: Optional[str] = None) -> bool:
    """Check if daily loss limit has been exceeded (percentage or flat)."""
    owns_db = db is None
    ctx = get_db_session() if owns_db else nullcontext(db)
    try:
        with ctx as db:
            effective_mode = mode or settings_obj.TRADING_MODE
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
            daily_loss_limit_pct = getattr(settings_obj, "DAILY_LOSS_LIMIT_PCT", None)
            if daily_loss_limit_pct:
                bankroll = get_bankroll(settings_obj, db, effective_mode)
                daily_limit = bankroll * daily_loss_limit_pct
            else:
                daily_limit = settings_obj.DAILY_LOSS_LIMIT
            return daily_pnl <= -daily_limit
    except Exception as e:
        logger.opt(exception=True).error(
            "[risk_manager._daily_loss_exceeded] {}: {}",
            type(e).__name__, e,
        )
        return True
    finally:
        if owns_db:
            db.close()


def check_drawdown_floors(
    settings_obj,
    bankroll: float,
    db=None,
    mode: Optional[str] = None,
    publish_event_fn=None,
) -> tuple:
    """Check if daily/weekly loss floors have been breached.

    Returns (floor_breached, action_taken) tuple.
    """
    owns_db = db is None
    ctx = get_db_session() if owns_db else nullcontext(db)
    try:
        with ctx as db:
            effective_mode = mode or settings_obj.TRADING_MODE
            now = datetime.now(timezone.utc)
            day_start = now - timedelta(hours=24)
            week_start = now - timedelta(days=7)

            daily_pnl = (
                db.query(
                    func.coalesce(func.sum(func.coalesce(Trade.pnl, -Trade.size)), 0.0)
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
                    func.coalesce(func.sum(func.coalesce(Trade.pnl, -Trade.size)), 0.0)
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

            effective_initial = settings_obj.INITIAL_BANKROLL
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

            daily_floor = base_bankroll * settings_obj.DAILY_LOSS_FLOOR_PCT
            if daily_pnl < daily_floor:
                pause_until = now + timedelta(hours=24)
                action = _store_loss_floor_action(
                    db, effective_mode, "pause_until", pause_until
                )
                if publish_event_fn:
                    publish_event_fn(
                        "daily_loss_floor_triggered",
                        {
                            "bankroll": bankroll,
                            "daily_pnl": daily_pnl,
                            "daily_floor_pct": settings_obj.DAILY_LOSS_FLOOR_PCT,
                            "daily_floor_amount": daily_floor,
                            "pause_until": pause_until.isoformat(),
                            "action": "all_strategies_paused",
                        },
                    )
                return True, action

            weekly_floor = base_bankroll * settings_obj.WEEKLY_LOSS_FLOOR_PCT
            if weekly_pnl < weekly_floor:
                paper_until = now + timedelta(days=7)
                action = _store_loss_floor_action(
                    db, effective_mode, "paper_until", paper_until
                )
                if publish_event_fn:
                    publish_event_fn(
                        "weekly_loss_floor_triggered",
                        {
                            "bankroll": bankroll,
                            "weekly_pnl": weekly_pnl,
                            "weekly_floor_pct": settings_obj.WEEKLY_LOSS_FLOOR_PCT,
                            "weekly_floor_amount": weekly_floor,
                            "paper_until": paper_until.isoformat(),
                            "action": "reverted_to_paper_mode",
                        },
                    )
                return True, action

            return False, None

    except Exception as e:
        logger.opt(exception=True).error(
            "[risk_manager.check_drawdown_floors] {}: {}",
            type(e).__name__, e,
        )
        return False, f"error_during_floor_check: {type(e).__name__}"
    finally:
        if owns_db:
            db.close()


def _store_loss_floor_action(
    db, effective_mode: str, key: str, value
) -> str:
    """Store loss floor action in BotState.misc_data."""
    action_map = {
        "pause_until": "all_strategies_paused_24h",
        "paper_until": "reverted_to_paper_mode_7d",
    }
    try:
        state = for_update(
            db, db.query(BotState).filter_by(mode=effective_mode)
        ).first()
        if state is None:
            state = BotState(mode=effective_mode, misc_data={})
            db.add(state)
        state.misc_data = state.misc_data or {}
        state.misc_data[key] = value.isoformat()
        db.commit()
    except Exception as e:
        logger.error(f"[risk_manager] Failed to store {key}: {e}")
    return action_map.get(key, "unknown_action")
