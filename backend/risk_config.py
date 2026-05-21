"""Single source of truth for risk parameters.
Import from here instead of hardcoding in strategies, backtests, or risk managers.
"""

# Position Sizing
DEFAULT_KELLY_FRACTION = 0.25
MAX_KELLY_FRACTION = 0.50
DEFAULT_MAX_POSITION_USD = 50.0
DEFAULT_MAX_DAILY_LOSS_USD = 100.0

# Drawdown
DEFAULT_MAX_DRAWDOWN_PCT = 0.20
TERMINAL_DRAWDOWN_PCT = 0.50

# Bankroll
INITIAL_BANKROLL = 1000.0

# Circuit Breaker
CB_DEFAULT_FAILURE_THRESHOLD = 5
CB_DEFAULT_RECOVERY_TIMEOUT = 60.0

# Learning
MAX_PARAM_CHANGE_FRACTION = 0.30
ROLLBACK_DEGRADATION_THRESHOLD = 0.15
