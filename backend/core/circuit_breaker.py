"""Backward-compatible shim — imports from backend.core.risk.circuit_breaker.
This module exists so that 'from backend.core.circuit_breaker import X' keeps working.
"""

from backend.core.risk.circuit_breaker import *  # noqa: F403
