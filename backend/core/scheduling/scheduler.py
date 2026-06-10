"""DEPRECATED: Use backend.core.scheduler instead.

Background scheduler for multi-strategy autonomous trading.

This module manages the APScheduler instance and scheduling configuration.
The actual job functions are in scheduling_strategies.py.

This module will be removed in a future release.
"""

import asyncio
import datetime as dt_module
import threading
from datetime import datetime, timedelta, timezone
from typing import List, Optional
from apscheduler.events import EVENT_JOB_EXECUTED, EVENT_JOB_ERROR
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.triggers.cron import CronTrigger
from loguru import logger

from backend.config import settings
from backend.job_queue.worker import Worker
from backend.job_queue.abstract import AbstractQueue, create_queue
from backend.core.scheduling.task_manager import TaskManager

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
from backend.core.position_monitor import (
    sell_signal_monitor_job,
    SELL_MONITOR_INTERVAL_MINUTES,
)

# auto_sell is opt-in per strategy, not imported globally
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
from backend.core.db_archiver import nightly_archive_job
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
from backend.mesh.auditor import audit_source_performance
from backend.mesh.learning import update_source_weights_from_outcomes
from backend.ai.rejection_learner import generate_rejection_proposals
from backend.core.strategy_evolution_loop import strategy_evolution_loop
from backend.core.wr_monitor import wr_monitor_job
from backend.core.wallet_reconciler import wallet_reconciler_job
from backend.core.arb_executor import arb_execution_job

scheduler: Optional[AsyncIOScheduler] = None

queue: Optional[AbstractQueue] = None
worker: Optional[Worker] = None
worker_task: Optional[asyncio.Task] = None
task_manager: Optional[TaskManager] = None

# Concurrency guard for scheduler state mutations (threading.Lock since start_scheduler is sync)
_scheduler_state_lock = threading.Lock()


def _get_scheduler() -> Optional[AsyncIOScheduler]:
    """Thread-safe accessor for the module-level scheduler."""
    with _scheduler_state_lock:
        return scheduler


def _set_scheduler(value: Optional[AsyncIOScheduler]) -> None:
    """Thread-safe setter for the module-level scheduler."""
    global scheduler
    with _scheduler_state_lock:
        scheduler = value


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


def auto_disable_losing_strategies():
    """Audit strategy performance and disable/throttle losers. Module-level so it can be tested.

    Uses two windows:
    1. Last 24 hours (recent performance, catches fresh losing streaks)
    2. Lifetime (catches strategies that have been losing for weeks but
       happen to have no recent trades)

    A strategy is disabled if EITHER window shows it's a loser.
    """
    from backend.models.database import Trade, StrategyConfig
    from backend.config import settings
    from backend.db.utils import get_db_session
    from datetime import datetime, timezone, timedelta

    disabled = []
    min_trades = getattr(settings, "AGI_AUTO_DISABLE_MIN_TRADES", 5)
    min_trades_lifetime = getattr(settings, "AGI_AUTO_DISABLE_MIN_TRADES_LIFETIME", 50)
    try:
        now = datetime.now(timezone.utc)
        since_24h = now - timedelta(hours=24)
        with get_db_session() as db:
            # Batch fetch enabled configs and active modes
            enabled_configs = (
                db.query(StrategyConfig).filter(StrategyConfig.enabled).all()
            )
            strategy_names = [c.strategy_name for c in enabled_configs]
            active_modes = list(settings.active_modes_set)

            all_trades = (
                db.query(Trade)
                .filter(
                    Trade.strategy.in_(strategy_names),
                    Trade.settled,
                    Trade.trading_mode.in_(active_modes),
                )
                .all()
            )

            trades_by_key: dict[tuple[str, str], list] = {}
            lifetime_trades_by_key: dict[tuple[str, str], list] = {}
            for t in all_trades:
                key = (t.strategy, t.trading_mode)
                lifetime_trades_by_key.setdefault(key, []).append(t)
                if t.timestamp and t.timestamp >= since_24h:
                    trades_by_key.setdefault(key, []).append(t)

            from backend.core.maker_taker_analytics import maker_taker_analytics

            maker_taker_analytics.get_stats(db)

            for config in enabled_configs:
                config_mode = getattr(config, "mode", None) or "paper"
                for mode in active_modes:
                    if config_mode != mode:
                        continue
                    trades = trades_by_key.get((config.strategy_name, mode), [])
                    lifetime_trades = lifetime_trades_by_key.get(
                        (config.strategy_name, mode), []
                    )

                    recent_disabled = _evaluate_and_disable(
                        config, mode, trades, min_trades, "24h"
                    )
                    if recent_disabled:
                        disabled.append(recent_disabled)
                        break

                    if len(lifetime_trades) >= min_trades_lifetime:
                        lifetime_disabled = _evaluate_and_disable(
                            config, mode, lifetime_trades, min_trades, "lifetime"
                        )
                        if lifetime_disabled:
                            disabled.append(lifetime_disabled)
                            break

        if disabled:
            logger.warning(
                f"auto_disable_losing_strategies: disabled {len(disabled)} strategies: {disabled}"
            )
    except Exception as exc:
        logger.exception(f"auto_disable_losing_strategies failed: {exc}")
    return disabled


def _evaluate_and_disable(
    config, mode: str, trades: list, min_trades: int, window_label: str
) -> str | None:
    """Evaluate trades and disable the strategy if it qualifies. Returns reason string or None."""
    if len(trades) < min_trades:
        return None

    resolved = [t for t in trades if t.result in ("win", "loss")]
    if len(resolved) < max(3, min_trades // 2):
        return None

    wins = sum(1 for t in resolved if (t.pnl or 0) > 0)
    win_rate = wins / len(resolved)
    pnl = sum(t.pnl for t in trades if t.pnl)

    recent_losses = sorted(
        [t for t in trades if t.result == "loss"],
        key=lambda t: t.settlement_time or t.timestamp,
        reverse=True,
    )
    consecutive_losses = 0
    for t in recent_losses:
        consecutive_losses += 1
        if consecutive_losses >= 10:
            break

    if win_rate < 0.30 or pnl < -50.0 or consecutive_losses >= 10:
        from backend.core.strategy_health import disable_for_rehab

        reason_parts = []
        if win_rate < 0.30:
            reason_parts.append(f"win_rate={win_rate:.0%}")
        if pnl < -50.0:
            reason_parts.append(f"pnl=${pnl:.0f}")
        if consecutive_losses >= 10:
            reason_parts.append(f"{consecutive_losses}+ consecutive losses")
        reason_str = ", ".join(reason_parts)
        disable_for_rehab(config)
        logger.warning(
            f"Auto-disabled {config.strategy_name} ({mode}) [{window_label}]: {reason_str}"
        )
        return f"{config.strategy_name} ({mode}) [{window_label}]: {reason_str}"
    return None


def _throttle_maker_preference(
    config, mode: str, trades: list, mt_stats: dict
) -> str | None:
    """Throttle strategies where taker execution is losing money.

    Switches the strategy to maker-only mode (via params) to capture
    rebates and avoid taker fees on a strategy that's net negative ROI.
    """
    if not mt_stats:
        return None
    recommendation = mt_stats.get("recommendation", "insufficient_data")
    if recommendation not in ("reduce_taker", "prefer_maker"):
        return None
    maker_info = mt_stats.get("maker", {})
    taker_info = mt_stats.get("taker", {})
    taker_roi = taker_info.get("roi", 0)
    taker_count = taker_info.get("count", 0)
    if taker_count < 10:
        return None
    import json as _json

    if recommendation == "reduce_taker":
        reason = (
            f"Taker ROI ({taker_roi:.2%}) is negative "
            f"(n={taker_count} settled trades)"
        )
    else:
        maker_roi = maker_info.get("roi", 0)
        reason = (
            f"Maker ROI ({maker_roi:.2%}) significantly exceeds Taker ROI "
            f"({taker_roi:.2%}) over full trade history"
        )
    config.rehab_allocation_pct = 0.50
    try:
        params = _json.loads(config.params) if config.params else {}
    except Exception:
        params = {}
    params["force_maker_only"] = True
    config.params = _json.dumps(params)
    logger.warning(
        f"Throttled {config.strategy_name} ({mode}) due to Taker "
        f"underperformance: {reason}. Enforced maker-only execution."
    )
    return f"{config.strategy_name} ({mode}): {reason}"


def _cumulative_loss_disable(
    db, enabled_configs: list, active_modes: list
) -> list[str]:
    """Disable strategies with >$100 cumulative loss over the last 7 days."""
    from sqlalchemy import func as _func
    from backend.models.database import Trade
    from backend.core.strategy_health import disable_for_rehab

    disabled = []
    week_ago = datetime.now(timezone.utc) - timedelta(days=7)
    for config in enabled_configs:
        if not config.enabled:
            continue
        for mode in active_modes:
            cum_pnl = (
                db.query(_func.coalesce(_func.sum(Trade.pnl), 0.0))
                .filter(
                    Trade.strategy == config.strategy_name,
                    Trade.trading_mode == mode,
                    Trade.settled,
                    Trade.timestamp >= week_ago,
                )
                .scalar()
                or 0.0
            )
            if cum_pnl < -100.0:
                disable_for_rehab(config)
                disabled.append(
                    f"{config.strategy_name} ({mode}): 7d cumulative loss ${abs(cum_pnl):.0f}"
                )
                logger.warning(
                    f"Auto-disabled {config.strategy_name} ({mode}): 7d cumulative loss ${abs(cum_pnl):.0f}"
                )
                break
    return disabled


async def _sync_db_to_polymarket_job():
    """Periodic 1:1 sync: DB trades ↔ Polymarket reality.

    Fetches Polymarket positions every 5 minutes and ensures DB trade statuses
    match what's actually on Polymarket. Prevents the DB from drifting away
    from reality over hours/days of continuous operation.

    Fixes the root cause of 190+ unsettled trades accumulating over weeks.
    """
    import httpx
    from backend.db.utils import get_db_session
    from backend.models.database import Trade
    from backend.config import settings as _settings

    try:
        wallet = _settings.POLYMARKET_BUILDER_ADDRESS
        if not wallet:
            logger.debug("[db_pm_sync] No wallet address configured, skipping")
            return

        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.get(
                f"https://data-api.polymarket.com/positions?user={wallet.lower()}"
            )
            if r.status_code != 200:
                logger.warning(f"[db_pm_sync] Positions API returned {r.status_code}")
                return
            positions = r.json()

        # Build token_id → position map
        pm_positions = {}
        for p in positions:
            asset = p.get("asset", "")
            if asset:
                pm_positions[asset] = {
                    "size": float(p.get("size", 0)),
                    "cur_price": float(p.get("curPrice", 0)),
                    "title": p.get("title", ""),
                    "outcome": p.get("outcome", ""),
                    "redeemable": p.get("redeemable", False),
                }

        with get_db_session() as db:
            # 1. Find DB trades marked as filled but position no longer exists
            db_filled = (
                db.query(Trade)
                .filter(
                    Trade.trading_mode == "live",
                    Trade.status == "filled",
                    Trade.settled.is_(False),
                )
                .all()
            )

            marked_closed = 0
            for trade in db_filled:
                tid = str(trade.token_id) if trade.token_id else ""
                if tid and tid not in pm_positions:
                    # Position gone → market resolved, mark closed
                    trade.status = "closed"
                    trade.settlement_time = datetime.now(timezone.utc)
                    trade.settlement_source = "db_pm_sync"
                    marked_closed += 1

            # 2. Find DB trades that should be filled (have matching PM position)
            db_open = (
                db.query(Trade)
                .filter(
                    Trade.trading_mode == "live",
                    Trade.token_id.isnot(None),
                    Trade.settled.is_(False),
                    Trade.status.in_([None, "open", "pending"]),
                )
                .all()
            )

            marked_filled = 0
            pm_assets_found = set()
            for trade in db_open:
                tid = str(trade.token_id) if trade.token_id else ""
                if tid and tid in pm_positions:
                    pos = pm_positions[tid]
                    trade.status = "filled"
                    # Update PnL in real-time
                    direction = (trade.direction or "no").lower()
                    entry = float(trade.entry_price or 0)
                    cur = pos["cur_price"]
                    size = float(trade.size or 0)
                    if direction in ("yes", "up"):
                        trade.pnl = round(size * (cur - entry), 4)
                    else:
                        trade.pnl = round(size * (entry - cur), 4)
                    trade.settlement_time = datetime.now(timezone.utc)
                    marked_filled += 1
                    pm_assets_found.add(tid)

            if marked_closed > 0 or marked_filled > 0:
                db.commit()
                logger.info(
                    f"[db_pm_sync] Synced: {marked_filled} marked filled, "
                    f"{marked_closed} marked closed. "
                    f"PM positions: {len(pm_positions)}, DB filled: {len(db_filled)}, "
                    f"DB open: {len(db_open)}"
                )

            # 3. Update bot_state bankroll from portfolio reality
            if marked_closed > 0 or marked_filled > 0:
                try:
                    total_pos_value = sum(
                        float(p.get("currentValue", 0)) for p in positions
                    )
                    # Use recent wallet_sync value or fallback
                    from backend.models.database import BotState

                    state = db.query(BotState).filter_by(mode="live").first()
                    if state:
                        cash = float(state.bankroll or 0) - total_pos_value
                        from backend.core.wallet.botstate_ledger import BotStateLedger

                        BotStateLedger.sync_to_absolute(
                            db=db,
                            mode="live",
                            target_balance=cash + total_pos_value,
                            source="db_pm_sync",
                        )
                        db.commit()
                except Exception as e:
                    logger.debug(f"[db_pm_sync] bankroll update failed: {e}")

    except Exception as e:
        logger.warning(f"[db_pm_sync] Failed: {e}")


async def _cleanup_stale_trades_job():
    """Settle trades older than 12h that are still open. Prevents stale accumulation.

    Handles BOTH live and paper modes. For paper trades, first attempts Gamma
    resolution before force-settling (fixes the 1990+ paper trades stuck as
    status=None forever bug).
    """
    from backend.db.utils import get_db_session
    from backend.models.database import Trade

    try:
        with get_db_session() as db:
            cutoff = datetime.now(timezone.utc) - timedelta(hours=12)
            stale_live = (
                db.query(Trade)
                .filter(
                    Trade.settled.is_(False),
                    Trade.trading_mode == "live",
                    Trade.timestamp < cutoff,
                )
                .all()
            )
            if stale_live:
                for t in stale_live:
                    t.settled = True
                    try:
                        from backend.core.settlement.settlement_helpers import calculate_pnl

                        t.pnl = calculate_pnl(t, 0.0)
                    except Exception:
                        min_loss = -(float(getattr(t, "entry_price", 0.0) or 0.0) * float(getattr(t, "size", 0.0) or 0.0))
                        t.pnl = round(min_loss, 2)
                    t.settlement_value = 0.0
                    t.settlement_time = datetime.now(timezone.utc)
                    t.settlement_source = "stale_live_force_close"
                db.commit()
                logger.info(
                    f"[stale_trade_cleanup] Auto-settled {len(stale_live)} stale LIVE trades (>12h)"
                )

            # Paper trades: mark settled=True with pnl=None to let
            # resolve_paper_trades pick them up for Gamma resolution.
            # Previously: paper trades were NEVER cleaned (query had no
            # mode filter but the pnl=0.0 assignment blocked Gamma resolution).
            stale_paper = (
                db.query(Trade)
                .filter(
                    Trade.settled.is_(False),
                    Trade.trading_mode == "paper",
                    Trade.timestamp < cutoff,
                )
                .all()
            )
            if stale_paper:
                for t in stale_paper:
                    t.settled = True
                    t.pnl = None  # signal to resolve_paper_trades: resolve me
                    t.settlement_value = None
                    t.settlement_time = datetime.now(timezone.utc)
                db.commit()
                logger.info(
                    f"[stale_trade_cleanup] Marked {len(stale_paper)} stale PAPER trades "
                    f"for Gamma resolution (>12h)"
                )

                # Immediately resolve them via Gamma
                try:
                    from backend.core.settlement.settlement_helpers import (
                        resolve_paper_trades,
                    )

                    paper_settled = await resolve_paper_trades(db)
                    if paper_settled:
                        wins = sum(1 for t in paper_settled if getattr(t, "result", "") == "win")
                        losses = len(paper_settled) - wins
                        total_pnl = sum(
                            getattr(t, "pnl", 0.0) or 0.0 for t in paper_settled
                        )
                        logger.info(
                            f"[stale_trade_cleanup] Gamma-resolved {len(paper_settled)} "
                            f"paper trades: {wins}W/{losses}L, PnL=${total_pnl:+.2f}"
                        )
                except Exception as e:
                    logger.warning(f"[stale_trade_cleanup] Paper Gamma resolution failed: {e}")

            # Force-settle paper trades that were marked for Gamma but couldn't
            # resolve (e.g. weather/event markets where Gamma returns '[').
            # These are stuck at settled=True, pnl=NULL. After 5 days, force as loss.
            stuck_cutoff = datetime.now(timezone.utc) - timedelta(days=5)
            stuck_paper = (
                db.query(Trade)
                .filter(
                    Trade.trading_mode == "paper",
                    Trade.settled.is_(True),
                    Trade.pnl.is_(None),
                    Trade.timestamp < stuck_cutoff,
                )
                .all()
            )
            if stuck_paper:
                for t in stuck_paper:
                    t.pnl = 0.0
                    t.result = "loss"
                    t.settlement_value = 0.0
                    t.settlement_time = datetime.now(timezone.utc)
                    t.settlement_source = "force_closed_unresolved"
                db.commit()
                logger.info(
                    f"[stale_trade_cleanup] Force-settled {len(stuck_paper)} "
                    f"stuck paper trades as loss (>5 days, market never resolved)"
                )
    except Exception as e:
        logger.warning(f"[stale_trade_cleanup] Failed: {e}")

    # --- 5-min binary trade cleanup (1h threshold) ---
    # These strategies trade short-duration binaries (5-min windows) but the
    # main settlement loop waits 12-72h before force-settling. The duplicate
    # guard blocks new entries until old ones are settled.
    _BINARY_5M_STRATEGIES = frozenset({
        "crypto_oracle", "cex_pm_leadlag",
        "crypto_micro", "hft_scalper", "probability_arb",
    })
    try:
        with get_db_session() as db:
            now = datetime.now(timezone.utc)
            cutoff_1h = now - timedelta(hours=1)
            stale_binaries = (
                db.query(Trade)
                .filter(
                    Trade.settled.is_(False),
                    Trade.timestamp < cutoff_1h,
                    Trade.strategy.in_(list(_BINARY_5M_STRATEGIES)),
                )
                .all()
            )
            if stale_binaries:
                for t in stale_binaries:
                    t.settled = True
                    t.result = "expired_unresolved"
                    t.pnl = 0.0
                    t.settlement_value = 0.0
                    t.settlement_time = now
                    t.settlement_source = "5min_binary_cleanup"
                db.commit()
                logger.warning(
                    "[stale_trade_cleanup] Auto-settled {} stale 5-min binary trades (>1h) "
                    "from strategies: {}",
                    len(stale_binaries),
                    {t.strategy for t in stale_binaries},
                )
    except Exception as e:
        logger.warning(f"[stale_trade_cleanup] 5-min binary cleanup failed: {e}")


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

    # Weekly HuggingFace dataset ingestion — refreshes local Parquet cache
    def _hf_ingest_weekly():
        """Wrapper for weekly HF dataset ingestion job."""
        try:
            from backend.scripts.ingest_hf_dataset import ingest_dataset

            path = ingest_dataset()
            logger.info("Weekly HF dataset ingestion complete: %s", path)
        except Exception as e:
            logger.warning("Weekly HF dataset ingestion failed: %s", e)

    scheduler.add_job(
        _hf_ingest_weekly,
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
                # Only schedule strategy for its configured mode (skip paper if live)
                if config.mode == "live" and mode != "live":
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
                IntervalTrigger(seconds=30),
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
                disabled_configs = (
                    db.query(StrategyConfig)
                    .filter(
                        StrategyConfig.enabled.is_(True),
                        StrategyConfig.disabled_at.isnot(None),
                    )
                    .all()
                )

                for config in disabled_configs:
                    if config.strategy_name in ("agi_orchestrator",):
                        continue

                    disabled_at = config.disabled_at
                    if disabled_at and disabled_at.tzinfo is None:
                        disabled_at = disabled_at.replace(tzinfo=timezone.utc)

                    if not disabled_at or disabled_at > cutoff:
                        continue

                    since_rehab = disabled_at
                    for mode in settings.active_modes_set:
                        trades = (
                            db.query(Trade)
                            .filter(
                                Trade.strategy == config.strategy_name,
                                Trade.settled,
                                Trade.timestamp >= since_rehab,
                                Trade.trading_mode == mode,
                            )
                            .all()
                        )

                        if len(trades) < 3:
                            continue

                        wins = sum(1 for t in trades if t.result == "win")
                        win_rate = wins / len(trades) if trades else 0

                        if win_rate < wr_threshold:
                            config.disabled_at = datetime.now(timezone.utc) + timedelta(
                                hours=re_disable_hours - cooldown_hours
                            )
                            re_disabled.append(
                                f"{config.strategy_name}: WR={win_rate:.0%} < {wr_threshold:.0%}, extended disable {re_disable_hours}h"
                            )
                            logger.warning(
                                f"Re-disable {config.strategy_name}: WR={win_rate:.0%} below {wr_threshold:.0%}, extended for {re_disable_hours}h"
                            )
                            break
                    else:
                        config.enabled = True
                        # Only set paper mode if strategy was previously disabled/rehabbing.
                        # Active live strategies keep their existing trading_mode.
                        if config.disabled_at is not None:
                            config.trading_mode = "paper"
                        config.disabled_at = None
                        if config.rehab_allocation_pct is None:
                            config.rehab_allocation_pct = getattr(
                                settings, "AGI_REHAB_ALLOCATION_PCT", 0.25
                            )
                        rehabilitated.append(config.strategy_name)
                        logger.info(
                            f"Rehabilitated {config.strategy_name} in paper mode at {config.rehab_allocation_pct:.0%} allocation (cooldown {cooldown_hours}h elapsed)"
                        )

            if rehabilitated:
                logger.info(
                    f"Lite-rehabilitated {len(rehabilitated)} strategies: {rehabilitated}"
                )
            if re_disabled:
                logger.info(
                    f"Extended disable for {len(re_disabled)} strategies: {re_disabled}"
                )
        except Exception as e:
            logger.warning(f"Lite rehabilitation check failed: {e}")

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


def reschedule_jobs() -> list[dict]:
    """Reschedule jobs with current settings values. Call after settings update."""
    from apscheduler.jobstores.base import JobLookupError as _JobLookupError

    sched = _get_scheduler()
    if sched is None or not sched.running:
        return []

    results = []

    # Reschedule scan job
    try:
        sched.reschedule_job(
            "market_scan",
            trigger=IntervalTrigger(seconds=settings.SCAN_INTERVAL_SECONDS),
        )
        job = sched.get_job("market_scan")
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
        sched.reschedule_job(
            "settlement_check",
            trigger=IntervalTrigger(seconds=settings.SETTLEMENT_INTERVAL_SECONDS),
        )
        job = sched.get_job("settlement_check")
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
            sched.reschedule_job(
                "weather_scan",
                trigger=IntervalTrigger(seconds=settings.WEATHER_SCAN_INTERVAL_SECONDS),
            )
            job = sched.get_job("weather_scan")
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


def performance_decay_check_job():
    """G-09: Detect strategy performance decay by comparing 24h vs 7d win rates.

    Runs every PERFORMANCE_DECAY_CHECK_INTERVAL_HOURS (default 6h).
    If a strategy's 24h win rate drops by more than PERFORMANCE_DECAY_THRESHOLD
    (default 20%) compared to its 7d win rate, logs a warning.
    """
    from backend.models.database import Trade, StrategyConfig
    from backend.db.utils import get_db_session
    from datetime import datetime, timezone, timedelta

    threshold = getattr(settings, "PERFORMANCE_DECAY_THRESHOLD", 0.20)
    now = datetime.now(timezone.utc)
    day_start = now - timedelta(hours=24)
    week_start = now - timedelta(days=7)

    try:
        with get_db_session() as db:
            configs = (
                db.query(StrategyConfig).filter(StrategyConfig.enabled.is_(True)).all()
            )
            for config in configs:
                strategy_name = config.strategy_name

                # 7-day win rate
                week_trades = (
                    db.query(Trade)
                    .filter(
                        Trade.strategy == strategy_name,
                        Trade.settled.is_(True),
                        Trade.settlement_time >= week_start,
                        Trade.result.in_(["win", "loss"]),
                    )
                    .all()
                )

                if len(week_trades) < 5:
                    continue

                week_wins = sum(1 for t in week_trades if t.result == "win")
                week_wr = week_wins / len(week_trades)

                # 24-hour win rate
                day_trades = [t for t in week_trades if t.settlement_time >= day_start]
                if len(day_trades) < 3:
                    continue

                day_wins = sum(1 for t in day_trades if t.result == "win")
                day_wr = day_wins / len(day_trades)

                # Check for decay
                decay = week_wr - day_wr
                if decay > threshold:
                    logger.warning(
                        "[perf_decay] Strategy {} decay detected: "
                        "24h WR={:.1%} vs 7d WR={:.1%} (decay={:.1%} > threshold={:.1%})",
                        strategy_name,
                        day_wr,
                        week_wr,
                        decay,
                        threshold,
                    )
                    log_event(
                        "warning",
                        f"Performance decay: {strategy_name} "
                        f"24h WR={day_wr:.0%} vs 7d WR={week_wr:.0%}",
                    )
                else:
                    logger.debug(
                        "[perf_decay] Strategy {} healthy: 24h WR={:.1%}, 7d WR={:.1%}, decay={:.1%}",
                        strategy_name,
                        day_wr,
                        week_wr,
                        decay,
                    )

    except Exception as e:
        logger.warning("[perf_decay] Performance decay check failed: {}", e)
