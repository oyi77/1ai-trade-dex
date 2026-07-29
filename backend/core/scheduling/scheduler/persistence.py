# persistence.py — extracted from scheduler.py
"""Scheduler sub-module: persistence."""

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from backend.core.position_monitor import (
    sell_signal_monitor_job,
    SELL_MONITOR_INTERVAL_MINUTES,
)
from backend.core.scheduling.scheduling_strategies import (
    scan_and_trade_job,
    weather_scan_and_trade_job,
    settlement_job,
    news_feed_scan_job,
    arbitrage_scan_job,
    auto_trader_job,
    auto_redeem_job,
    heartbeat_job,
    strategy_cycle_job,
    sync_testnet_wallet,
    sync_live_wallet,
    verify_settlement_blockchain,
    market_universe_scan_job,
    position_monitor_job,
)
from backend.core.strategy_evolution_loop import strategy_evolution_loop
from backend.core.wallet_reconciler import wallet_reconciler_job
from backend.models.database import ScheduledJob, Trade
from loguru import logger

from .state import _scheduler_state_lock

JOB_FUNCTION_REGISTRY = {
    "settlement_job": settlement_job,
    "heartbeat_job": heartbeat_job,
    "scan_and_trade_job": scan_and_trade_job,
    "weather_scan_and_trade_job": weather_scan_and_trade_job,
    "news_feed_scan_job": news_feed_scan_job,
    "arbitrage_scan_job": arbitrage_scan_job,
    "auto_trader_job": auto_trader_job,
    "auto_redeem_job": auto_redeem_job,
    "strategy_cycle_job": strategy_cycle_job,
    "sync_testnet_wallet": sync_testnet_wallet,
    "sync_live_wallet": sync_live_wallet,
    "verify_settlement_blockchain": verify_settlement_blockchain,
    "market_universe_scan_job": market_universe_scan_job,
    "position_monitor_job": position_monitor_job,
    "sell_signal_monitor_job": sell_signal_monitor_job,
    "strategy_evolution_loop": strategy_evolution_loop,
    "wallet_reconciler_job": wallet_reconciler_job,
}

def _serialize_trigger(trigger) -> dict:
    if isinstance(trigger, IntervalTrigger):
        interval = getattr(trigger, "interval", None)
        seconds = int(interval.total_seconds()) if interval is not None else None
        return {"type": "interval", "seconds": seconds}
    return {"type": "unknown", "repr": repr(trigger)}

def save_scheduler_state(
    job_id: str,
    func_name: str,
    trigger,
    kwargs: dict | None,
    max_instances: int = 1,
    misfire_grace_time: int | None = None,
    next_run_time=None,
) -> None:
    """Persist a single scheduled job's registration metadata to DB."""
    try:
        from backend.db.utils import get_db_session

        state = {
            "func_name": func_name,
            "trigger": _serialize_trigger(trigger),
            "kwargs": kwargs or {},
            "max_instances": max_instances,
            "misfire_grace_time": misfire_grace_time,
        }
        with get_db_session() as db:
            row = db.query(ScheduledJob).filter(ScheduledJob.job_name == job_id).first()
            if row is None:
                row = ScheduledJob(
                    job_name=job_id,
                    job_state_json=state,
                    next_run=next_run_time,
                    enabled=True,
                )
                db.add(row)
            else:
                row.job_state_json = state
                row.next_run = next_run_time
                row.enabled = True
    except Exception as exc:
        logger.warning(f"Failed to persist scheduled job '{job_id}': {exc}")

def _persist_and_add_job(
    sched: AsyncIOScheduler,
    func,
    trigger,
    *,
    id: str,
    kwargs: dict | None = None,
    replace_existing: bool = True,
    max_instances: int = 1,
    misfire_grace_time: int | None = None,
):
    """Persist the job's registration to DB then register it with APScheduler."""
    func_name = getattr(func, "__name__", str(func))
    save_scheduler_state(
        job_id=id,
        func_name=func_name,
        trigger=trigger,
        kwargs=kwargs,
        max_instances=max_instances,
        misfire_grace_time=misfire_grace_time,
    )
    add_kwargs: dict = {
        "id": id,
        "replace_existing": replace_existing,
        "max_instances": max_instances,
    }
    if kwargs is not None:
        add_kwargs["kwargs"] = kwargs
    if misfire_grace_time is not None:
        add_kwargs["misfire_grace_time"] = misfire_grace_time
    return sched.add_job(func, trigger, **add_kwargs)

def load_scheduler_state(sched: AsyncIOScheduler) -> int:
    """Reload all enabled persisted jobs into the scheduler. Returns count restored."""
    restored = 0
    try:
        from backend.models.database import SessionLocal  # noqa: F401
        from backend.db.utils import get_db_session

        with get_db_session() as db:
            rows = (
                db.query(ScheduledJob).filter(ScheduledJob.enabled.is_(True)).all()
            )  # noqa: E712
            for row in rows:
                state = row.job_state_json or {}
                func_name = state.get("func_name")
                func = JOB_FUNCTION_REGISTRY.get(func_name)
                if func is None:
                    logger.debug(
                        f"Skipping persisted job '{row.job_name}': func '{func_name}' not registered"
                    )
                    continue
                trig_state = state.get("trigger") or {}
                if (
                    trig_state.get("type") != "interval"
                    or trig_state.get("seconds") is None
                ):
                    continue
                trigger = IntervalTrigger(seconds=int(trig_state["seconds"]))
                add_kwargs = {
                    "id": row.job_name,
                    "replace_existing": True,
                    "max_instances": int(state.get("max_instances", 1)),
                }
                if state.get("kwargs"):
                    add_kwargs["kwargs"] = state["kwargs"]
                grace = state.get("misfire_grace_time")
                if grace is not None:
                    add_kwargs["misfire_grace_time"] = int(grace)
                try:
                    with _scheduler_state_lock:
                        sched.add_job(func, trigger, **add_kwargs)
                    restored += 1
                except Exception as exc:
                    logger.warning(f"Failed to restore job '{row.job_name}': {exc}")
    except Exception as exc:
        logger.warning(f"load_scheduler_state failed: {exc}")
    return restored