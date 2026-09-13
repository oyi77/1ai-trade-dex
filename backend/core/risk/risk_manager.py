"""

Risk manager — validates trades against position size, exposure, drawdown, and confidence rules.

This module will be removed in a future release.
"""

import json
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple

from contextlib import nullcontext
from backend.config import settings
from backend.db.utils import get_db_session
from backend.models.database import Trade, BotState, for_update
from backend.monitoring.hft_metrics import record_signal, db_query_duration
from backend.monitoring.metrics import increment_risk_rejection
from backend.core.risk.correlation_monitor import CorrelationMonitor
from sqlalchemy import func, or_

from loguru import logger



from backend.core.risk._risk_manager_types import (
    RiskDecision,
    EdgeFilterError,
    DrawdownStatus,
    IMMUTABLE_SAFETY_RULES,
    _not_backfill_settlement_source,
)
from backend.core.risk._risk_manager_core import RiskManagerCoreMixin
from backend.core.risk._risk_manager_validation import RiskManagerValidationMixin
from backend.core.risk._risk_manager_drawdown import RiskManagerDrawdownMixin
from backend.core.risk._risk_manager_limits import RiskManagerLimitsMixin
from backend.core.risk._risk_manager_apex import RiskManagerApexMixin


class RiskManager(
    RiskManagerCoreMixin,
    RiskManagerValidationMixin,
    RiskManagerDrawdownMixin,
    RiskManagerLimitsMixin,
    RiskManagerApexMixin,
):
    """Pre-trade risk validation — composed from focused mixins."""
