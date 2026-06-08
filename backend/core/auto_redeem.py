"""Backward-compatible shim — imports from backend.core.settlement.auto_redeem.
This module exists so that 'from backend.core.auto_redeem import X' keeps working.
"""

from backend.core.settlement.auto_redeem import *  # noqa: F403
