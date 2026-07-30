"""Position sizing and trading limits."""
import os
from dataclasses import dataclass
from typing import Optional


@dataclass
class StrategyPositionSizingMixin:
    """Position sizing, trading limits, and signal weights."""

    # --------------------------------------------------------------------------
    # Trading parameters
    # --------------------------------------------------------------------------
    MIN_DEBATE_EDGE: float = 0.04  # debate threshold
    MIN_EDGE_THRESHOLD: float = 0.03  # minimum edge for signals
    MIN_EDGE_PP: float = 0.0  # minimum edge in percentage points for risk_manager
    MAX_ENTRY_PRICE: float = 0.80  # maximum entry price
    MAX_TRADES_PER_WINDOW: int = 20  # trades per scheduling window
    MAX_TRADES_PER_SCAN: int = 10  # trades per scan cycle
    AUTO_TRADER_BATCH_SIZE: int = 100  # batch size for auto-trader
    MAX_TOTAL_PENDING_TRADES: int = 50  # max pending trades
    STALE_TRADE_HOURS: int = 24  # hours before trade considered stale

    # Position sizing
    KELLY_FRACTION: float = 0.10  # Kelly fraction (0.10 = 10% Kelly)
    MAX_POSITION_FRACTION: float = 0.30  # max position as % of bankroll
    MAX_TOTAL_EXPOSURE_FRACTION: float = 0.70  # max total exposure
    CORRELATION_MULTIPLIER: float = (
        1.0  # same-category exposure multiplier (1.0=no inflation)
    )
    MAX_CORRELATED_EXPOSURE_PCT: float = (
        0.80  # max correlation-adjusted exposure % of bankroll
    )
    MAX_TRADE_SIZE: float = 100.0  # max single trade size in USD
    MIN_ORDER_USDC: float = 1.0  # minimum order size (CLOB minimum)
    PAPER_MIN_ORDER_USDC: float = (
        5.0  # minimum order size (paper — matches CLOB $5 minimum)
    )

    # Confidence and signal weights
    AUTO_APPROVE_MIN_CONFIDENCE: float = float(
        os.getenv("AUTO_APPROVE_MIN_CONFIDENCE", "0.25")
    )
    PAPER_AUTO_APPROVE_MIN_CONFIDENCE: float = float(
        os.getenv("PAPER_AUTO_APPROVE_MIN_CONFIDENCE", "0.20")
    )
    AI_SIGNAL_WEIGHT: float = 0.30  # AI weight in ensemble (max 0.50)
    LONGSHOT_NO_BIAS_WEIGHT: float = 0.10  # bias weight for longshot markets

    # Longshot Bias Strategy
    LONGSHOT_BIAS_MAX_PRICE: float = 0.30  # only trade below 30c
    LONGSHOT_BIAS_MIN_EV: float = 0.05  # minimum expected value
    LONGSHOT_BIAS_MAX_POSITION_USD: float = 20.0  # max position in USD
    LONGSHOT_BIAS_ENABLED: bool = False  # start disabled

    # Indicator weights (must sum to ~1.0)
    WEIGHT_RSI: float = 0.20
    WEIGHT_MOMENTUM: float = 0.35
    WEIGHT_VWAP: float = 0.20
    WEIGHT_SMA: float = 0.15
    WEIGHT_MARKET_SKEW: float = 0.10

    # Volume filters
    MIN_MARKET_VOLUME: float = 100.0  # minimum market volume
    MIN_WHALE_TRADE_USD: float = 1000.0  # minimum whale trade size
