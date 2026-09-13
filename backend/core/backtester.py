"""Backtesting engine — simulate strategy execution against historical market data."""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from loguru import logger
from sqlalchemy.orm import Session

from backend.core.learning.calibration import kelly_fraction
from backend.models.database import SessionLocal, Signal, Trade

from ._backtester_backtestconfig import (
    BacktestConfig,
    BacktestResult,
    BacktestTrade,
)

from ._backtester_backtestengine import (
    BacktestEngine,
)


__all__ = [
    "Any",
    "BacktestConfig",
    "BacktestEngine",
    "BacktestResult",
    "BacktestTrade",
    "Session",
    "SessionLocal",
    "Signal",
    "Trade",
    "dataclass",
    "date",
    "datetime",
    "kelly_fraction",
    "logger",
    "math",
    "statistics",
]
