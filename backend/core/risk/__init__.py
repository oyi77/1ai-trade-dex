"""
Risk management — public API re-exports.

This module maintains backward compatibility by re-exporting all public
symbols from the internal split modules.
"""

# Models and constants
from .models import (
    RiskDecision,
    EdgeFilterError,
    DrawdownStatus,
    IMMUTABLE_SAFETY_RULES,
    _not_backfill_settlement_source,
)

# Main manager class
from .manager import RiskManager

# Sub-module public functions (for advanced use / testing)
from .validation.edge import check_edge
from .validation.drawdown import (
    check_drawdown,
    _daily_loss_exceeded,
    check_drawdown_floors,
    _get_bankroll,
)
from .breakers import (
    _breaker_enabled_for_mode,
    _validate_trade_daily_loss_breaker,
    _validate_trade_drawdown_breaker,
    _validate_trade_category_breaker,
    _check_category_circuit_breaker,
)
from .calibration import (
    _get_or_update_calibration_and_bias,
    _validate_trade_calibration,
)
from .concentration import (
    _validate_trade_concentration,
    check_concentration,
)
from .allocation import (
    _get_strategy_allocation,
    _strategy_allocation_cap,
    _validate_trade_strategy_allocation,
)
from .sidelock import (
    check_side_lock,
    _has_unsettled_trade,
)
from .confidence import (
    _get_confidence_threshold,
    _get_regime_multiplier,
)
from .apex import evaluate_apex_signal

__all__ = [
    # Models
    "RiskDecision",
    "EdgeFilterError",
    "DrawdownStatus",
    "IMMUTABLE_SAFETY_RULES",
    "_not_backfill_settlement_source",
    # Main class
    "RiskManager",
    # Sub-module functions
    "check_edge",
    "check_drawdown",
    "_daily_loss_exceeded",
    "check_drawdown_floors",
    "_get_bankroll",
    "_breaker_enabled_for_mode",
    "_validate_trade_daily_loss_breaker",
    "_validate_trade_drawdown_breaker",
    "_validate_trade_category_breaker",
    "_check_category_circuit_breaker",
    "_get_or_update_calibration_and_bias",
    "_validate_trade_calibration",
    "_validate_trade_concentration",
    "check_concentration",
    "_get_strategy_allocation",
    "_strategy_allocation_cap",
    "_validate_trade_strategy_allocation",
    "check_side_lock",
    "_has_unsettled_trade",
    "_get_confidence_threshold",
    "_get_regime_multiplier",
    "evaluate_apex_signal",
]