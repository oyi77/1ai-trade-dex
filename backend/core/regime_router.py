"""RegimeConfidenceRouter - placeholder for regime-based confidence multipliers."""

from typing import Optional


class RegimeConfidenceRouter:
    """Placeholder implementation for regime-based confidence multipliers.
    
    This will be fully implemented in Task 28. For now, it provides
    a simple interface that returns predefined multipliers for testing.
    """
    
    def __init__(self):
        # Predefined multipliers for testing (will be dynamic in full implementation)
        self._multipliers = {
            "BTC Momentum": 1.25,  # Volatile regime
            "Market Maker": 0.85,  # Sideways regime
            # Default multiplier for unknown strategies
        }
    
    def get_multiplier(self, strategy_name: str) -> float:
        """Get confidence multiplier for a strategy based on current regime.
        
        Args:
            strategy_name: Name of the trading strategy
            
        Returns:
            Multiplier to apply to base confidence threshold (1.0 = no change)
        """
        # Return predefined multiplier or default to 1.0 for unknown strategies
        return self._multipliers.get(strategy_name, 1.0)


# Singleton instance for easy access
regime_router = RegimeConfidenceRouter()