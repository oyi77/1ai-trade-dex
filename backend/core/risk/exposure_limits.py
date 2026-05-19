"""
Exposure Limits — Pre-trade validation checklist.

Validates trades against portfolio-level limits before execution.
"""
from dataclasses import dataclass
from typing import Tuple


@dataclass
class TradeConfig:
    """Proposed trade configuration."""
    market_id: str
    category: str
    size_usd: float
    side: str  # "BUY" or "SELL"
    outcome: str  # "YES" or "NO"


@dataclass
class PortfolioState:
    """Current portfolio state for validation."""
    free_capital: float = 0.0
    open_positions: int = 0
    max_open_positions: int = 5
    positions_in_market: int = 0
    max_per_market: int = 2
    category_exposure_pct: float = 0.0  # ratio 0-1 of bankroll in this category
    max_category_pct: float = 0.60  # 60% max in single category (ratio 0-1)
    daily_loss_usd: float = 0.0
    max_daily_loss_usd: float = 100.0
    trading_hours_allowed: bool = True
    min_position_usd: float = 5.0
    max_position_usd: float = 50.0


def validate_trade(trade: TradeConfig, portfolio: PortfolioState) -> Tuple[bool, str]:
    """
    Pre-trade validation checklist.

    Returns (is_valid, reason).
    """
    # Capital check
    if trade.size_usd > portfolio.free_capital:
        return False, f"Insufficient capital: need ${trade.size_usd:.2f}, have ${portfolio.free_capital:.2f}"

    # Position limit
    if portfolio.open_positions >= portfolio.max_open_positions:
        return False, f"Max open positions reached: {portfolio.open_positions}/{portfolio.max_open_positions}"

    # Market limit
    if portfolio.positions_in_market >= portfolio.max_per_market:
        return False, f"Max positions in market reached: {portfolio.positions_in_market}/{portfolio.max_per_market}"

    # Category limit (category_exposure_pct and max_category_pct both as ratio 0-1)
    if portfolio.category_exposure_pct >= portfolio.max_category_pct:
        return False, f"Category exposure too high: {portfolio.category_exposure_pct:.1%} >= {portfolio.max_category_pct:.0%}"

    # Daily loss limit
    if abs(portfolio.daily_loss_usd) >= portfolio.max_daily_loss_usd:
        return False, f"Daily loss limit reached: ${abs(portfolio.daily_loss_usd):.2f} >= ${portfolio.max_daily_loss_usd:.2f}"

    # Trading hours
    if not portfolio.trading_hours_allowed:
        return False, "Outside allowed trading hours"

    # Size limits
    if trade.size_usd < portfolio.min_position_usd:
        return False, f"Position too small: ${trade.size_usd:.2f} < ${portfolio.min_position_usd:.2f}"

    if trade.size_usd > portfolio.max_position_usd:
        return False, f"Position too large: ${trade.size_usd:.2f} > ${portfolio.max_position_usd:.2f}"

    return True, "OK"
