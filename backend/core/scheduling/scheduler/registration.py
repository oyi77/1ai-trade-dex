# registration.py — extracted from scheduler.py
"""Scheduler sub-module: registration."""

from apscheduler.triggers.interval import IntervalTrigger
from backend.config import settings
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
from backend.models.database import ScheduledJob, Trade
from datetime import datetime, timedelta, timezone
from loguru import logger

from .state import _get_scheduler

def schedule_strategy(
    strategy_name: str, interval_seconds: int, mode: str = "paper"
) -> None:
    """Add or replace a strategy's APScheduler job for a specific mode.

    Args:
        strategy_name: Name of the strategy to schedule.
        interval_seconds: Interval between job executions.
        mode: Trading mode ("paper", "testnet", or "live").
    """
    import random

    sched = _get_scheduler()
    if sched is None or not sched.running:
        return

    from backend.config import settings

    # Floor: strategies don't need sub-30s reaction (market data changes slowly)
    MIN_STRATEGY_INTERVAL = 30
    if interval_seconds < MIN_STRATEGY_INTERVAL:
        logger.warning(
            f"Strategy {strategy_name} interval {interval_seconds}s below floor "
            f"{MIN_STRATEGY_INTERVAL}s — clamping"
        )
        interval_seconds = MIN_STRATEGY_INTERVAL

    profile_interval = getattr(settings, "ORCHESTRATOR_STRATEGY_INTERVAL_SECONDS", None)
    if profile_interval is not None and profile_interval < interval_seconds:
        logger.warning(
            f"Risk profile overriding strategy {strategy_name} interval: "
            f"{interval_seconds}s → {profile_interval}s"
        )
        interval_seconds = max(profile_interval, MIN_STRATEGY_INTERVAL)

    job_id = f"{mode}_{strategy_name}_{interval_seconds}"
    # misfire_grace_time must be generous for long-interval strategies (e.g. 300s, 600s)
    # so that a small scheduler delay doesn't permanently skip the run.
    grace = max(60, interval_seconds // 2)
    # Stagger first execution by 0-60s to prevent all strategies from hitting DB simultaneously
    jitter = random.randint(0, 60)
    next_run = datetime.now(timezone.utc) + timedelta(seconds=jitter)
    sched.add_job(
        strategy_cycle_job,
        IntervalTrigger(seconds=interval_seconds),
        kwargs={"strategy_name": strategy_name, "mode": mode},
        id=job_id,
        replace_existing=True,
        max_instances=5,
        misfire_grace_time=grace,
        next_run_time=next_run,
    )
    logger.info(
        f"Scheduled strategy {strategy_name} for mode {mode} every {interval_seconds}s (job_id={job_id})"
    )

def unschedule_strategy(
    strategy_name: str, mode: str = "paper", interval_seconds: int = 60
) -> None:
    """Remove a strategy's APScheduler job for a specific mode."""
    sched = _get_scheduler()
    if sched is None or not sched.running:
        return
    job_id = f"{mode}_{strategy_name}_{interval_seconds}"
    try:
        sched.remove_job(job_id)
        logger.info(f"Unscheduled strategy {strategy_name} for mode {mode}")
    except Exception:
        logger.exception(
            f"Failed to unschedule strategy {strategy_name} for mode {mode}"
        )

def get_scheduler_jobs() -> list[dict]:
    """Return current scheduled jobs info."""
    sched = _get_scheduler()
    if sched is None or not sched.running:
        return []
    return [
        {
            "id": job.id,
            "next_run": job.next_run_time.isoformat() if job.next_run_time else None,
            "trigger": str(job.trigger),
        }
        for job in sched.get_jobs()
    ]

def _load_strategy_jobs() -> None:
    """Read StrategyConfig table and schedule enabled strategies for all modes."""
    import backend.strategies  # noqa: F401 — triggers __init__.py auto-registration
    from backend.models.database import SessionLocal, StrategyConfig  # noqa: F401
    from backend.db.utils import get_db_session
    from backend.core.mode_context import list_contexts

    with get_db_session() as db:
        contexts = list_contexts()
        for mode in contexts.keys():
            configs = (
                db.query(StrategyConfig)
                .filter(StrategyConfig.enabled.is_(True))
                .filter(
                    (StrategyConfig.trading_mode == mode)
                    | (StrategyConfig.trading_mode.is_(None))
                )
                .all()
            )
            for cfg in configs:
                schedule_strategy(cfg.strategy_name, cfg.interval_seconds or 60, mode)

    # Register WS-driven strategies with event bus
    _register_event_driven_strategies()

def _register_event_driven_strategies() -> None:
    """Register strategies that support WS events with the event bus."""
    import backend.strategies  # noqa: F401 — triggers __init__.py auto-registration
    from backend.strategies.registry import STRATEGY_REGISTRY
    from backend.core.event_bus import event_bus
    from backend.core.ws_fallback import WsFirstExecutor

    for name, strategy_cls in STRATEGY_REGISTRY.items():
        try:
            strategy = strategy_cls()
            tokens = getattr(strategy, "subscribed_tokens", set())
            events = getattr(strategy, "subscribed_events", {"last_trade_price"})

            if not tokens:
                continue

            executor = WsFirstExecutor(name)
            event_bus.subscribe_strategy(
                strategy_name=name,
                token_ids=tokens,
                event_types=events,
                handler=strategy.on_market_event,
                fallback_handler=executor.on_ws_disconnected,
            )
            logger.info(
                f"EventBus: registered '{name}' with {len(tokens)} tokens, {len(events)} event types"
            )
        except Exception as e:
            logger.warning(f"Failed to register strategy {name} for event bus: {e}")

def _job_executed_listener(event):
    """Update ScheduledJob.last_run after each job completes."""
    job_id = event.job_id
    try:
        from backend.db.utils import get_db_session

        with get_db_session() as db:
            row = db.query(ScheduledJob).filter(ScheduledJob.job_name == job_id).first()
            if row:
                row.last_run = datetime.now(timezone.utc)
                sched = _get_scheduler()
                if sched:
                    job = sched.get_job(job_id)
                    if job and job.next_run_time:
                        row.next_run = job.next_run_time
                db.commit()
    except Exception as exc:
        logger.debug(f"Failed to update last_run for job '{job_id}': {exc}")