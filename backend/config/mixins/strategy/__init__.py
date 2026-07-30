"""Strategy params — position sizing, governance, and per-strategy settings."""
from dataclasses import dataclass

from .position_sizing import StrategyPositionSizingMixin
from .governance import StrategyGovernanceMixin
from .strategy_specific import StrategySpecificMixin


@dataclass
class StrategyParamsMixin(  # noqa: F811 — name re-export for backward compat
    StrategyPositionSizingMixin,
    StrategyGovernanceMixin,
    StrategySpecificMixin,
):
    """Aggregate strategy params mixin (all sub-mixins combined)."""
    pass


__all__ = [
    "StrategyParamsMixin",
    "StrategyPositionSizingMixin",
    "StrategyGovernanceMixin",
    "StrategySpecificMixin",
]
