"""Background scheduler for multi-strategy autonomous trading.

This module manages the APScheduler instance and scheduling configuration.
The actual job functions are in scheduling_strategies.py.
"""

import asyncio
import datetime as dt_module
import threading
from datetime import datetime, timedelta, timezone
from typing import List, Optional
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from loguru import logger

from backend.config import settings
from backend.job_queue.worker import Worker
from backend.job_queue.abstract import AbstractQueue, create_queue
from backend.core.task_manager import TaskManager

from backend.core.scheduling_strategies import (
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
from backend.core.position_monitor import (
    sell_signal_monitor_job,
    SELL_MONITOR_INTERVAL_MINUTES,
)
from backend.models.database import ScheduledJob, Trade
from backend.core.auto_improve import auto_improve_job
from backend.core.strategy_ranker import strategy_ranking_job
from backend.core.agi_jobs import (
    self_review_job,
    research_pipeline_job,
    agi_health_check_job,
    nightly_review_job,
    strategy_rehabilitation_job,
    historical_data_collection_job,
    forensics_integration_job,
    fronttest_validation_job,
    model_calibration_check_job,
)
from backend.core.db_backup import backup_job
from backend.core.cache_cleanup import cache_cleanup_job
from backend.core.autonomous_promoter import autonomous_promotion_job
from backend.core.bankroll_allocator import bankroll_allocation_job
from backend.core.agi_orchestrator import agi_improvement_cycle_job
from backend.core.shadow_validation import shadow_validation_job
from backend.application.agi.evolution_jobs import (
    run_crossover_cycle,
    rebalance_population,
    run_mutation_cycle,
    update_fitness_from_shadow,
    necromancy_analysis_job,
    full_population_review_job,
    legend_evaluation_job,
)
from backend.ai.training.train import run_training_pipeline
from backend.data.hf_dataset_collector import hf_dataset_collection_job
from backend.core.backtest_engine import EnhancedBacktestEngine, EnhancedBacktestConfig
from backend.mesh.auditor import audit_source_performance
from backend.mesh.learning import update_source_weights_from_outcomes
from backend.ai.rejection_learner import generate_rejection_proposals

scheduler: Optional[AsyncIOScheduler] = None

queue: Optional[AbstractQueue] = None
worker: Optional[Worker] = None
worker_task: Optional[asyncio.Task] = None
task_manager: Optional[TaskManager] = None

# Concurrency guard for scheduler state mutations (threading.Lock since start_scheduler is sync)
_scheduler_state_lock = threading.Lock()

# Event log for terminal display (in-memory, last 200 events)
event_log: List[dict] = []
MAX_LOG_SIZE = 200
_event_log_lock = threading.Lock()


def _register_evolution_jobs(target_scheduler) -> None:
    """Register evolution scheduler jobs using config-driven intervals."""
    target_scheduler.add_job(
        update_fitness_from_shadow,
        IntervalTrigger(hours=1),
        id="evolution_fitness_update",
        replace_existing=True,
        max_instances=1,
    )
    logger.info("Scheduled evolution fitness update job every 1 hour")

    target_scheduler.add_job(
        run_mutation_cycle,
        IntervalTrigger(hours=settings.AGI_MUTATION_INTERVAL_HOURS),
        id="evolution_mutation_cycle",
        replace_existing=True,
        max_instances=1,
    )
    logger.info(
        "Scheduled evolution mutation cycle job every %s hours",
        settings.AGI_MUTATION_INTERVAL_HOURS,
    )

    target_scheduler.add_job(
        run_crossover_cycle,
        IntervalTrigger(hours=settings.AGI_CROSSOVER_INTERVAL_HOURS),
        id="evolution_crossover_cycle",
        replace_existing=True,
        max_instances=1,
    )
    logger.info(
        "Scheduled evolution crossover cycle job every %s hours",
        settings.AGI_CROSSOVER_INTERVAL_HOURS,
    )

    target_scheduler.add_job(
        rebalance_population,
        IntervalTrigger(hours=settings.AGI_MUTATION_INTERVAL_HOURS),
        id="evolution_population_rebalance",
        replace_existing=True,
        max_instances=1,
    )
    logger.info(
        "Scheduled evolution population rebalance job every %s hours",
        settings.AGI_MUTATION_INTERVAL_HOURS,
    )


def log_event(event_type: str, message: str, data: dict = None):
    """Log an event for terminal display."""
    event = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "type": event_type,
        "message": message,
        "data": data or {},
    }
    with _event_log_lock:
        event_log.append(event)

        while len(event_log) > MAX_LOG_SIZE:
            event_log.pop(0)

    log_func = {
        "error": logger.error,
        "warning": logger.warning,
        "success": logger.info,
        "info": logger.info,
        "data": logger.debug,
        "trade": logger.info,
    }.get(event_type, logger.info)

    log_func(f"[{event_type.upper()}] {message}")


def get_recent_events(limit: int = 50) -> List[dict]:
    """Get recent events for terminal display."""
    with _event_log_lock:
        return list(event_log[-limit:])


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
}


def _serialize_trigger(trigger) -> dict:
    if isinstance(trigger, IntervalTrigger):
        interval = getattr(trigger, "interval", None)
        seconds = int(interval.total_seconds()) if interval is not None else None
        return {"type": "interval", "seconds": seconds}
    return {"type": "unknown", "repr": repr(trigger)}


def save_scheduler_state(job_id: str, func_name: str, trigger, kwargs: dict | None,
                         max_instances: int = 1, misfire_grace_time: int | None = None,
                         next_run_time=None) -> None:
    """Persist a single scheduled job's registration metadata to DB."""
    try:
        from backend.models.database import SessionLocal  # noqa: F401  (kept for compatibility)
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


def _persist_and_add_job(sched: AsyncIOScheduler, func, trigger, *, id: str,
                         kwargs: dict | None = None, replace_existing: bool = True,
                         max_instances: int = 1, misfire_grace_time: int | None = None):
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
            rows = db.query(ScheduledJob).filter(ScheduledJob.enabled == True).all()  # noqa: E712
            for row in rows:
                state = row.job_state_json or {}
                func_name = state.get("func_name")
                func = JOB_FUNCTION_REGISTRY.get(func_name)
                if func is None:
                    logger.debug(f"Skipping persisted job '{row.job_name}': func '{func_name}' not registered")
                    continue
                trig_state = state.get("trigger") or {}
                if trig_state.get("type") != "interval" or trig_state.get("seconds") is None:
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


def schedule_strategy(strategy_name: str, interval_seconds: int, mode: str = "paper") -> None:
    """Add or replace a strategy's APScheduler job for a specific mode.

    Args:
        strategy_name: Name of the strategy to schedule.
        interval_seconds: Interval between job executions.
        mode: Trading mode ("paper", "testnet", or "live").
    """
    import random
    global scheduler
    if scheduler is None or not scheduler.running:
        return

    job_id = f"{mode}_{strategy_name}_{interval_seconds}"
    # misfire_grace_time must be generous for long-interval strategies (e.g. 300s, 600s)
    # so that a small scheduler delay doesn't permanently skip the run.
    grace = max(60, interval_seconds // 2)
    # Stagger first execution by 0-60s to prevent all strategies from hitting DB simultaneously
    jitter = random.randint(0, 60)
    next_run = datetime.now(timezone.utc) + timedelta(seconds=jitter)
    scheduler.add_job(
        strategy_cycle_job,
        IntervalTrigger(seconds=interval_seconds),
        kwargs={"strategy_name": strategy_name, "mode": mode},
        id=job_id,
        replace_existing=True,
        max_instances=2,
        misfire_grace_time=grace,
        next_run_time=next_run,
    )
    logger.info(
        f"Scheduled strategy {strategy_name} for mode {mode} every {interval_seconds}s (job_id={job_id})"
    )


def unschedule_strategy(strategy_name: str, mode: str = "paper", interval_seconds: int = 60) -> None:
    """Remove a strategy's APScheduler job for a specific mode."""
    global scheduler
    if scheduler is None or not scheduler.running:
        return
    job_id = f"{mode}_{strategy_name}_{interval_seconds}"
    try:
        scheduler.remove_job(job_id)
        logger.info(f"Unscheduled strategy {strategy_name} for mode {mode}")
    except Exception:
        logger.exception(f"Failed to unschedule strategy {strategy_name} for mode {mode}")
        logger.warning(f"Failed to unschedule strategy {strategy_name} for mode {mode}")


def get_scheduler_jobs() -> list[dict]:
    """Return current scheduled jobs info."""
    global scheduler
    if scheduler is None or not scheduler.running:
        return []
    return [
        {
            "id": job.id,
            "next_run": job.next_run_time.isoformat() if job.next_run_time else None,
            "trigger": str(job.trigger),
        }
        for job in scheduler.get_jobs()
    ]


def _load_strategy_jobs() -> None:
    """Read StrategyConfig table and schedule enabled strategies for all modes."""
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
                    (StrategyConfig.trading_mode == mode) | (StrategyConfig.trading_mode.is_(None))
                )
                .all()
            )
            for cfg in configs:
                schedule_strategy(cfg.strategy_name, cfg.interval_seconds or 60, mode)

    # Register WS-driven strategies with event bus
    _register_event_driven_strategies()


def _register_event_driven_strategies() -> None:
    """Register strategies that support WS events with the event bus."""
    from backend.strategies.registry import STRATEGY_REGISTRY
    from backend.core.event_bus import event_bus
    from backend.core.ws_fallback import WsFirstExecutor

    logger.info("[DEBUG] _register_event_driven_strategies() starting")
    for name, strategy_cls in STRATEGY_REGISTRY.items():
        try:
            strategy = strategy_cls()
            tokens = getattr(strategy, "subscribed_tokens", set())
            events = getattr(strategy, "subscribed_events", {"last_trade_price"})
            logger.info(f"[DEBUG] Registering {name}: tokens={len(tokens)}, events={len(events)}")

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
            logger.info(f"EventBus: registered '{name}' with {len(tokens)} tokens, {len(events)} event types")
        except Exception as e:
            logger.warning(f"[DEBUG] Failed to register strategy {name} for event bus: {e}")
    logger.info("[DEBUG] _register_event_driven_strategies() completed")


def start_scheduler():
    """Start the background scheduler for multi-strategy trading."""
    global scheduler, queue, worker, worker_task

    if scheduler is not None and scheduler.running:
        log_event("warning", "Scheduler already running")
        return

    scheduler = AsyncIOScheduler()

# SCHED-5: Job Store Configuration
# The scheduler uses AsyncIOScheduler with the default MemoryJobStore.
# This means scheduled jobs are NOT persisted across restarts.
# Critical jobs (agi_health_check_job, nightly_review_job, strategy_rehabilitation_job)
# are re-registered from DATABASE configuration on each startup via load_persisted_jobs().
# If you need full persistence, uncomment the SQLAlchemyJobStore configuration below:
#
# from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
# from apscheduler.schedulers.asyncio import AsyncIOScheduler
# jobstores = {
#     'default': SQLAlchemyJobStore(engine=engine)  # where engine is SQLAlchemy engine
# }
# executors = {
#     'default': AsyncIOExecutor()
# }
# scheduler = AsyncIOScheduler(jobstores=jobstores, executors=executors)

    # Restore jobs from DB first
    try:
        jobs_restored = load_scheduler_state(scheduler)
        if jobs_restored:
            logger.info(f"Restored {jobs_restored} scheduled jobs from DB crash recovery.")
    except Exception as exc:
        logger.warning(f"Scheduler state restoration failed: {exc}")

    scan_seconds = settings.SCAN_INTERVAL_SECONDS
    settle_seconds = settings.SETTLEMENT_INTERVAL_SECONDS

    # Check settlements every 2 minutes
    _persist_and_add_job(
        scheduler,
        settlement_job,
        IntervalTrigger(seconds=settle_seconds),
        id="settlement_check",
        max_instances=1,
        replace_existing=True,
        misfire_grace_time=60,
    )

    # Heartbeat every minute
    _persist_and_add_job(
        scheduler,
        heartbeat_job,
        IntervalTrigger(minutes=1),
        id="heartbeat",
        max_instances=1,
        replace_existing=True,
    )

    if getattr(settings, "AUTO_REDEEM_ENABLED", False):
        auto_redeem_seconds = getattr(settings, "AUTO_REDEEM_INTERVAL_SECONDS", 3600)
        _persist_and_add_job(
            scheduler,
            auto_redeem_job,
            IntervalTrigger(seconds=auto_redeem_seconds),
            id="auto_redeem",
            replace_existing=True,
            max_instances=1,
            misfire_grace_time=60,
        )
        logger.info(
            f"Scheduled auto-redeem job every {auto_redeem_seconds}s "
            f"(dry_run={getattr(settings, 'AUTO_REDEEM_DRY_RUN', True)})"
        )

    from backend.core.mode_context import list_contexts
    contexts = list_contexts()
    modes = list(contexts.keys()) if contexts else ["paper", "testnet", "live"]

    for mode in modes:
        _persist_and_add_job(
            scheduler,
            scan_and_trade_job,
            IntervalTrigger(seconds=scan_seconds),
            kwargs={"mode": mode},
            id=f"{mode}_market_scan",
            replace_existing=True,
            max_instances=1,
            misfire_grace_time=60,
        )

    if getattr(settings, "WEATHER_ENABLED", True):
        weather_seconds = getattr(settings, "WEATHER_SCAN_INTERVAL_SECONDS", 600)
        for mode in modes:
            scheduler.add_job(
                weather_scan_and_trade_job,
                IntervalTrigger(seconds=weather_seconds),
                kwargs={"mode": mode},
                id=f"{mode}_weather_scan",
                replace_existing=True,
                max_instances=1,
                misfire_grace_time=120,
            )

    # Universe scanner: pre-fetch all markets across platforms into cache
    universe_ttl = getattr(settings, "MARKET_UNIVERSE_CACHE_TTL_SECONDS", 300)
    scheduler.add_job(
        market_universe_scan_job,
        IntervalTrigger(seconds=universe_ttl),
        id="market_universe_scan",
        replace_existing=True,
        max_instances=1,
        misfire_grace_time=60,
    )

    # Position monitor: scan for stale positions every 30 minutes
    _persist_and_add_job(
        scheduler,
        position_monitor_job,
        IntervalTrigger(minutes=30, jitter=300),
        id="position_monitor",
        replace_existing=True,
        max_instances=1,
        misfire_grace_time=300,
    )

    # Sell signal monitor: scan open positions for sell triggers every 5 minutes
    _persist_and_add_job(
        scheduler,
        sell_signal_monitor_job,
        IntervalTrigger(minutes=SELL_MONITOR_INTERVAL_MINUTES, jitter=60),
        id="sell_signal_monitor",
        replace_existing=True,
        max_instances=1,
        misfire_grace_time=120,
    )

    # AGI self-tuning: periodic review of all strategies every 30 minutes
    from backend.core.agi_self_tuner import get_agi_self_tuner
    agi_self_tune_interval = getattr(settings, "AGI_SELF_TUNE_INTERVAL_MINUTES", 30)
    scheduler.add_job(
        get_agi_self_tuner().periodic_review,
        IntervalTrigger(minutes=agi_self_tune_interval, jitter=120),
        id="agi_self_tune",
        name="AGI Self-Tuning Review",
        replace_existing=True,
        max_instances=1,
        misfire_grace_time=300,
    )
    logger.info(f"Scheduled AGI self-tuning review every {agi_self_tune_interval} minutes")

    # Watchdog: check strategy heartbeats every 30s
    from backend.core.heartbeat import watchdog_job, wallet_sync_job, liveness_file_job

    scheduler.add_job(
        liveness_file_job,
        IntervalTrigger(seconds=20),
        id="liveness_file",
        replace_existing=True,
        max_instances=1,
        next_run_time=dt_module.datetime.now(dt_module.timezone.utc) + dt_module.timedelta(seconds=5),
    )

    scheduler.add_job(
        watchdog_job,
        IntervalTrigger(seconds=30),
        id="watchdog",
        replace_existing=True,
        max_instances=1,
        next_run_time=dt_module.datetime.now(dt_module.timezone.utc) + dt_module.timedelta(seconds=5),
    )

    # Wallet balance sync: fetch live CLOB balance every 60s
    _persist_and_add_job(
        scheduler,
        wallet_sync_job,
        IntervalTrigger(seconds=60),
        id="wallet_sync",
        replace_existing=True,
        max_instances=1,
    )

    # Wallet sync disabled — contains blocking synchronous DB calls that freeze the event loop.
    # Re-enable after refactoring to use async DB (asyncpg/databases) or thread pool execution.
    # First, remove any restored wallet_sync_live job from crash recovery state.
    try:
        scheduler.remove_job("wallet_sync_live")
        logger.info("Removed wallet_sync_live job (blocking DB calls — disabled)")
    except Exception:
        logger.exception("Failed to remove wallet_sync_live job")
        # Job may not exist

    # Settlement verification disabled — contains blocking synchronous DB calls (.all() + loop)
    # that freeze the event loop for the duration of the query + resolution checks.
    # Re-enable after refactoring to use async DB (asyncpg/databases) or thread pool execution.
    # First, remove any restored settlement_verify job from crash recovery state.
    try:
        scheduler.remove_job("settlement_verify")
        logger.info("Removed settlement_verify job (blocking DB calls — disabled)")
    except Exception:
        logger.exception("Failed to remove settlement_verify job")
        # Job may not exist

    # Start OrderbookRouter as APScheduler fallback heartbeat
    if settings.POLYMARKET_WS_ENABLED:
        from backend.infrastructure.market_stream.orderbook_router import OrderbookRouter
        from backend.data.polymarket_websocket import PolymarketWebSocket, WebSocketConfig, ChannelType

        orderbook_router = OrderbookRouter()

        # Start the router dispatch loop
        asyncio.create_task(orderbook_router.start())

        # Connect to WebSocket and register router as handler
        if settings.POLYMARKET_WS_CLOB_URL:
            async def _start_market_ws() -> None:
                subscribed_tokens = set()
                try:
                    from backend.core.event_bus import event_bus

                    subscribed_tokens.update(event_bus.get_all_subscribed_tokens())
                except Exception:
                    logger.exception("Failed to read strategy WS subscriptions from EventBus")

                try:
                    from backend.core.market_scanner import fetch_short_duration_token_ids

                    short_tokens = await fetch_short_duration_token_ids(
                        limit=settings.POLYMARKET_WS_SUBSCRIPTION_LIMIT
                    )
                    subscribed_tokens.update(short_tokens)
                except Exception:
                    logger.exception("Failed to preload short-duration WS tokens")

                ws_config = WebSocketConfig(
                    channel=ChannelType.MARKET,
                    asset_ids=list(subscribed_tokens)[:settings.POLYMARKET_WS_SUBSCRIPTION_LIMIT],
                )
                ws_client = PolymarketWebSocket(ws_config)
                orderbook_router.register_with_websocket(ws_client)
                await ws_client.connect()

            asyncio.create_task(_start_market_ws())
            logger.info("OrderbookRouter WebSocket startup task scheduled")
        else:
            logger.warning("POLYMARKET_WS_CLOB_URL not configured, OrderbookRouter running in fallback mode")

    # Start the scheduler
    scheduler.start()
    for job in scheduler.get_jobs():
        logger.info(
            f"scheduler job registered: id={job.id} next_run={job.next_run_time}"
        )
    logger.info(f"scheduler started: jobs={[j.id for j in scheduler.get_jobs()]}")

    # Schedule all enabled strategies from DB
    logger.info("Scheduling enabled strategies from DB...")
    from backend.models.database import SessionLocal, StrategyConfig  # noqa: F401
    from backend.db.utils import get_db_session
    from datetime import datetime, timezone, timedelta

    disabled = []
    configs_to_schedule = []
    since = datetime.now(timezone.utc) - timedelta(hours=1)
    # Phase 1: read configs + trade history (read-only, no for_update)
    with get_db_session() as db:
        for config in db.query(StrategyConfig).filter(StrategyConfig.enabled).all():
            if config.strategy_name in ('copy_trader', 'weather_emos', 'agi_orchestrator', 'btc_oracle', 'crypto_oracle'):
                interval = config.interval_seconds or 60
                configs_to_schedule.append((config.strategy_name, interval, 'paper'))
                configs_to_schedule.append((config.strategy_name, interval, 'live'))
                continue
            for mode in settings.active_modes_set:
                trades = db.query(Trade).filter(
                    Trade.strategy == config.strategy_name,
                    Trade.settled,
                    Trade.timestamp >= since,
                    Trade.trading_mode == mode,
                ).all()

                should_disable = False
                if len(trades) >= 3:
                    resolved = [t for t in trades if t.result in ('win', 'loss')]
                    if len(resolved) < 3:
                        continue
                    wins = sum(1 for t in resolved if t.result == 'win')
                    win_rate = wins / len(resolved)
                    pnl = sum(t.pnl for t in trades if t.pnl)

                    if win_rate < 0.30 or pnl < -50.0:
                        should_disable = True
                        disabled.append(f"{config.strategy_name} ({mode}): win_rate={win_rate:.0%}, pnl=${pnl:.0f}")
                        logger.warning(f"Auto-disabled {config.strategy_name} ({mode}): win_rate={win_rate:.0%}, pnl=${pnl:.0f}")

                if not should_disable:
                    interval = config.interval_seconds or 60
                    configs_to_schedule.append((config.strategy_name, interval, mode))
                    logger.info(f"Scheduling strategy {config.strategy_name} ({mode}) every {interval}s")
    # Phase 2: apply disable mutations (separate session, short-lived)
    if disabled:
        with get_db_session() as db:
            for desc in disabled:
                name = desc.split(" ")[0]
                db.query(StrategyConfig).filter(
                    StrategyConfig.strategy_name == name,
                    StrategyConfig.enabled,
                ).update({"enabled": False})
            db.commit()
            logger.info(f"Disabled {len(disabled)} underperforming strategies: {disabled}")
    # Phase 3: register strategy jobs
    for name, interval, mode in configs_to_schedule:
        schedule_strategy(name, interval, mode=mode)
    logger.info("Done scheduling strategies from DB")

    if settings.NEWS_FEED_ENABLED:
        scheduler.add_job(
            news_feed_scan_job,
            IntervalTrigger(seconds=settings.NEWS_FEED_INTERVAL_SECONDS),
            id="news_feed_scan",
            replace_existing=True,
            max_instances=1,
        )

    if settings.ARBITRAGE_DETECTOR_ENABLED:
        scheduler.add_job(
            arbitrage_scan_job,
            IntervalTrigger(seconds=settings.ARBITRAGE_SCAN_INTERVAL_SECONDS),
            id="arbitrage_scan",
            replace_existing=True,
            max_instances=1,
        )

    if settings.AUTO_TRADER_ENABLED:
        for mode in modes:
            scheduler.add_job(
                auto_trader_job,
                IntervalTrigger(seconds=60),
                kwargs={"mode": mode},
                id=f"{mode}_auto_trader",
                replace_existing=True,
                max_instances=1,
            )

    # Strategy ranking job - daily ranking and auto-disable
    scheduler.add_job(
        strategy_ranking_job,
        IntervalTrigger(days=1),
        id="strategy_ranking",
        replace_existing=True,
        max_instances=1,
    )
    logger.info("Scheduled daily strategy ranking job")

    # Bankroll allocator - daily, runs after ranking to use fresh scores
    if getattr(settings, "AGI_BANKROLL_ALLOCATION_ENABLED", False):
        scheduler.add_job(
            bankroll_allocation_job,
            IntervalTrigger(days=getattr(settings, "AGI_BANKROLL_ALLOCATION_INTERVAL_DAYS", 1)),
            id="bankroll_allocation",
            replace_existing=True,
            max_instances=1,
        )
        logger.info("Scheduled daily bankroll allocation job")

    # Auto-improvement job - learns from trade outcomes
    if settings.AUTO_IMPROVE_ENABLED:
        from apscheduler.triggers.interval import IntervalTrigger as _IntervalTrigger

        scheduler.add_job(
            auto_improve_job,
            _IntervalTrigger(days=settings.AUTO_IMPROVE_INTERVAL_DAYS),
            id="auto_improve",
            replace_existing=True,
            max_instances=1,
        )

    # Self-review job - daily attribution, postmortems, degradation detection
    if settings.SELF_REVIEW_ENABLED:
        scheduler.add_job(
            self_review_job,
            IntervalTrigger(days=settings.SELF_REVIEW_INTERVAL_DAYS),
            id="self_review",
            replace_existing=True,
            max_instances=1,
        )
        logger.info(
            "Scheduled self-review job every %d day(s)",
            settings.SELF_REVIEW_INTERVAL_DAYS,
        )

    # Research pipeline job - autonomous market research
    if settings.RESEARCH_PIPELINE_ENABLED:
        scheduler.add_job(
            research_pipeline_job,
            IntervalTrigger(hours=settings.RESEARCH_PIPELINE_INTERVAL_HOURS),
            id="research_pipeline",
            replace_existing=True,
            max_instances=1,
        )
        logger.info(
            "Scheduled research pipeline job every %d hour(s)",
            settings.RESEARCH_PIPELINE_INTERVAL_HOURS,
        )

    # Autonomous promoter - evaluates experiments and auto-promotes/retires
    promotion_interval = getattr(settings, "AGI_PROMOTION_INTERVAL_HOURS", 6)
    scheduler.add_job(
        autonomous_promotion_job,
        IntervalTrigger(hours=promotion_interval),
        id="autonomous_promotion",
        replace_existing=True,
        max_instances=1,
    )
    logger.info(f"Scheduled autonomous promotion job every {promotion_interval} hour(s)")

    # Shadow validation - evaluates SHADOW genomes every 5 minutes
    if getattr(settings, "SHADOW_VALIDATE_ENABLED", True):
        scheduler.add_job(
            shadow_validation_job,
            IntervalTrigger(seconds=300),  # Every 5 minutes
            id="shadow_validate",
            replace_existing=True,
            max_instances=1,
        )
        logger.info("Scheduled shadow validation job every 5 minutes")

    # AGI improvement cycle — runs all 7 closed loops (feedback, meta-learn, evolve, propose, compose, replace, counterfactual)
    agi_cycle_interval = getattr(settings, "AGI_IMPROVEMENT_CYCLE_INTERVAL_HOURS", 1)
    if getattr(settings, "AGI_IMPROVEMENT_CYCLE_ENABLED", True):
        scheduler.add_job(
            agi_improvement_cycle_job,
            IntervalTrigger(hours=agi_cycle_interval),
            id="agi_improvement_cycle",
            replace_existing=True,
            max_instances=1,
        )
        logger.info("Scheduled AGI improvement cycle every %d hour(s)", agi_cycle_interval)

    if getattr(settings, "AGI_HEALTH_CHECK_ENABLED", True):
        health_interval = getattr(settings, "AGI_HEALTH_CHECK_INTERVAL_MINUTES", 15)
        scheduler.add_job(
            agi_health_check_job,
            IntervalTrigger(minutes=health_interval),
            id="agi_health_check",
            replace_existing=True,
            max_instances=1,
        )
        logger.info("Scheduled AGI health check every %d minute(s)", health_interval)

    if getattr(settings, "AGI_NIGHTLY_REVIEW_ENABLED", True):
        from datetime import datetime as _dt, timedelta as _td

        review_hour = getattr(settings, "AGI_NIGHTLY_REVIEW_HOUR", 2)
        now = _dt.now()
        target = now.replace(hour=review_hour, minute=0, second=0, microsecond=0)
        if target <= now:
            target += _td(days=1)
        scheduler.add_job(
            nightly_review_job,
            "date",
            run_date=target,
            id="nightly_review",
            replace_existing=True,
        )

    if getattr(settings, "AGI_REHABILITATION_ENABLED", True):
        scheduler.add_job(
            strategy_rehabilitation_job,
            IntervalTrigger(days=1),
            id="strategy_rehabilitation",
            replace_existing=True,
            max_instances=1,
        )

    if getattr(settings, "HISTORICAL_DATA_COLLECTOR_ENABLED", True):
        hist_interval = getattr(settings, "HISTORICAL_DATA_COLLECTOR_INTERVAL_HOURS", 6)
        scheduler.add_job(
            historical_data_collection_job,
            IntervalTrigger(hours=hist_interval),
            id="historical_data_collection",
            replace_existing=True,
            max_instances=1,
        )

    scheduler.add_job(
        forensics_integration_job,
        IntervalTrigger(days=1),
        id="forensics_integration",
        replace_existing=True,
        max_instances=1,
    )

    # Calibration drift check — runs every 6h; triggers retraining if Brier
    # score exceeds AGI_BRIER_DRIFT_THRESHOLD (default 0.25).
    calibration_interval_hours = getattr(settings, "AGI_CALIBRATION_CHECK_INTERVAL_HOURS", 6)
    scheduler.add_job(
        model_calibration_check_job,
        IntervalTrigger(hours=calibration_interval_hours),
        id="model_calibration_check",
        replace_existing=True,
        max_instances=1,
    )

    if getattr(settings, "AGI_FRONTTEST_DAYS", 14) > 0:
        scheduler.add_job(
            fronttest_validation_job,
            IntervalTrigger(hours=6),
            id="fronttest_validation",
            replace_existing=True,
            max_instances=1,
        )
        logger.info("Scheduled fronttest validation job every 6 hour(s)")

    backup_interval = getattr(settings, "DB_BACKUP_INTERVAL_HOURS", 6)
    if backup_interval > 0:
        scheduler.add_job(
            backup_job,
            IntervalTrigger(hours=backup_interval),
            id="db_backup",
            replace_existing=True,
            max_instances=1,
        )
        logger.info(f"Scheduled database backup job every {backup_interval} hour(s)")

    scheduler.add_job(
        cache_cleanup_job,
        IntervalTrigger(hours=1),
        id="cache_cleanup",
        replace_existing=True,
        max_instances=1,
    )
    logger.info("Scheduled cache cleanup job every 1 hour")

    from backend.core.proposal_executor import (
        execute_approved_proposals_job,
        measure_impact_and_rollback_job
    )

    scheduler.add_job(
        execute_approved_proposals_job,
        IntervalTrigger(minutes=30),
        id="execute_proposals",
        replace_existing=True,
        max_instances=1,
    )
    logger.info("Scheduled proposal execution job every 30 minutes")

    scheduler.add_job(
        measure_impact_and_rollback_job,
        IntervalTrigger(hours=2),
        id="measure_impact_rollback",
        replace_existing=True,
        max_instances=1,
    )
    logger.info("Scheduled impact measurement and auto-rollback job every 2 hours")

    scheduler.add_job(
        run_training_pipeline,
        'cron',
        hour=2, minute=0,
        id='nightly_retrain',
        replace_existing=True,
        max_instances=1,
    )
    logger.info("Scheduled nightly model retraining job at 02:00 UTC")

    scheduler.add_job(
        self_review_job,
        'cron',
        hour=0, minute=30,
        id='daily_self_review',
        replace_existing=True,
        max_instances=1,
    )
    logger.info("Scheduled daily self-review job at 00:30 UTC")

    try:
        from backend.ai.proposal_generator import auto_promote_eligible_proposals
        scheduler.add_job(
            auto_promote_eligible_proposals,
            'cron',
            minute=0,
            id='hourly_auto_promote',
            replace_existing=True,
            max_instances=1,
        )
        logger.info("Scheduled hourly auto-promote job for eligible proposals")
    except Exception:
        logger.exception("Failed to schedule auto-promote eligible proposals job")

    scheduler.add_job(
        audit_source_performance,
        'cron',
        hour=3, minute=0,
        id='source_performance_audit',
        replace_existing=True,
        max_instances=1,
    )
    logger.info("Scheduled source performance audit job at 03:00 UTC")

    def auto_disable_losing_strategies():
        from backend.models.database import Trade, StrategyConfig
        from backend.config import settings
        from backend.db.utils import get_db_session
        from datetime import datetime, timezone, timedelta

        disabled = []
        min_trades = getattr(settings, "AGI_AUTO_DISABLE_MIN_TRADES", 10)
        try:
            since = datetime.now(timezone.utc) - timedelta(hours=1)
            with get_db_session() as db:
                for config in db.query(StrategyConfig).filter(StrategyConfig.enabled).all():
                    if config.strategy_name in ('copy_trader', 'weather_emos', 'agi_orchestrator', 'btc_oracle', 'crypto_oracle'):
                        continue

                    for mode in settings.active_modes_set:
                        trades = db.query(Trade).filter(
                            Trade.strategy == config.strategy_name,
                            Trade.settled,
                            Trade.timestamp >= since,
                            Trade.trading_mode == mode,
                        ).all()

                        if len(trades) < min_trades:
                            continue

                        # Only count trades with definitive outcomes for win rate
                        resolved = [t for t in trades if t.result in ('win', 'loss')]
                        if len(resolved) < max(3, min_trades // 2):
                            continue  # not enough resolved outcomes yet

                        wins = sum(1 for t in resolved if t.result == 'win')
                        win_rate = wins / len(resolved)
                        pnl = sum(t.pnl for t in trades if t.pnl)

                        if win_rate < 0.30 or pnl < -50.0:
                            config.enabled = False
                            config.disabled_at = datetime.now(timezone.utc)
                            disabled.append(f"{config.strategy_name} ({mode}): win_rate={win_rate:.0%}, pnl=${pnl:.0f}")
                            logger.warning(f"Auto-disabled {config.strategy_name} ({mode}): win_rate={win_rate:.0%}, pnl=${pnl:.0f}")
                            break

            if disabled:
                logger.info(f"Auto-disabled {len(disabled)} losing strategies: {disabled}")
        except Exception as e:
            logger.warning(f"Auto-disable check failed: {e}")

    try:
        scheduler.add_job(
            auto_disable_losing_strategies,
            'cron',
            minute=15,
            id='auto_disable_losing',
            replace_existing=True,
            max_instances=1,
        )
        logger.info("Scheduled auto-disable losing strategies job at :15 every hour")
    except Exception:
        logger.exception("Failed to schedule auto-disable losing strategies job")

    def auto_rehabilitate_strategies():
        from backend.models.database import Trade, StrategyConfig
        from backend.config import settings
        from backend.db.utils import get_db_session
        from datetime import datetime, timezone, timedelta

        cooldown_hours = getattr(settings, "AGI_REHAB_LITE_COOLDOWN_HOURS", 1)
        re_disable_hours = getattr(settings, "AGI_REHAB_LITE_RE_DISABLE_HOURS", 4)
        wr_threshold = getattr(settings, "AGI_REHAB_LITE_WIN_RATE_THRESHOLD", 0.30)

        rehabilitated = []
        re_disabled = []
        try:
            cutoff = datetime.now(timezone.utc) - timedelta(hours=cooldown_hours)
            with get_db_session() as db:
                disabled_configs = db.query(StrategyConfig).filter(
                    StrategyConfig.enabled.is_(False),
                    StrategyConfig.disabled_at.isnot(None),
                ).all()

                for config in disabled_configs:
                    if config.strategy_name in ('agi_orchestrator',):
                        continue

                    disabled_at = config.disabled_at
                    if disabled_at and disabled_at.tzinfo is None:
                        disabled_at = disabled_at.replace(tzinfo=timezone.utc)

                    if not disabled_at or disabled_at > cutoff:
                        continue

                    since_rehab = disabled_at
                    for mode in settings.active_modes_set:
                        trades = db.query(Trade).filter(
                            Trade.strategy == config.strategy_name,
                            Trade.settled,
                            Trade.timestamp >= since_rehab,
                            Trade.trading_mode == mode,
                        ).all()

                        if len(trades) < 3:
                            continue

                        wins = sum(1 for t in trades if t.result == 'win')
                        win_rate = wins / len(trades) if trades else 0

                        if win_rate < wr_threshold:
                            config.disabled_at = datetime.now(timezone.utc) + timedelta(hours=re_disable_hours - cooldown_hours)
                            re_disabled.append(f"{config.strategy_name}: WR={win_rate:.0%} < {wr_threshold:.0%}, extended disable {re_disable_hours}h")
                            logger.warning(
                                f"Re-disable {config.strategy_name}: WR={win_rate:.0%} below {wr_threshold:.0%}, extended for {re_disable_hours}h"
                            )
                            break
                    else:
                        config.enabled = True
                        config.trading_mode = 'paper'
                        config.disabled_at = None
                        rehabilitated.append(config.strategy_name)
                        logger.info(
                            f"Rehabilitated {config.strategy_name} in paper mode (cooldown {cooldown_hours}h elapsed)"
                        )

            if rehabilitated:
                logger.info(f"Lite-rehabilitated {len(rehabilitated)} strategies: {rehabilitated}")
            if re_disabled:
                logger.info(f"Extended disable for {len(re_disabled)} strategies: {re_disabled}")
        except Exception as e:
            logger.warning(f"Lite rehabilitation check failed: {e}")

    try:
        scheduler.add_job(
            auto_rehabilitate_strategies,
            'cron',
            minute=45,
            id='auto_rehabilitate_lite',
            replace_existing=True,
            max_instances=1,
        )
        logger.info("Scheduled lite rehabilitation job at :45 every hour")
    except Exception:
        logger.exception("Failed to schedule auto-rehabilitate strategies job")

    scheduler.add_job(
        update_source_weights_from_outcomes,
        'cron',
        minute=30,
        id='source_weight_update',
        replace_existing=True,
        max_instances=1,
    )
    logger.info("Scheduled source weight update job every hour at :30")

    scheduler.add_job(
        generate_rejection_proposals,
        'cron',
        hour=4, minute=0,
        id='rejection_learner',
        replace_existing=True,
        max_instances=1,
    )
    logger.info("Scheduled rejection learner job at 04:00 UTC")

    # Evolution engine jobs (guarded by EVOLUTION_ENGINE_ENABLED flag)
    if settings.EVOLUTION_ENGINE_ENABLED:
        logger.info("EVOLUTION_ENGINE_ENABLED=True - scheduling evolution jobs")
        _register_evolution_jobs(scheduler)

        # Necromancy analysis — weekly
        scheduler.add_job(
            necromancy_analysis_job,
            IntervalTrigger(weeks=1),
            id="necromancy_analysis",
            replace_existing=True,
            max_instances=1,
        )
        logger.info("Scheduled necromancy analysis job weekly")

        # Full population review — weekly
        scheduler.add_job(
            full_population_review_job,
            IntervalTrigger(weeks=1),
            id="population_review",
            replace_existing=True,
            max_instances=1,
        )
        logger.info("Scheduled full population review job weekly")

        # Legend evaluation — monthly
        scheduler.add_job(
            legend_evaluation_job,
            IntervalTrigger(weeks=4),
            id="legend_evaluation",
            replace_existing=True,
            max_instances=1,
        )
        logger.info("Scheduled legend evaluation job monthly")

    # Initialize queue worker if enabled
    if settings.JOB_WORKER_ENABLED:
        logger.info("JOB_WORKER_ENABLED=True - initializing queue worker")

        global queue, worker, worker_task, task_manager
        queue = create_queue()

        if hasattr(queue, "recover_stale_jobs"):
            import concurrent.futures

            def _run_recovery():
                recovery_loop = asyncio.new_event_loop()
                try:
                    asyncio.set_event_loop(recovery_loop)
                    return recovery_loop.run_until_complete(
                        queue.recover_stale_jobs(stale_threshold_seconds=600)
                    )
                finally:
                    recovery_loop.close()

            try:
                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                    recovered = pool.submit(_run_recovery).result(timeout=30)
                if recovered > 0:
                    logger.info(f"Recovered {recovered} stale jobs from previous crash")
            except Exception as e:
                logger.exception(f"Stale job recovery failed: {e}")

        use_local_worker = queue.__class__.__name__ != "RedisQueue"
        if not use_local_worker:
            logger.warning(
                "JOB_WORKER_ENABLED with RedisQueue detected; skipping local Worker loop. "
                "Run arq worker (backend.job_queue.arq_settings:WorkerSettings)."
            )
        else:
            # bot process: use the module-level task_manager set during scheduler init
            # API process: task_manager is set on app.state by lifespan startup
            worker = Worker(queue, max_concurrent=settings.MAX_CONCURRENT_JOBS, task_manager=task_manager)

            # Keep settlement_check on APScheduler until queue mode has a
            # periodic producer for settlement_check jobs.  Removing it here
            # left the worker idle with no settlement jobs enqueued, so live
            # positions stayed pending and blocked new trades via exposure caps.
            jobs_to_remove = [f"{mode}_market_scan" for mode in modes]
            for job_id in jobs_to_remove:
                try:
                    scheduler.remove_job(job_id)
                    logger.info(
                        f"Removed APScheduler job '{job_id}' - worker will handle via queue"
                    )
                except Exception as e:
                    logger.warning(f"Could not remove job '{job_id}': {e}")

            if task_manager:
                worker_task = asyncio.create_task(
                    task_manager.create_task(worker.start(), name="queue_worker")
                )
            else:
                worker_task = asyncio.create_task(worker.start())
            logger.info("Queue worker started in background")

        log_event(
            "success",
            "Multi-strategy trading scheduler started with queue worker",
            {
                "worker_enabled": bool(use_local_worker),
                "scan_interval": f"{scan_seconds}s",
                "settlement_interval": f"{settle_seconds}s",
                "min_edge": f"{settings.MIN_EDGE_THRESHOLD:.0%}",
                "weather_enabled": settings.WEATHER_ENABLED,
                "max_concurrent_jobs": settings.MAX_CONCURRENT_JOBS,
            },
        )
    else:
        logger.info("JOB_WORKER_ENABLED=False - using APScheduler for job execution")
        log_event(
            "success",
            "Multi-strategy trading scheduler started",
            {
                "worker_enabled": False,
                "scan_interval": f"{scan_seconds}s",
                "settlement_interval": f"{settle_seconds}s",
                "min_edge": f"{settings.MIN_EDGE_THRESHOLD:.0%}",
                "weather_enabled": settings.WEATHER_ENABLED,
            },
        )

    # Load registry-driven strategy jobs from DB
    logger.info("[DEBUG] About to load strategy jobs from DB")
    try:
        _load_strategy_jobs()
        logger.info("[DEBUG] _load_strategy_jobs() completed successfully")
    except Exception as e:
        logger.exception(f"Could not load strategy jobs from DB: {e}")

    # Register event-driven research triggers
    logger.info("[DEBUG] About to register research event triggers")
    try:
        from backend.research.event_triggers import register_research_triggers

        register_research_triggers()
        logger.info("[DEBUG] register_research_triggers() completed")
    except Exception as e:
        logger.warning("Could not register research event triggers: %s", e)


def stop_scheduler():
    """Stop the background scheduler."""
    global scheduler, worker, queue, worker_task

    if scheduler is None or not scheduler.running:
        log_event("info", "Scheduler not running")
        return

    # Stop worker if running
    if worker is not None:
        logger.info("Stopping queue worker...")
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(worker.stop())
        except RuntimeError:
            asyncio.run(worker.stop())
        worker = None
        logger.info("Queue worker stopped")

        # Cancel the worker asyncio task to unblock any pending await
        if worker_task is not None and not worker_task.done():
            worker_task.cancel()
            logger.info("Worker task cancelled")
        worker_task = None

        # Shutdown queue
        if queue is not None:
            queue.shutdown()
            queue = None
            logger.info("Queue shutdown complete")

    # Shutdown scheduler
    scheduler.shutdown(wait=False)
    scheduler = None
    log_event("info", "Scheduler stopped")


def is_scheduler_running() -> bool:
    """Check if scheduler is currently running."""
    return scheduler is not None and scheduler.running


def reschedule_jobs() -> list[dict]:
    """Reschedule jobs with current settings values. Call after settings update."""
    from apscheduler.jobstores.base import JobLookupError as _JobLookupError

    global scheduler
    if scheduler is None or not scheduler.running:
        return []

    results = []

    # Reschedule scan job
    try:
        scheduler.reschedule_job(
            "market_scan",
            trigger=IntervalTrigger(seconds=settings.SCAN_INTERVAL_SECONDS),
        )
        job = scheduler.get_job("market_scan")
        results.append(
            {
                "job_id": "market_scan",
                "next_run": str(job.next_run_time) if job else None,
            }
        )
    except _JobLookupError:
        logger.warning("market_scan job not registered, skipping reschedule")
    except Exception as e:
        logger.warning(f"Failed to reschedule market_scan: {e}")

    # Reschedule settlement job
    try:
        scheduler.reschedule_job(
            "settlement_check",
            trigger=IntervalTrigger(seconds=settings.SETTLEMENT_INTERVAL_SECONDS),
        )
        job = scheduler.get_job("settlement_check")
        results.append(
            {
                "job_id": "settlement_check",
                "next_run": str(job.next_run_time) if job else None,
            }
        )
    except _JobLookupError:
        logger.warning("settlement_check job not registered, skipping reschedule")
    except Exception as e:
        logger.warning(f"Failed to reschedule settlement_check: {e}")

    # Reschedule weather scan if enabled
    if settings.WEATHER_ENABLED:
        try:
            scheduler.reschedule_job(
                "weather_scan",
                trigger=IntervalTrigger(seconds=settings.WEATHER_SCAN_INTERVAL_SECONDS),
            )
            job = scheduler.get_job("weather_scan")
            results.append(
                {
                    "job_id": "weather_scan",
                    "next_run": str(job.next_run_time) if job else None,
                }
            )
        except _JobLookupError:
            logger.warning("weather_scan job not registered, skipping reschedule")
        except Exception as e:
            logger.warning(f"Failed to reschedule weather_scan: {e}")

    log_event("info", f"Scheduler jobs rescheduled: {[r['job_id'] for r in results]}")
    return results


async def run_manual_scan(mode: str = "paper"):
    """Trigger a manual market scan."""
    log_event("info", f"Manual scan triggered for mode: {mode}")
    await scan_and_trade_job(mode)


async def run_manual_settlement():
    """Trigger a manual settlement check."""
    log_event("info", "Manual settlement triggered")
    await settlement_job()

# Add monitoring job
async def monitoring_job():
    """Run production monitoring checks"""
    from backend.core.monitoring import run_monitoring_check
    from backend.models.database import get_db

    db = next(get_db())
    try:
        health = await run_monitoring_check(db)
        logger.info(f"✅ Monitoring check: {health['database']['healthy']}")
        return health
    except Exception as e:
        logger.error(f"❌ Monitoring check failed: {e}")
    finally:
        db.close()
