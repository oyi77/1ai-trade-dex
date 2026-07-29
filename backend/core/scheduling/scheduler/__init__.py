"""
APScheduler wrapper — split from the original scheduler.py monolith.

Re-exports all symbols from the original single file for backward
compatibility.  External importers use lazy imports inside functions,
so this package-level re‑export is belt‑and‑suspenders.
"""
# ruff: noqa: F401 — deliberate backward-compat re-exports

# ---------------------------------------------------------------------------
# Public symbol re‑exports from sub‑modules
# ---------------------------------------------------------------------------
# State globals
# ruff: noqa: F401 — deliberate backward-compat re-exports
# Core scheduler lifecycle
from backend.core.scheduling.scheduler._scheduler_core import (
    _register_evolution_jobs,
    is_scheduler_running,
    reschedule_jobs,
    start_scheduler,
    stop_scheduler,
)

# DB sync
from backend.core.scheduling.scheduler.db_sync import (
    _cleanup_stale_trades_job,
    _sync_db_to_polymarket_job,
)

# Event logging
from backend.core.scheduling.scheduler.event_log import (
    get_recent_events,
    log_event,
)

# HFT trigger
from backend.core.scheduling.scheduler.hft_trigger import (
    _subscribe_hft_trigger,
)

# Monitoring
from backend.core.scheduling.scheduler.monitoring import (
    monitoring_job,
    run_manual_scan,
    run_manual_settlement,
)

# Performance
from backend.core.scheduling.scheduler.performance import (
    _cumulative_loss_disable,
    _evaluate_and_disable,
    _throttle_maker_preference,
    auto_disable_losing_strategies,
    performance_decay_check_job,
)

# Persistence
from backend.core.scheduling.scheduler.persistence import (
    _persist_and_add_job,
    _serialize_trigger,
    load_scheduler_state,
    save_scheduler_state,
)

# Registration
from backend.core.scheduling.scheduler.registration import (
    _job_executed_listener,
    _load_strategy_jobs,
    _register_event_driven_strategies,
    get_scheduler_jobs,
    schedule_strategy,
    unschedule_strategy,
)
from backend.core.scheduling.scheduler.state import (
    _get_scheduler,
    _set_scheduler,
    scheduler,
)

# Backward-compat re-exports from scheduling_strategies (originally imported in scheduler.py)
from backend.core.scheduling.scheduling_strategies import (
    scan_and_trade_job,
    settlement_job,
)
