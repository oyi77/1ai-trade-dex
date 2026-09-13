from __future__ import annotations

import os
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session

from loguru import logger

from backend.core.agi_types import MarketRegime, AGIGoal
from backend.models.kg_models import Base, DecisionAuditLog



from backend.core.agi_orchestrator_status import AGIStatus, AGICycleResult
from backend.core.agi_orchestrator_cycle import AGIOrchestrator
from backend.core.agi_orchestrator_errors import (
    ErrorType,
    TRANSIENT_EXCEPTIONS,
    PERMANENT_EXCEPTIONS,
    classify_exception,
    _open_circuit,
    _alert_permanent_failure,
    _record_transient_failure,
    _reset_circuit,
    _consecutive_failures,
    _circuit_open,
    _TRANSIENT_FAILURE_THRESHOLD,
    _STATS_REPORT_CRITICAL_ERRORS,
    _get_httpx_transient,
    _httpx_transient,
    _httpx_checked,
)
from backend.core.agi_orchestrator_job import agi_improvement_cycle_job
