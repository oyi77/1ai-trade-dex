"""Trading routes - signals, trades, settlements, calibration."""

import json as _json

from fastapi import APIRouter, Depends, HTTPException, Query, Body
from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime, timedelta, timezone
from sqlalchemy.orm import Session

from backend.config import settings
from backend.models.database import (
    get_db,
    Signal,
    Trade,
    TradeAttempt,
    TradeContext,
    SettlementEvent,
    DecisionLog,
)
from backend.core.signals import scan_for_signals, TradingSignal
from backend.core.errors import handle_errors
from backend.api.auth import require_admin

from backend.api.validation import (  # noqa: E402
    SignalCreateRequest as ValidatedSignalCreateRequest,
)

router = APIRouter(tags=["trading"])

from ._trading_calibrationbucket import (  # noqa: E402  (must follow the names it imports back)
    CalibrationBucket,
    CalibrationSummary,
    CreateSignalRequest,
    SignalResponse,
    TradeResponse,
    _compute_calibration_summary,
    _signal_to_response,
    create_signal,
    get_actionable_signals,
    get_equity_curve,
    get_settlements,
    get_signals,
    get_signals_history,
    get_trades,
    settle_trades_endpoint,
    simulate_trade,
)

from ._trading_get_debate_signals import (  # noqa: E402  (must follow the names it imports back)
    _serialize_trade,
    get_debate_signals,
    get_journal,
    get_journal_stats,
    update_journal_notes,
)


__all__ = [
    "APIRouter",
    "BaseModel",
    "Body",
    "CalibrationBucket",
    "CalibrationSummary",
    "CreateSignalRequest",
    "DecisionLog",
    "Depends",
    "HTTPException",
    "List",
    "Optional",
    "Query",
    "Session",
    "SettlementEvent",
    "Signal",
    "SignalResponse",
    "Trade",
    "TradeAttempt",
    "TradeContext",
    "TradeResponse",
    "TradingSignal",
    "ValidatedSignalCreateRequest",
    "_compute_calibration_summary",
    "_json",
    "_serialize_trade",
    "_signal_to_response",
    "create_signal",
    "datetime",
    "get_actionable_signals",
    "get_db",
    "get_debate_signals",
    "get_equity_curve",
    "get_journal",
    "get_journal_stats",
    "get_settlements",
    "get_signals",
    "get_signals_history",
    "get_trades",
    "handle_errors",
    "require_admin",
    "router",
    "scan_for_signals",
    "settings",
    "settle_trades_endpoint",
    "simulate_trade",
    "timedelta",
    "timezone",
    "update_journal_notes",
]
