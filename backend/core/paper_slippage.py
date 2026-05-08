"""
Paper trading slippage simulator for realistic fill simulation.

Simulates Polymarket CLOB fees, slippage, and liquidity constraints
for paper trading mode to make PnL more realistic.

Settings are read with priority: SystemSettings DB > app_settings > default.
The DB check enables cross-process config changes (API writes SystemSettings,
bot process reads them on next fill).
"""

import logging
import math
import random
from typing import Any, Literal, Optional
from sqlalchemy.orm import Session
from backend.config import settings as app_settings

logger = logging.getLogger("trading_bot")


class PaperSlippageSimulator:
    """Simulates realistic slippage, fees, and liquidity for paper trades."""

    def __init__(self):
        pass

    @staticmethod
    def _get_setting(key: str, default: Any, db: Optional[Session] = None) -> Any:
        """
        Read a setting with priority: SystemSettings DB > app_settings > default.

        This enables cross-process runtime configuration — when the API process
        writes a value to SystemSettings, the bot process picks it up on the next
        simulate_fill() call without restart.
        """
        # Try SystemSettings DB first (authoritative source for runtime changes)
        if db is not None:
            try:
                from backend.models.database import SystemSettings
                row = db.query(SystemSettings).filter(SystemSettings.key == key).first()
                if row is not None:
                    val = row.value
                    # Coerce to match default type
                    if isinstance(default, bool):
                        return str(val).lower() in ("true", "1", "yes") if isinstance(val, str) else bool(val)
                    elif isinstance(default, float):
                        return float(val)
                    elif isinstance(default, int):
                        return int(float(val))
                    return val
            except Exception as e:
                logger.debug(f"SystemSettings read failed for {key}: {e}")

        # Fall back to app_settings (in-memory, set at startup from .env)
        val = getattr(app_settings, key, None)
        if val is not None:
            if isinstance(default, bool):
                return str(val).lower() in ("true", "1", "yes") if isinstance(val, str) else bool(val)
            elif isinstance(default, float):
                return float(val)
            elif isinstance(default, int):
                return int(float(val))
            return val

        return default

    def simulate_fill(
        self,
        entry_price: float,
        size: float,
        direction: Literal["BUY", "SELL"],
        market_ticker: str = "",
        orderbook_depth_usd: float = 0,
        db: Optional[Session] = None
    ) -> dict:
        """
        Simulate a paper trade fill with realistic conditions.

        Args:
            entry_price: Theoretical entry price (mid price)
            size: Trade size in USD
            direction: "BUY" or "SELL"
            market_ticker: Market identifier for logging
            orderbook_depth_usd: Estimated orderbook depth in USD (optional)
            db: Optional DB session for reading SystemSettings (cross-process config)

        Returns:
            dict with: fill_price, slippage_bps, fee_usd, effective_size, rejected, rejection_reason
        """
        # Read all settings at call time (enables runtime configuration changes)
        base_slippage_bps = float(self._get_setting("PAPER_SLIPPAGE_BPS", 0.0, db))
        min_slippage_bps = float(self._get_setting("PAPER_MIN_SLIPPAGE_BPS", 5.0, db))
        size_impact_factor = float(self._get_setting("PAPER_SIZE_IMPACT_FACTOR", 0.5, db))
        clob_fee_rate = float(self._get_setting("PAPER_CLOB_FEE_RATE", 0.02, db))
        min_depth_usd = float(self._get_setting("PAPER_MIN_DEPTH_USD", 0.0, db))
        random_slippage = bool(self._get_setting("PAPER_RANDOM_SLIPPAGE", False, db))

        # If slippage simulation disabled (base_slippage_bps=0), return original fill
        if base_slippage_bps == 0:
            return {
                "fill_price": entry_price,
                "slippage_bps": 0.0,
                "fee_usd": 0.0,
                "effective_size": size,
                "rejected": False,
                "rejection_reason": ""
            }

        # Check liquidity constraints
        if min_depth_usd > 0 and orderbook_depth_usd < min_depth_usd:
            return {
                "fill_price": entry_price,
                "slippage_bps": 0.0,
                "fee_usd": 0.0,
                "effective_size": 0.0,
                "rejected": True,
                "rejection_reason": "INSUFFICIENT_LIQUIDITY"
            }

        # Calculate slippage based on size impact
        # Larger orders experience more slippage (logarithmic relationship)
        size_impact = size_impact_factor * math.log(max(1, size / 100))
        slippage_bps = max(min_slippage_bps, base_slippage_bps * (1 + size_impact))

        # Add random jitter if enabled
        if random_slippage:
            jitter = random.uniform(0.8, 1.2)  # ±20% variation
            slippage_bps *= jitter

        # Apply slippage based on direction
        slippage_factor = slippage_bps / 10000  # Convert bps to decimal
        if direction == "BUY":
            fill_price = entry_price * (1 + slippage_factor)
        else:  # SELL
            fill_price = entry_price * (1 - slippage_factor)

        # Clamp price to Polymarket bounds [0.01, 0.99]
        fill_price = max(0.01, min(0.99, fill_price))

        # Estimate CLOB fee (2% of expected profit,
        # For simplicity, we assume a worst-case scenario where the trade goes to 1.0
        expected_profit = size * (1.0 - fill_price) if direction == "BUY" else size * fill_price
        fee_usd = max(expected_profit * clob_fee_rate, size * 0.001)

        return {
            "fill_price": fill_price,
            "slippage_bps": slippage_bps,
            "fee_usd": fee_usd,
            "effective_size": size,
            "rejected": False,
            "rejection_reason": ""
        }


# Module-level singleton instance
_simulator_instance = None


def get_simulator() -> PaperSlippageSimulator:
    """Get the singleton PaperSlippageSimulator instance."""
    global _simulator_instance
    if _simulator_instance is None:
        _simulator_instance = PaperSlippageSimulator()
    return _simulator_instance
