"""Heartbeat and watchdog — in-memory cache, batch-flushed to DB by watchdog."""

import asyncio
import json
import os
import threading
from datetime import datetime, timezone, timedelta

from sqlalchemy import text
from sqlalchemy.exc import OperationalError

from backend.models.database import BotState, SessionLocal, StrategyConfig

from loguru import logger
HEARTBEAT_PREFIX = "heartbeat:"
_recent_alerts: dict[str, datetime] = {}  # strategy_name -> last_alert_time
ALERT_DEDUP_WINDOW = timedelta(minutes=5)

# In-memory heartbeat cache: strategy_name -> ISO timestamp
_pending_heartbeats: dict[str, str] = {}
_hb_lock = threading.Lock()


def _is_lock_timeout_error(exc: Exception) -> bool:
    """Return True for PostgreSQL lock-timeout / lock-not-available failures."""

    if isinstance(exc, OperationalError):
        orig = getattr(exc, "orig", None)
        pgcode = getattr(orig, "pgcode", None)
        if pgcode == "55P03":
            return True

    message = str(exc).lower()
    return (
        "lock timeout" in message
        or "locknotavailable" in message
        or "could not obtain lock" in message
        or "canceling statement due to lock timeout" in message
    )


def update_heartbeat(strategy_name: str) -> None:
    """Record heartbeat in memory — no DB write (watchdog flushes batch)."""
    ts = datetime.now(timezone.utc).isoformat()
    with _hb_lock:
        _pending_heartbeats[strategy_name] = ts

    # Refresh external liveness immediately from real strategy activity so the
    # guardian reflects event-loop health even when the DB heartbeat flush is
    # delayed by BotState lock contention.
    _touch_heartbeat_file()


def _flush_heartbeats() -> bool:
    """Write all pending heartbeats to DB in a single transaction.

    Uses atomic jsonb_set() for PostgreSQL to avoid lock contention.
    Falls back to SQLAlchemy ORM for SQLite.
    """
    from backend.config import settings
    with _hb_lock:
        if not _pending_heartbeats:
            return True
        snapshot = dict(_pending_heartbeats)

    db = SessionLocal()
    try:
        # Postgres: use atomic jsonb_set to avoid read-modify-write deadlocks
        if settings.is_postgres:
            db.execute(text("SET LOCAL lock_timeout = '2s'"))
            db.execute(text("SET LOCAL statement_timeout = '5s'"))
            acquired = db.execute(
                text("SELECT pg_try_advisory_xact_lock(hashtext('polyedge_heartbeat_flush'))")
            ).scalar()
            if not acquired:
                db.rollback()
                logger.debug("heartbeat flush skipped: another flusher is active")
                return False

            heartbeat_patch = json.dumps(
                {
                    f"{HEARTBEAT_PREFIX}{strategy_name}": ts
                for strategy_name, ts in snapshot.items()
                }
            )
            heartbeat_stmt = text(
                "UPDATE bot_state "
                "SET misc_data = COALESCE(misc_data::jsonb, '{}'::jsonb) || CAST(:heartbeat_patch AS jsonb) "
                "WHERE mode = :mode"
            )
            for mode in settings.active_modes_set:
                db.execute(
                    heartbeat_stmt,
                    {"heartbeat_patch": heartbeat_patch, "mode": mode},
                )
            db.commit()
        else:
            for state in db.query(BotState).all():
                data = {}
                if state.misc_data:
                    try:
                        data = json.loads(state.misc_data) if isinstance(state.misc_data, str) else state.misc_data
                    except Exception:
                        logger.exception(f"heartbeat: failed to parse misc_data JSON for mode {state.mode}")
                        data = {}
                for strategy_name, ts in snapshot.items():
                    data[f"{HEARTBEAT_PREFIX}{strategy_name}"] = ts
                state.misc_data = json.dumps(data)
            db.commit()
        with _hb_lock:
            for strategy_name, ts in snapshot.items():
                if _pending_heartbeats.get(strategy_name) == ts:
                    _pending_heartbeats.pop(strategy_name, None)
        return True
    except Exception as e:
        try:
            db.rollback()
        except Exception:
            logger.exception("heartbeat rollback failed after flush error")
        if _is_lock_timeout_error(e):
            logger.warning("heartbeat flush deferred due to BotState contention")
        else:
            logger.warning(f"heartbeat flush failed: {e}")
        return False
    finally:
        db.close()


def get_strategy_health(db) -> list[dict]:
    """
    Return health status for all enabled strategies.
    Each entry: {name, last_heartbeat, lag_seconds, healthy}
    """
    result = []
    try:
        configs = (
            db.query(StrategyConfig).filter(StrategyConfig.enabled.is_(True)).all()
        )
        from backend.config import settings
        all_data = {}
        for mode in settings.active_modes_set:
            state = db.query(BotState).filter_by(mode=mode).first()
            if state and state.misc_data:
                try:
                    mode_data = (
                        json.loads(state.misc_data)
                        if isinstance(state.misc_data, str)
                        else {}
                    )
                    all_data.update(mode_data)
                except Exception:
                    logger.warning(f"Failed to parse misc_data JSON for mode {mode}, skipping")

        now = datetime.now(timezone.utc)
        for cfg in configs:
            key = f"{HEARTBEAT_PREFIX}{cfg.strategy_name}"
            last_hb_str = all_data.get(key)
            last_hb = None
            lag = None
            healthy = False
            if last_hb_str:
                try:
                    last_hb = datetime.fromisoformat(last_hb_str)
                    if last_hb.tzinfo is None:
                        last_hb = last_hb.replace(tzinfo=timezone.utc)
                    lag = (now - last_hb).total_seconds()
                    # healthy = heartbeat within 2x the strategy interval
                    threshold = (cfg.interval_seconds or 60) * 2
                    healthy = lag < threshold
                except Exception:
                    logger.warning(
                        f"Failed to check heartbeat for strategy {cfg.strategy_name}"
                    )

            result.append(
                {
                    "name": cfg.strategy_name,
                    "last_heartbeat": last_hb_str,
                    "lag_seconds": round(lag, 1) if lag is not None else None,
                    "healthy": healthy,
                    "interval_seconds": cfg.interval_seconds or 60,
                }
            )
    except Exception as e:
        logger.error(f"get_strategy_health failed: {e}")
    return result


async def watchdog_job() -> None:
    """APScheduler watchdog — flush heartbeats, check for stale strategies.

    Also touches a heartbeat file for external liveness monitoring
    so PM2 or an external monitor can detect event-loop freezes.
    """
    from backend.core.decisions import record_decision

    # Touch heartbeat file for external liveness monitoring
    _touch_heartbeat_file()

    if not _flush_heartbeats():
        logger.warning("[WATCHDOG] Skipping stale heartbeat checks until heartbeat flush succeeds")
        return

    from backend.db.utils import get_db_session
    with get_db_session() as db:
        healths = get_strategy_health(db)
        for h in healths:
            if not h["healthy"] and h["lag_seconds"] is not None:
                threshold = max(h["interval_seconds"] * 4, 300)
                if h["lag_seconds"] > threshold:
                    logger.error(
                        f"[WATCHDOG] Strategy {h['name']} heartbeat stale: "
                        f"lag={h['lag_seconds']}s threshold={threshold}s"
                    )
                    record_decision(
                        db,
                        "watchdog",
                        h["name"],
                        "ERROR",
                        signal_data={
                            "lag_seconds": h["lag_seconds"],
                            "healthy": False,
                            "sources": ["heartbeat_watchdog"],
                        },
                        reason=f"Heartbeat stale: {h['lag_seconds']:.0f}s since last cycle",
                    )
                    db.commit()

                # Send Telegram alert if configured (with dedup window)
                try:
                    from backend.config import settings

                    if settings.TELEGRAM_BOT_TOKEN:
                        last_alert = _recent_alerts.get(h["name"])
                        now_dt = datetime.now(timezone.utc)
                        if last_alert and (now_dt - last_alert) < ALERT_DEDUP_WINDOW:
                            continue  # skip duplicate alert within 5 min window
                        _recent_alerts[h["name"]] = now_dt
                        _send_telegram_alert_sync(
                            f"⚠️ WATCHDOG: Strategy {h['name']} is silent "
                            f"({h['lag_seconds']:.0f}s since last heartbeat)"
                        )
                except Exception as te:
                    logger.debug(f"Watchdog Telegram alert failed: {te}")


def _send_telegram_alert_sync(message: str) -> None:
    """Fire-and-forget Telegram message (sync, for watchdog use).

    Runs in a thread to avoid blocking the event loop when Telegram API is slow.
    """
    from backend.config import settings

    token = settings.TELEGRAM_BOT_TOKEN
    if not token:
        return

    def _do_send():
        import httpx
        admin_ids = getattr(settings, "TELEGRAM_ADMIN_CHAT_IDS", "")
        try:
            with httpx.Client() as client:
                for chat_id in str(admin_ids).split(","):
                    chat_id = chat_id.strip()
                    if not chat_id:
                        continue
                    try:
                        client.post(
                            f"{settings.TELEGRAM_API_BASE}/bot{token}/sendMessage",
                            json={"chat_id": chat_id, "text": message},
                            timeout=5.0,
                        )
                    except Exception:
                        logger.warning("Failed to send Telegram heartbeat alert")
        except Exception as exc:
            logger.debug(f"Telegram alert thread failed: {exc}")

    import threading
    t = threading.Thread(target=_do_send, daemon=True)
    t.start()


async def wallet_sync_job() -> None:
    """
    APScheduler job — fetches live CLOB wallet balance and persists to bot_state.
    Syncs ALL modes that need real wallet balance (live, testnet).
    """
    from backend.config import settings
    from backend.models.database import StrategyConfig

    modes_to_sync = set()
    try:
        from backend.db.utils import get_db_session
        with get_db_session() as _db:
            configs = (
                _db.query(StrategyConfig).filter(StrategyConfig.enabled.is_(True)).all()
            )
            for cfg in configs:
                cfg_mode = cfg.trading_mode
                if cfg_mode in ("live", "testnet"):
                    modes_to_sync.add(cfg_mode)
    except asyncio.CancelledError:
        logger.info("wallet_sync_job cancelled during shutdown")
        return
    except Exception:
        logger.exception("wallet_sync_job: failed to query enabled strategy configs for wallet sync modes")

    for mode in settings.active_modes_set:
        if mode in ("live", "testnet"):
            modes_to_sync.add(mode)

    if not modes_to_sync:
        return

    for sync_mode in modes_to_sync:
        try:
            from backend.data.polymarket_clob import clob_from_settings

            clob = clob_from_settings(mode=sync_mode)
            async with clob:
                await asyncio.wait_for(clob.create_or_derive_api_key(), timeout=30.0)
                balance_data = await asyncio.wait_for(
                    clob.get_wallet_balance(),
                    timeout=30.0,
                )
                usdc_balance = balance_data.get("usdc_balance", 0.0)
                error = balance_data.get("error")

                if usdc_balance >= 0 and not error:
                    _sync_balance_to_db(usdc_balance, sync_mode)
                    logger.info(
                        f"wallet_sync: {sync_mode} balance = ${usdc_balance:.2f}"
                    )
        except asyncio.CancelledError:
            logger.info("wallet_sync_job cancelled during shutdown")
            return
        except Exception as e:
            logger.warning(f"wallet_sync_job ({sync_mode}) failed: {e}")


def _sync_balance_to_db(balance: float, mode: str) -> None:
    """Write wallet balance to bot_state DB row via SQLAlchemy."""
    if mode == "live":
        logger.debug(
            "wallet_sync: skipping live BotState.bankroll raw CLOB cash write; "
            "live bankroll is reconciled from PM portfolio value"
        )
        return

    from backend.db.utils import get_db_session

    try:
        with get_db_session() as db:
            state = db.query(BotState).filter(BotState.mode == mode).first()
            if state:
                state.bankroll = max(0.0, float(balance))
                db.commit()
                logger.debug(f"wallet_sync: {mode} balance updated to ${state.bankroll:.2f}")
    except Exception as e:
        logger.warning(f"wallet_sync: {mode} balance update failed: {e}")


HEARTBEAT_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), '.omc', 'bot-heartbeat.tmp')


def _touch_heartbeat_file() -> None:
    """Touch a heartbeat file for external liveness monitoring.

    An external monitor script can check this file's modification time.
    If older than a threshold (e.g., 2 min), the bot event loop is frozen
    and needs a force restart.
    """
    try:
        os.makedirs(os.path.dirname(HEARTBEAT_FILE), exist_ok=True)
        with open(HEARTBEAT_FILE, 'w') as f:
            f.write(datetime.now(timezone.utc).isoformat())
    except OSError:
        pass  # Non-critical — don't crash watchdog for a file write failure


async def liveness_file_job() -> None:
    """Lightweight external liveness tick.

    This job intentionally avoids DB work so guardian health reflects whether the
    event loop is alive, not whether BotState writes are contended.
    """
    _touch_heartbeat_file()
