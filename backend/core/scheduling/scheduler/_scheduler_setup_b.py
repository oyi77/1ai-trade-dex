"""Phase B — position monitor, self-tune, watchdog, wallet, meteora."""

from __future__ import annotations

from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from loguru import logger

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
from backend.mesh.auditor import audit_source_performance
from backend.mesh.learning import update_source_weights_from_outcomes
import datetime as dt_module
from backend.core.scheduling.scheduler.db_sync import (
    _cleanup_stale_trades_job,
    _sync_db_to_polymarket_job,
)
from backend.core.scheduling.scheduler.event_log import log_event
from backend.core.scheduling.scheduler.hft_trigger import _subscribe_hft_trigger
from backend.core.scheduling.scheduler.performance import (
    auto_disable_losing_strategies,
    performance_decay_check_job,
)
from backend.core.scheduling.scheduler.persistence import (
    _persist_and_add_job,
    load_scheduler_state,
)
from backend.core.scheduling.scheduler.rehab import auto_rehabilitate_strategies
from backend.core.scheduling.scheduler.registration import (
    _job_executed_listener,
    _load_strategy_jobs,
    schedule_strategy,
)
from apscheduler.events import EVENT_JOB_EXECUTED, EVENT_JOB_ERROR
import asyncio


def _setup_monitoring_jobs(scheduler) -> None:
    """Phase B — position monitor, self-tune, watchdog, wallet, meteora."""

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

    _persist_and_add_job(
        scheduler,
        sell_signal_monitor_job,
        IntervalTrigger(minutes=SELL_MONITOR_INTERVAL_MINUTES, jitter=60),
        id="sell_signal_monitor",
        replace_existing=True,
        max_instances=1,
        misfire_grace_time=120,
    )

    # Auto-sell: opt-in module only. Strategies import AutoSellManager directly.
    # NOT forced globally — each strategy decides whether to use profit-target exits.

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
    logger.info(
        f"Scheduled AGI self-tuning review every {agi_self_tune_interval} minutes"
    )

    # Watchdog: check strategy heartbeats every 30s
    from backend.core.heartbeat import watchdog_job, wallet_sync_job, liveness_file_job, drift_alert_job

    scheduler.add_job(
        liveness_file_job,
        IntervalTrigger(seconds=20),
        id="liveness_file",
        replace_existing=True,
        max_instances=1,
        next_run_time=dt_module.datetime.now(dt_module.timezone.utc)
        + dt_module.timedelta(seconds=5),
    )

    scheduler.add_job(
        watchdog_job,
        IntervalTrigger(seconds=30),
        id="watchdog",
        replace_existing=True,
        max_instances=1,
        next_run_time=dt_module.datetime.now(dt_module.timezone.utc)
        + dt_module.timedelta(seconds=5),
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

    _persist_and_add_job(
        scheduler,
        wallet_reconciler_job,
        IntervalTrigger(minutes=5),
        id="wallet_reconciler",
        replace_existing=True,
        max_instances=1,
        misfire_grace_time=120,
    )
    logger.info("Scheduled wallet reconciler job every 5 minutes")

    # DB ↔ CLOB drift alert: compare live bankroll to real PUSD every 5 min
    _persist_and_add_job(
        scheduler,
        drift_alert_job,
        IntervalTrigger(minutes=5),
        id="drift_alert",
        replace_existing=True,
        max_instances=1,
        misfire_grace_time=120,
    )

    logger.info("Scheduled drift alert job every 5 minutes")

    # Meteora DLMM pool screening: refresh candidates every 30 minutes
    from backend.data.meteora.service import meteora_screening_job

    _persist_and_add_job(
        scheduler,
        meteora_screening_job,
        IntervalTrigger(minutes=30, jitter=120),
        id="meteora_screening",
        replace_existing=True,
        max_instances=1,
        misfire_grace_time=300,
    )
    logger.info("Scheduled Meteora DLMM screening job every 30 minutes")

    # Meteora paper position management: evaluate exits every 10 minutes
    from backend.data.meteora.paper import meteora_management_job

    _persist_and_add_job(
        scheduler,
        meteora_management_job,
        IntervalTrigger(minutes=10, jitter=60),
        id="meteora_management",
        replace_existing=True,
        max_instances=1,
        misfire_grace_time=120,
    )
    logger.info("Scheduled Meteora DLMM management job every 10 minutes")

    # Meteora data retention: prune old screening artifacts daily
    from backend.data.meteora.service import meteora_retention_job

    _persist_and_add_job(
        scheduler,
        meteora_retention_job,
        IntervalTrigger(hours=24, jitter=600),
        id="meteora_retention",
        replace_existing=True,
        max_instances=1,
        misfire_grace_time=3600,
    )
    logger.info("Scheduled Meteora DLMM retention job every 24 hours")

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

    # Start WSDispatcher and unified WS stream
    if settings.POLYMARKET_WS_ENABLED:
        from backend.infrastructure.market_stream.orderbook_router import (
            OrderbookRouter,
        )
        from backend.core.ws_dispatcher import ws_dispatcher

        orderbook_router = OrderbookRouter()

        # Start the router dispatch loop
        asyncio.create_task(orderbook_router.start())

        # ── HFT trigger: subscribe orderbook updates to strategy re-evaluation ──
        if settings.HFT_ENABLED:
            asyncio.create_task(_subscribe_hft_trigger(orderbook_router))
            logger.info("HFT trigger handler registered on OrderbookRouter")

        # ── HFT signal generator: real-time orderbook signal detection ──
        if settings.HFT_ENABLED:
            try:
                from backend.core.hft_signal_gen import start_default_generator

                asyncio.create_task(start_default_generator(orderbook_router))
                logger.info("HFT signal generator started")
            except Exception as e:
                logger.warning("Failed to start HFT signal generator: {}", e)

        # ── HFT latency optimizer: pre-warm connections + tune event loop ──
        if settings.HFT_ENABLED:
            try:
                from backend.core.latency_optimizer import start_latency_optimizer

                asyncio.create_task(start_latency_optimizer())
                logger.info("HFT latency optimizer pre-warming started")
            except Exception as e:
                logger.warning("Failed to start HFT latency optimizer: {}", e)

        if settings.POLYMARKET_WS_CLOB_URL:
            # Register OrderbookRouter with WSDispatcher
            ws_dispatcher.register_router(orderbook_router)
            # Start unified dispatcher pipeline
            asyncio.create_task(ws_dispatcher.start())
            logger.info("WSDispatcher and OrderbookRouter startup task scheduled")
        else:
            logger.warning(
                "POLYMARKET_WS_CLOB_URL not configured, WSDispatcher not started, OrderbookRouter running in fallback mode"
            )

    from backend.core.scheduling.scheduler.hf_ingest import hf_ingest_weekly_job

    scheduler.add_job(
        hf_ingest_weekly_job,
        IntervalTrigger(days=7),
        id="hf_dataset_ingest",
        replace_existing=True,
        max_instances=1,
    )
    logger.info("Scheduled weekly HuggingFace dataset ingestion job")

    scheduler.add_listener(_job_executed_listener, EVENT_JOB_EXECUTED | EVENT_JOB_ERROR)

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
            for mode in settings.active_modes_set:
                # Only schedule strategy for its configured mode (skip mismatched)
                if config.mode and config.mode != mode:
                    continue
                trades = (
                    db.query(Trade)
                    .filter(
                        Trade.strategy == config.strategy_name,
                        Trade.settled,
                        Trade.timestamp >= since,
                        Trade.trading_mode == mode,
                    )
                    .all()
                )

                should_disable = False
                if len(trades) >= 3:
                    resolved = [t for t in trades if t.result in ("win", "loss")]
                    if len(resolved) < 3:
                        continue
                    wins = sum(1 for t in resolved if t.result == "win")
                    win_rate = wins / len(resolved)
                    pnl = sum(t.pnl for t in trades if t.pnl)

                    if win_rate < 0.30 or pnl < -50.0:
                        should_disable = True
                        disabled.append(
                            f"{config.strategy_name} ({mode}): win_rate={win_rate:.0%}, pnl=${pnl:.0f}"
                        )
                        logger.warning(
                            f"Auto-disabled {config.strategy_name} ({mode}): win_rate={win_rate:.0%}, pnl=${pnl:.0f}"
                        )

                if not should_disable:
                    interval = config.interval_seconds or 60
                    configs_to_schedule.append((config.strategy_name, interval, mode))
                    logger.info(
                        f"Scheduling strategy {config.strategy_name} ({mode}) every {interval}s"
                    )
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
            logger.info(
                f"Disabled {len(disabled)} underperforming strategies: {disabled}"
            )
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

    if getattr(settings, "ARB_EXECUTOR_ENABLED", False):
        for mode in modes:
            scheduler.add_job(
                arb_execution_job,
                IntervalTrigger(seconds=120),
                kwargs={"mode": mode, "limit": 200},
                id=f"{mode}_arb_executor",
                replace_existing=True,
                max_instances=1,
            )
        logger.info("Scheduled arb executor job every 30 seconds for modes: %s", modes)

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
            IntervalTrigger(
                days=getattr(settings, "AGI_BANKROLL_ALLOCATION_INTERVAL_DAYS", 1)
            ),
            id="bankroll_allocation",
            replace_existing=True,
            max_instances=1,
        )
        logger.info("Scheduled daily bankroll allocation job")

    # Auto-improvement job - learns from trade outcomes
    if settings.AUTO_IMPROVE_ENABLED:
        scheduler.add_job(
            auto_improve_job,
            IntervalTrigger(days=settings.AUTO_IMPROVE_INTERVAL_DAYS),
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
    logger.info(
        f"Scheduled autonomous promotion job every {promotion_interval} hour(s)"
    )

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

