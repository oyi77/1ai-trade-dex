"""Backward-compatible shim — imports from backend.core.risk.risk_manager_hft.
This module exists so that 'from backend.core.risk_manager_hft import X' keeps working.
"""

from backend.core.risk.risk_manager_hft import *  # noqa: F401,F403
from backend.core.risk.risk_manager_hft import (  # noqa: F401  — private names
    _cfg,
)
