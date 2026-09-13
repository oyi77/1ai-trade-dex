"""Phase C — AGI cycle, evolution, health, review, nightly, misc."""

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
from backend.core.scheduling.scheduler.registration import _job_executed_listener
import asyncio


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

    # Old DEAP mutation cycle disabled — Smart AGI evolution replaces it.
    # Smart AGI runs edge discovery + capital allocation + auto-kill, not parameter mutation.
    # target_scheduler.add_job(
    #     run_mutation_cycle,
    #     IntervalTrigger(hours=settings.AGI_MUTATION_INTERVAL_HOURS),
    #     id="evolution_mutation_cycle",
    #     replace_existing=True,
    #     max_instances=1,
    # )
    logger.info("Old DEAP mutation cycle disabled — Smart AGI evolution replaces it")

    # Old DEAP crossover cycle disabled — Smart AGI handles capital allocation instead.
    # target_scheduler.add_job(
    #     run_crossover_cycle,
    #     IntervalTrigger(hours=settings.AGI_CROSSOVER_INTERVAL_HOURS),
    #     id="evolution_crossover_cycle",
    #     replace_existing=True,
    #     max_instances=1,
    # )
    logger.info("Old DEAP crossover cycle disabled — Smart AGI handles allocation")

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



def _setup_agi_jobs(scheduler, agi_self_tune_interval: int) -> None:
    """Phase C — AGI cycle, evolution, health, review, nightly, misc."""
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
        logger.info(
            "Scheduled AGI improvement cycle every %d hour(s)", agi_cycle_interval
        )

    # Strategy evolution coordinator — health scan, forensics, rehab, variant creation
    evolution_interval = getattr(settings, "AGI_IMPROVEMENT_CYCLE_INTERVAL_HOURS", 4)
    scheduler.add_job(
        strategy_evolution_loop,
        IntervalTrigger(hours=evolution_interval),
        id="strategy_evolution_loop",
        replace_existing=True,
        max_instances=1,
    )
    logger.info(
        "Scheduled strategy evolution loop every %d hour(s)", evolution_interval
    )

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

    # --- AGI startup verification summary ---
    _agi_shadow_enabled = getattr(settings, "SHADOW_VALIDATE_ENABLED", True)
    _agi_cycle_enabled = getattr(settings, "AGI_IMPROVEMENT_CYCLE_ENABLED", True)
    _agi_health_enabled = getattr(settings, "AGI_HEALTH_CHECK_ENABLED", True)
    _agi_jobs_registered: list[str] = [
        f"autonomous_promotion={promotion_interval}h",
        (
            f"improvement_cycle={agi_cycle_interval}h"
            if _agi_cycle_enabled
            else "improvement_cycle=DISABLED"
        ),
        (
            f"health_check={getattr(settings, 'AGI_HEALTH_CHECK_INTERVAL_MINUTES', 15)}min"
            if _agi_health_enabled
            else "health_check=DISABLED"
        ),
        f"self_tune={agi_self_tune_interval}min",
        "shadow_validate=5min" if _agi_shadow_enabled else "shadow_validate=DISABLED",
    ]
    logger.info(
        "[AGI Scheduler] All AGI jobs registered: %s",
        ", ".join(_agi_jobs_registered),
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
    calibration_interval_hours = getattr(
        settings, "AGI_CALIBRATION_CHECK_INTERVAL_HOURS", 6
    )
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

    # Parquet Archiver - runs daily at 2:00 AM
    scheduler.add_job(
        nightly_archive_job,
        CronTrigger(hour=2, minute=0),
        id="nightly_archive",
        replace_existing=True,
        max_instances=1,
    )
    logger.info("Scheduled nightly Parquet database archiver at 2:00 AM")

    # G-09: Strategy performance decay detection — every 6 hours
    _persist_and_add_job(
        scheduler,
        performance_decay_check_job,
        IntervalTrigger(
            hours=getattr(settings, "PERFORMANCE_DECAY_CHECK_INTERVAL_HOURS", 6)
        ),
        id="performance_decay_check",
        replace_existing=True,
        max_instances=1,
        misfire_grace_time=300,
    )
    logger.info(
        "Scheduled performance decay check job every %d hours",
        getattr(settings, "PERFORMANCE_DECAY_CHECK_INTERVAL_HOURS", 6),
    )

    # G-04: Disk space monitoring — check every 15 minutes
    from backend.monitoring.disk_monitor import disk_space_check_job

    scheduler.add_job(
        disk_space_check_job,
        IntervalTrigger(minutes=15),
        id="disk_space_check",
        replace_existing=True,
        max_instances=1,
    )
    logger.info("Scheduled disk space check job every 15 minutes")

    # WR Monitor: check live strategy win rates every 6 hours
    scheduler.add_job(
        wr_monitor_job,
        IntervalTrigger(hours=6, jitter=600),
        id="wr_monitor",
        replace_existing=True,
        max_instances=1,
    )
    logger.info("Scheduled WR monitor job every 6 hours")

    from backend.core.proposal_executor import (
        execute_approved_proposals_job,
        measure_impact_and_rollback_job,
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
        "cron",
        hour=2,
        minute=0,
        id="nightly_retrain",
        replace_existing=True,
        max_instances=1,
    )
    logger.info("Scheduled nightly model retraining job at 02:00 UTC")

    scheduler.add_job(
        self_review_job,
        "cron",
        hour=0,
        minute=30,
        id="daily_self_review",
        replace_existing=True,
        max_instances=1,
    )
    logger.info("Scheduled daily self-review job at 00:30 UTC")

    try:
        from backend.ai.proposal_generator import auto_promote_eligible_proposals

        scheduler.add_job(
            auto_promote_eligible_proposals,
            "cron",
            minute=0,
            id="hourly_auto_promote",
            replace_existing=True,
            max_instances=1,
        )
        logger.info("Scheduled hourly auto-promote job for eligible proposals")
    except Exception:
        logger.exception("Failed to schedule auto-promote eligible proposals job")

    scheduler.add_job(
        audit_source_performance,
        "cron",
        hour=3,
        minute=0,
        id="source_performance_audit",
        replace_existing=True,
        max_instances=1,
    )
    logger.info("Scheduled source performance audit job at 03:00 UTC")

    try:
        scheduler.add_job(
            auto_disable_losing_strategies,
            "cron",
            minute=15,
            id="auto_disable_losing",
            replace_existing=True,
            max_instances=1,
        )
        logger.info("Scheduled auto-disable losing strategies job at :15 every hour")
    except Exception:
        logger.exception("Failed to schedule auto-disable losing strategies job")

    try:
        scheduler.add_job(
            auto_rehabilitate_strategies,
            "cron",
            minute=45,
            id="auto_rehabilitate_lite",
            replace_existing=True,
            max_instances=1,
        )
        logger.info("Scheduled lite rehabilitation job at :45 every hour")
    except Exception:
        logger.exception("Failed to schedule auto-rehabilitate strategies job")

    scheduler.add_job(
        update_source_weights_from_outcomes,
        "cron",
        minute=30,
        id="source_weight_update",
        replace_existing=True,
        max_instances=1,
    )
    logger.info("Scheduled source weight update job every hour at :30")

    scheduler.add_job(
        generate_rejection_proposals,
        "cron",
        hour=4,
        minute=0,
        id="rejection_learner",
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

