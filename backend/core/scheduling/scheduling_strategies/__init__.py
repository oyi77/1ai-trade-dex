"""
Backend job functions scheduled by APScheduler.

Split from the original scheduling_strategies.py monolith into a
package of domain-oriented sub-modules.
"""
# ruff: noqa: F401 — deliberate backward-compat re-exports

# ---------------------------------------------------------------------------
# Module-level re-exports for backward compatibility
# ---------------------------------------------------------------------------
# These are imported at package level so that code which does
# ``from backend.core.scheduling.scheduling_strategies import ...`` or
# ``scheduling_strategies.asyncio`` continues to work.
import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from loguru import logger
from sqlalchemy import func

from backend.config import settings
from backend.core.decisions import record_decision
from backend.core.event_bus import _broadcast_event
from backend.core.heartbeat import update_heartbeat
from backend.core.position_monitor import position_monitor_job

# ---------------------------------------------------------------------------
# Public function re-exports from sub-modules
# ---------------------------------------------------------------------------
from backend.core.scheduling.scheduling_strategies._approval import (
    _execute_trade,
    _process_signal_with_approval,
    _queue_for_approval,
)
from backend.core.scheduling.scheduling_strategies._helpers import (
    _get_bankroll_for_mode,
    _market_data_clob,
)
from backend.core.scheduling.scheduling_strategies.auto_trader import (
    auto_redeem_job,
    auto_trader_job,
)
from backend.core.scheduling.scheduling_strategies.feed_scanners import (
    arbitrage_scan_job,
    market_universe_scan_job,
    news_feed_scan_job,
)
from backend.core.scheduling.scheduling_strategies.heartbeat import (
    heartbeat_job,
    strategy_cycle_job,
)
from backend.core.scheduling.scheduling_strategies.market_scan import (
    scan_and_trade_job,
    weather_scan_and_trade_job,
)
from backend.core.scheduling.scheduling_strategies.settlement import (
    _settlement_job_inner,
    settlement_job,
    verify_settlement_blockchain,
)
from backend.core.scheduling.scheduling_strategies.wallet_sync import (
    sync_live_wallet,
    sync_testnet_wallet,
)
from backend.core.signals import scan_universe_markets
from backend.models.database import BotState, PendingApproval, Signal, StrategyConfig, Trade

# ---------------------------------------------------------------------------
# Explicit export list
# ---------------------------------------------------------------------------
__all__ = ["position_monitor_job"]
