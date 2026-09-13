"""PolyEdge top-level orchestrator — wires together CLOB, Telegram, scheduler, and strategies."""

import asyncio
import os
from pathlib import Path
import signal
from typing import Optional, Dict

from cachetools import TTLCache

from backend.config import settings
from backend.data.polymarket_clob import (
    PolymarketCLOB,
    clob_from_settings,
    clob_breaker,
)
from backend.core.risk.risk_profiles import apply_profile, get_active_profile_name

from loguru import logger

from ._orchestrator_init import (
    OrchestratorMixin,
)

from ._orchestrator_register_activity_sources import (
    OrchestratorMixin2,
)

class Orchestrator(OrchestratorMixin, OrchestratorMixin2):
    """Top-level coordinator. Create one per process."""


from ._orchestrator_auto_execute_weather import (  # noqa: E402  (must follow the names it imports back)
    _auto_execute_weather,
    init_phase2_modules,
    main,
)


__all__ = [
    "Dict",
    "Optional",
    "OrchestratorMixin",
    "OrchestratorMixin2",
    "Path",
    "PolymarketCLOB",
    "TTLCache",
    "apply_profile",
    "asyncio",
    "clob_breaker",
    "clob_from_settings",
    "get_active_profile_name",
    "logger",
    "os",
    "settings",
    "signal",
]

if __name__ == "__main__":
    asyncio.run(main())
