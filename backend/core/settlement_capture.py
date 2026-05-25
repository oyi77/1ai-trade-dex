"""Backward-compatible shim — imports from backend.core.settlement.settlement_capture.
This module exists so that 'from backend.core.settlement_capture import X' keeps working.
"""

from backend.core.settlement.settlement_capture import *
