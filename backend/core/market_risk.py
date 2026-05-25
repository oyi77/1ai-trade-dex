"""Backward-compatible shim — imports from backend.core.risk.market_risk.
This module exists so that 'from backend.core.market_risk import X' keeps working.
"""

from backend.core.risk.market_risk import *
