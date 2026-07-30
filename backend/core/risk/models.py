"""
Risk domain models — shared types used across all validators and the manager.
"""

from dataclasses import dataclass
from typing import Optional


@dataclass
class RiskDecision:
    allowed: bool
    reason: str
    adjusted_size: float


@dataclass
class DrawdownStatus:
    daily_pnl: float
    weekly_pnl: float
    daily_limit_pct: float
    weekly_limit_pct: float
    is_breached: bool
    breach_reason: str


class EdgeFilterError(Exception):
    def __init__(
        self,
        message: str,
        market_id: str = "",
        market_price: float = 0.0,
        signal_win_rate: float = 0.0,
        edge_pp: float = 0.0,
    ):
        super().__init__(message)
        self.message = message
        self.market_id = market_id
        self.market_price = market_price
        self.signal_win_rate = signal_win_rate
        self.edge_pp = edge_pp


# Immutable Safety Rules - cannot be overridden by strategies or AI
IMMUTABLE_SAFETY_RULES = {
    "max_total_exposure": {
        "default": 0.95,
        "override_env_var": "MAX_TOTAL_EXPOSURE_FRACTION",
        "description": "Never exceed 95% of bankroll in total exposure",
    },
    "max_single_strategy_pct": {
        "default": 0.25,
        "override_env_var": "MAX_SINGLE_STRATEGY_PCT",
        "description": "No strategy can exceed 25% of total capital allocation",
    },
    "daily_loss_floor": {
        "default": -0.10,
        "override_env_var": "DAILY_LOSS_FLOOR_PCT",
        "description": "All strategies pause for 24h if daily PnL < -10% of bankroll",
    },
    "weekly_loss_floor": {
        "default": -0.20,
        "override_env_var": "WEEKLY_LOSS_FLOOR_PCT",
        "description": "Revert to PAPER mode for 7 days if weekly PnL < -20% of bankroll",
    },
    "new_strategy_ramp_pct": {
        "default": 0.01,
        "override_env_var": "NEW_STRATEGY_RAMP_PCT",
        "description": "New strategies start at 1% allocation",
    },
    "new_strategy_min_trades": {
        "default": 20,
        "override_env_var": "NEW_STRATEGY_MIN_TRADES",
        "description": "Scale only after 20 profitable trades",
    },
    "min_archetype_diversity": {
        "default": 5,
        "override_env_var": "MIN_ARCHETYPE_DIVERSITY",
        "description": "At least 5 different archetypes must be active",
    },
    "emergency_kill_switch": {
        "default": True,
        "override_env_var": None,
        "description": "Single API call stops all trading immediately",
    },
    "audit_trail": {
        "default": True,
        "override_env_var": None,
        "description": "Every mutation/kill/promotion logged immutably",
    },
}
