"""System routes - stats, bot control, backtest, events."""

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from typing import List, Optional
from datetime import datetime, timezone, timedelta
from sqlalchemy import func, text
from sqlalchemy.orm import Session
import json as _json
import asyncio
import psutil
import os

from backend.config import settings
from backend.models.database import (
    get_db,
    BotState,
    Trade,
    Signal,
    AILog,
    DecisionLog,
    StrategyConfig,
    AuditLog,
    engine,
    for_update,
)
from backend.api.auth import require_admin
from backend.core.signals import scan_for_signals
from backend.core.wallet.bankroll_reconciliation import (
    fetch_pm_profile_pnl,
    fetch_pm_profile_trade_stats,
    _initial_bankroll_for_mode,
)
from backend.api.validation import (
    StrategyConfigRequest as ValidatedStrategyConfigRequest,
)
from loguru import logger

router = APIRouter(tags=["system"])
_ticker_price_cache = {}
_ticker_price_cache_timestamps = {}
_CACHE_TTL_SECONDS = 60

from ._system_iso import (  # noqa: E402  (must follow the names it imports back)
    BotStats,
    EventResponse,
    SyncMetadata,
    _available_simulated_bankroll,
    _iso,
    _live_cache_values,
)

from ._system_get_stats import (  # noqa: E402  (must follow the names it imports back)
    get_stats,
)

from ._system_get_strategy_stats import (  # noqa: E402  (must follow the names it imports back)
    AuditLogResponse,
    BacktestRequest,
    LiveAdjustRequest,
    PaperTopupRequest,
    ResetRequest,
    StrategyUpdateRequest,
    get_ai_status,
    get_db_pool_stats,
    get_events,
    get_mirofish_health,
    get_signal_config,
    get_strategy_stats,
    quick_backtest,
    run_backtest,
    run_scan,
    toggle_ai,
)

from ._system_get_audit_logs import (  # noqa: E402  (must follow the names it imports back)
    DetailedHealthStatus,
    HealthStatus,
    ReadinessStatus,
    get_audit_logs,
    get_connection_limits,
    health_check,
    redeem_positions,
)


__all__ = [
    "AILog",
    "APIRouter",
    "AuditLog",
    "AuditLogResponse",
    "BacktestRequest",
    "BaseModel",
    "BotState",
    "BotStats",
    "DecisionLog",
    "Depends",
    "DetailedHealthStatus",
    "EventResponse",
    "Field",
    "HTTPException",
    "HealthStatus",
    "List",
    "LiveAdjustRequest",
    "Optional",
    "PaperTopupRequest",
    "Query",
    "ReadinessStatus",
    "ResetRequest",
    "Session",
    "Signal",
    "StrategyConfig",
    "StrategyUpdateRequest",
    "SyncMetadata",
    "Trade",
    "ValidatedStrategyConfigRequest",
    "_CACHE_TTL_SECONDS",
    "_available_simulated_bankroll",
    "_initial_bankroll_for_mode",
    "_iso",
    "_json",
    "_live_cache_values",
    "_ticker_price_cache",
    "_ticker_price_cache_timestamps",
    "asyncio",
    "datetime",
    "engine",
    "fetch_pm_profile_pnl",
    "fetch_pm_profile_trade_stats",
    "for_update",
    "func",
    "get_ai_status",
    "get_audit_logs",
    "get_connection_limits",
    "get_db",
    "get_db_pool_stats",
    "get_events",
    "get_mirofish_health",
    "get_signal_config",
    "get_stats",
    "get_strategy_stats",
    "health_check",
    "logger",
    "os",
    "psutil",
    "quick_backtest",
    "redeem_positions",
    "require_admin",
    "router",
    "run_backtest",
    "run_scan",
    "scan_for_signals",
    "settings",
    "text",
    "timedelta",
    "timezone",
    "toggle_ai",
]
