"""Backward-compatible shim — imports from backend.core.risk.crash_guardian.
This module exists so that 'from backend.core.crash_guardian import X' keeps working.
"""
from backend.core.risk.crash_guardian import *  # noqa: F401,F403
