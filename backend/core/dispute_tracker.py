"""Backward-compatible shim — imports from backend.core.settlement.dispute_tracker.
This module exists so that 'from backend.core.dispute_tracker import X' keeps working.
"""

from backend.core.settlement.dispute_tracker import *
