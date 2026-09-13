# _scheduler_core.py — extracted from scheduler.py
"""Scheduler sub-module: _scheduler_core."""

from apscheduler.events import EVENT_JOB_EXECUTED, EVENT_JOB_ERROR
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from backend.ai.rejection_learner import generate_rejection_proposals
from backend.ai.training.train import run_training_pipeline
from backend.application.agi.evolution_jobs import (
    run_crossover_cycle,
    rebalance_population,
    run_mutation_cycle,
    update_fitness_from_shadow,
    necromancy_analysis_job,
    full_population_review_job,
    legend_evaluation_job,
)
from backend.config import settings
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
from backend.core.agi_orchestrator import agi_improvement_cycle_job
from backend.core.arb_executor import arb_execution_job
from backend.core.autonomous_promoter import autonomous_promotion_job
from backend.core.cache_cleanup import cache_cleanup_job
from backend.core.db_archiver import nightly_archive_job
from backend.core.db_backup import backup_job
from backend.core.learning.auto_improve import auto_improve_job
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
from backend.core.shadow_validation import shadow_validation_job
from backend.core.strategy_evolution_loop import strategy_evolution_loop
from backend.core.strategy_ranker import strategy_ranking_job
from backend.core.wallet.bankroll_allocator import bankroll_allocation_job
from backend.core.wallet_reconciler import wallet_reconciler_job
from backend.core.wr_monitor import wr_monitor_job
from backend.db.utils import utcnow
from backend.job_queue.abstract import AbstractQueue, create_queue
from backend.job_queue.worker import Worker
from backend.mesh.auditor import audit_source_performance
from backend.mesh.learning import update_source_weights_from_outcomes
from backend.models.database import ScheduledJob, Trade
from datetime import datetime, timedelta, timezone
from loguru import logger
import asyncio
import datetime as dt_module

from .db_sync import _cleanup_stale_trades_job, _sync_db_to_polymarket_job
from .event_log import log_event
from .hft_trigger import _subscribe_hft_trigger
from .performance import auto_disable_losing_strategies, performance_decay_check_job
from .persistence import _persist_and_add_job, load_scheduler_state
from .rehab import auto_rehabilitate_strategies
from .registration import _job_executed_listener, _load_strategy_jobs, schedule_strategy
from .state import _get_scheduler, _set_scheduler, queue, scheduler, task_manager, worker, worker_task

from backend.core.scheduling.scheduler._scheduler_setup_a import _setup_core_jobs
from backend.core.scheduling.scheduler._scheduler_setup_b import _setup_monitoring_jobs
from backend.core.scheduling.scheduler._scheduler_setup_c import (
    _setup_agi_jobs,
    _register_evolution_jobs,
)
def start_scheduler():
    """Start the background scheduler for multi-strategy trading."""
    global queue, worker, worker_task

    if _get_scheduler() is not None and _get_scheduler().running:
        log_event("warning", "Scheduler already running")
        return

    _set_scheduler(AsyncIOScheduler())
    scheduler = _get_scheduler()

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


    scan_seconds = settings.SCAN_INTERVAL_SECONDS
    settle_seconds = settings.SETTLEMENT_INTERVAL_SECONDS

    from backend.core.mode_context import list_contexts

    contexts = list_contexts()
    modes = list(contexts.keys()) if contexts else ["paper", "testnet", "live"]

    _setup_core_jobs(scheduler, scan_seconds, settle_seconds, modes)

    from backend.core.agi_self_tuner import get_agi_self_tuner

    agi_self_tune_interval = getattr(settings, "AGI_SELF_TUNE_INTERVAL_MINUTES", 30)
    _setup_monitoring_jobs(scheduler)
    _setup_agi_jobs(scheduler, agi_self_tune_interval)
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
            worker = Worker(
                queue,
                max_concurrent=settings.MAX_CONCURRENT_JOBS,
                task_manager=task_manager,
            )

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

    logger.info("Loading strategy jobs from DB")
    try:
        _load_strategy_jobs()
        logger.info("Strategy jobs loaded from DB")
    except Exception as e:
        logger.exception(f"Could not load strategy jobs from DB: {e}")

    try:
        from backend.research.event_triggers import register_research_triggers

        register_research_triggers()
    except Exception as e:
        logger.warning("Could not register research event triggers: %s", e)


def stop_scheduler():
    """Stop the background scheduler."""
    global worker, queue, worker_task

    scheduler = _get_scheduler()
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

    # Stop WSDispatcher if active
    try:
        from backend.core.ws_dispatcher import ws_dispatcher

        try:
            loop = asyncio.get_running_loop()
            loop.create_task(ws_dispatcher.stop())
        except RuntimeError:
            asyncio.run(ws_dispatcher.stop())
    except Exception as e:
        logger.warning(f"Failed to stop ws_dispatcher: {e}")

    # Shutdown scheduler
    scheduler.shutdown(wait=False)
    _set_scheduler(None)
    log_event("info", "Scheduler stopped")

def is_scheduler_running() -> bool:
    """Check if scheduler is currently running."""
    sched = _get_scheduler()
    return sched is not None and sched.running

