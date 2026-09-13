"""Phase A — restore, settlement, heartbeat, scans, universe."""

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


def _setup_core_jobs(scheduler, scan_seconds: int, settle_seconds: int, modes: list) -> None:
    """Phase A — restore, settlement, heartbeat, scans, universe."""
    # Restore jobs from DB first
    try:
        jobs_restored = load_scheduler_state(scheduler)
        if jobs_restored:
            logger.info(
                f"Restored {jobs_restored} scheduled jobs from DB crash recovery."
            )
    except Exception as exc:
        logger.warning(f"Scheduler state restoration failed: {exc}")

    scan_seconds = settings.SCAN_INTERVAL_SECONDS
    settle_seconds = settings.SETTLEMENT_INTERVAL_SECONDS

    _persist_and_add_job(
        scheduler,
        settlement_job,
        IntervalTrigger(seconds=settle_seconds),
        id="settlement_check",
        max_instances=1,
        replace_existing=True,
        misfire_grace_time=60,
    )

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

    # Stale trade cleanup: settle trades older than 12h to prevent accumulation
    _persist_and_add_job(
        scheduler,
        _cleanup_stale_trades_job,
        IntervalTrigger(minutes=15),
        id="stale_trade_cleanup",
        max_instances=1,
        replace_existing=True,
        misfire_grace_time=60,
    )

    # DB ↔ Polymarket 1:1 sync: prevent drift between local state and reality.
    # Runs every 5 minutes to keep trade statuses aligned with actual positions.
    _persist_and_add_job(
        scheduler,
        _sync_db_to_polymarket_job,
        IntervalTrigger(minutes=5),
        id="db_pm_sync",
        max_instances=1,
        replace_existing=True,
        misfire_grace_time=60,
    )
    logger.info("Scheduled DB↔Polymarket sync job every 5 minutes")

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
