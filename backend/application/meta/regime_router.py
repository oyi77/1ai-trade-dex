"""Regime-Aware Confidence Router - Phase G Gap G2/G6

Adjusts confidence thresholds based on detected market regime.
Different strategies perform better in different regimes.
"""

from typing import Dict

from backend.config import settings

from loguru import logger


class RegimeConfidenceRouter:
    """Routes confidence thresholds based on current market regime.

    Each strategy has regime-specific multipliers that adjust its
    base confidence threshold. This allows strategies to be more
    aggressive in favorable regimes and more conservative in unfavorable ones.
    """

    # Regime multipliers per strategy
    # Lower multiplier = higher threshold (more conservative)
    # Higher multiplier = lower threshold (more aggressive)
    REGIME_MULTIPLIERS: Dict[str, Dict[str, float]] = {
        "bull": {
            "BTC Momentum": 0.90,      # More conservative in bull markets
            "Market Maker": 1.10,      # More aggressive in bull markets
            "__default__": 1.00
        },
        "bear": {
            "BTC Momentum": 1.15,      # More aggressive in bear markets
            "Market Maker": 0.90,      # More conservative in bear markets
            "__default__": 1.05
        },
        "volatile": {
            "BTC Momentum": 1.25,      # More aggressive in volatile markets
            "Market Maker": 1.30,      # More aggressive in volatile markets
            "__default__": 1.15
        },
        "sideways": {
            "BTC Momentum": 1.10,      # Slightly more aggressive in sideways
            "Market Maker": 0.85,      # More conservative in sideways
            "__default__": 1.00
        },
        "event_dense": {
            "News Catalyst": 0.85,      # More conservative during events
            "Event Catalyst": 0.85,    # More conservative during events
            "__default__": 1.05
        },
    }

    def __init__(self):
        """Initialize the regime router."""
        self.regime_detector = None  # Will be injected or initialized

    def get_multiplier(self, strategy_name: str) -> float:
        """Get regime multiplier for a specific strategy.

        Args:
            strategy_name: Name of the strategy

        Returns:
            Multiplier to apply to base confidence threshold
        """
        regime = self._get_current_regime()
        regime_map = self.REGIME_MULTIPLIERS.get(regime, {})
        return regime_map.get(strategy_name, regime_map.get("__default__", 1.00))

    def get_adjusted_threshold(self, strategy_name: str, base_threshold: float) -> float:
        """Calculate regime-adjusted confidence threshold.

        Args:
            strategy_name: Name of the strategy
            base_threshold: Base confidence threshold (0-1)

        Returns:
            Adjusted threshold capped at 0.95 maximum
        """
        multiplier = self.get_multiplier(strategy_name)
        adjusted = base_threshold * multiplier

        # Cap at 0.95 to prevent overconfidence
        return min(adjusted, 0.95)

    def _get_current_regime(self) -> str:
        """Get current market regime from detector or settings.

        Returns:
            Current regime as string (e.g., 'bull', 'bear', 'sideways')
        """
        # If regime routing is disabled, return a neutral default
        if not settings.REGIME_ROUTING_ENABLED:
            return "sideways"

        # Use regime detector if available
        if self.regime_detector is not None:
            result = self.regime_detector.detect_regime({})
            return result.regime.value if result.regime else "unknown"

        # Fallback to unknown
        return "unknown"
