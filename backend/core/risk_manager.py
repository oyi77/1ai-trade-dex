"""Backward-compatible shim — imports from backend.core.risk.risk_manager.
This module exists so that 'from backend.core.risk_manager import X' keeps working.
"""
from backend.core.risk.risk_manager import *  # noqa: F401,F403
from backend.core.risk.risk_manager import (  # noqa: F401  — private names
    _not_backfill_settlement_source,
)
