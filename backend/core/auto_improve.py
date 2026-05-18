"""Backward-compatible shim — imports from backend.core.learning.auto_improve."""
from backend.core.learning.auto_improve import *  # noqa: F401,F403
from backend.core.learning.auto_improve import (  # noqa: F401  — private names and module-level imports
    _get_current_params,
    _confidence_to_float,
    _write_outcomes_to_brain,
    _write_market_insights,
    settings,
    SessionLocal,
    ParameterOptimizer,
    get_bigbrain,
    logger,
)
