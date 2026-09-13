"""WorkflowMixin — main promotion loop and strategy lifecycle management."""

from __future__ import annotations

import json as _json
from datetime import datetime, timezone, timedelta
from typing import Optional

from sqlalchemy.orm import Session

from backend.config import settings
from backend.models.database import StrategyConfig, GenomeRegistry, StrategyProposal
from backend.models.kg_models import ExperimentRecord
from backend.core.experiment_runner import ExperimentRunner
from backend.core.agi_types import ExperimentStatus
from backend.core.event_bus import publish_event
from backend.core.strategy_health import disable_for_rehab, StrategyHealthMonitor
from backend.core.forensics_integration import generate_forensics_proposals
from backend.core.safe_param_tuner import SafeParamTuner
from backend.db.utils import utcnow, get_db_session

from loguru import logger

from ._workflow_init import (
    WorkflowMixinMixin,
)

from ._workflow_run_demotion_cycle import (
    WorkflowMixinMixin2,
)

from ._workflow_trigger_improvement_loop import (
    WorkflowMixinMixin3,
)

class WorkflowMixin(WorkflowMixinMixin, WorkflowMixinMixin2, WorkflowMixinMixin3):
    """Mixin providing __init__, run_once, strategy enable/disable, and improvement loop."""


__all__ = [
    "ExperimentRecord",
    "ExperimentRunner",
    "ExperimentStatus",
    "GenomeRegistry",
    "Optional",
    "SafeParamTuner",
    "Session",
    "StrategyConfig",
    "StrategyHealthMonitor",
    "StrategyProposal",
    "WorkflowMixinMixin",
    "WorkflowMixinMixin2",
    "WorkflowMixinMixin3",
    "_json",
    "datetime",
    "disable_for_rehab",
    "generate_forensics_proposals",
    "get_db_session",
    "logger",
    "publish_event",
    "settings",
    "timedelta",
    "timezone",
    "utcnow",
]
