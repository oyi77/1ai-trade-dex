"""
Position Sizer — Kelly Criterion and dynamic position sizing.

Quarter-Kelly for conservative sizing.
"""

from backend.config import settings

# Hard limits
MIN_POSITION_USD = settings.POSITION_MIN_USD
MAX_POSITION_USD = settings.POSITION_MAX_USD


def kelly_criterion(
    win_rate: float, avg_win: float, avg_loss: float, kelly_fraction: float = None
) -> float:
    """
    Calculate optimal Kelly fraction.
    f* = (p * b - q) / b
    where p = win_rate, q = 1-p, b = avg_win/avg_loss

    Returns Kelly fraction (0-1). Uses settings.KELLY_FRACTION by default.
    """
    if kelly_fraction is None:
        kelly_fraction = getattr(settings, "KELLY_FRACTION", 0.25)
    if avg_loss == 0 or win_rate <= 0 or win_rate >= 1:
        return 0.0

    p = win_rate
    q = 1 - p
    b = avg_win / avg_loss

    f_star = (p * b - q) / b

    # Clamp to [0, 1] before applying quarter-Kelly
    f_star = max(0.0, min(1.0, f_star))

    return f_star * kelly_fraction


def calculate_position_size(
    capital: float,
    confidence: float,
    market_liquidity: float,
    max_slippage: float = 0.02,
    win_rate: float = 0.5,
    avg_win: float = 1.0,
    avg_loss: float = 1.0,
    kelly_fraction: float = None,
) -> float:
    """
    Position sizing accounting for Kelly, confidence, liquidity, and hard limits.

    Args:
        capital: Available capital in USD
        confidence: Signal confidence 0-1
        market_liquidity: Order book depth in USD
        max_slippage: Max acceptable slippage (default 2%)
        win_rate: Historical win rate 0-1
        avg_win: Average win multiplier
        avg_loss: Average loss multiplier
        kelly_fraction: Optional Kelly fraction override

    Returns:
        Position size in USD, clamped to [MIN_POSITION_USD, MAX_POSITION_USD]
    """
    if capital <= 0 or confidence <= 0:
        return 0.0

    # Kelly base sizing
    kelly_frac = kelly_criterion(win_rate, avg_win, avg_loss, kelly_fraction)
    base_size = capital * kelly_frac

    # Confidence discount (lower confidence = smaller size)
    confidence_multiplier = min(confidence, 1.0)
    size = base_size * confidence_multiplier

    # Liquidity discount (can't trade more than 10% of book depth)
    max_by_liquidity = market_liquidity * 0.10
    size = min(size, max_by_liquidity)

    # Slippage buffer (reduce size if slippage is high)
    if max_slippage > 0.05:  # >5% slippage = halve size
        size *= 0.5

    # Hard limits — min only applies if liquidity allows it
    if size > 0 and size < MIN_POSITION_USD:
        if max_by_liquidity >= MIN_POSITION_USD:
            size = MIN_POSITION_USD
        # else: keep size below min — liquidity is too thin for minimum trade
    size = min(size, MAX_POSITION_USD)

    return round(size, 2)
