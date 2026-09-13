"""DEPRECATED: Use backend.core.bankroll_reconciliation instead.

BotState bankroll reconciliation utilities.

The Trade table is the durable ledger. BotState bankroll fields are derived
caches used for sizing, dashboards, and fast risk checks; when old accounting
bugs corrupt those caches, recompute them from source-of-truth data instead of
mutating or deleting historical trades.


This module will be removed in a future release.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Iterable, Optional

from sqlalchemy import case, func, update
from sqlalchemy.orm import Session

from backend.config import settings
from backend.models.audit_logger import log_audit_event
from backend.models.database import BotState, Trade

from loguru import logger

from ._bankroll_reconciliation_bankrollreconciliationreport import (
    BankrollReconciliationReport,
    PolymarketProfileTradeStats,
    _fetch_clob_pusd_balance,
    fetch_pm_open_position_value,
    fetch_pm_portfolio_value,
    fetch_pm_profile_pnl,
    fetch_pm_total_equity,
    fetch_pm_traded_count,
    get_polymarket_wallet_address,
)

from ._bankroll_reconciliation_fetch_pm_profile_trade_stats import (
    _available_bankroll_for_mode,
    _build_report,
    _initial_bankroll_for_mode,
    _mode_bankroll,
    _mode_pnl,
    _mode_trade_count,
    _mode_update_values,
    _mode_win_count,
    _open_exposure,
    _realized_trade_stats,
    _set_mode_state,
    _snapshot_state,
    fetch_pm_profile_trade_stats,
)

from ._bankroll_reconciliation_reconcile_bot_state import (
    reconcile_bot_state,
)


__all__ = [
    "BankrollReconciliationReport",
    "BotState",
    "Iterable",
    "Optional",
    "PolymarketProfileTradeStats",
    "Session",
    "Trade",
    "_available_bankroll_for_mode",
    "_build_report",
    "_fetch_clob_pusd_balance",
    "_initial_bankroll_for_mode",
    "_mode_bankroll",
    "_mode_pnl",
    "_mode_trade_count",
    "_mode_update_values",
    "_mode_win_count",
    "_open_exposure",
    "_realized_trade_stats",
    "_set_mode_state",
    "_snapshot_state",
    "asdict",
    "case",
    "dataclass",
    "datetime",
    "fetch_pm_open_position_value",
    "fetch_pm_portfolio_value",
    "fetch_pm_profile_pnl",
    "fetch_pm_profile_trade_stats",
    "fetch_pm_total_equity",
    "fetch_pm_traded_count",
    "field",
    "func",
    "get_polymarket_wallet_address",
    "log_audit_event",
    "logger",
    "reconcile_bot_state",
    "settings",
    "timezone",
    "update",
]
