"""Backward-compatible shim — imports from backend.core.settlement.settlement_ws.
This module exists so that 'from backend.core.settlement_ws import X' keeps working.
"""
from backend.core.settlement.settlement_ws import *  # noqa: F401,F403
