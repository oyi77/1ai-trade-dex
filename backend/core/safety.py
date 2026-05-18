"""Backward-compatible shim — imports from backend.core.risk.safety.
This module exists so that 'from backend.core.safety import X' keeps working.
"""
from backend.core.risk.safety import *  # noqa: F401,F403
