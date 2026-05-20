"""
Arbitrage Executor for PolyEdge.

Detects three classes of arbitrage opportunities:
  - intra_market:    YES + NO prices sum to less than 1 minus fees
  - cross_platform:  price discrepancy between Polymarket and Kalshi
  - negrisk:         sum of YES prices across mutually exclusive outcomes != 1
"""

from dataclasses import dataclass, field
from typing import Optional

from backend.config import settings


def _cfg(name, default):
    return getattr(settings, name, default)


@dataclass
class ArbOpportunity:
    arb_type: str  # "intra_market", "cross_platform", "negrisk"
    market_id: str
    spread: float  # profit spread after fees
    max_size: float  # max profitable trade size in USD
    details: dict = field(default_factory=dict)


def detect_intra_market_arb(
    yes_price: float,
    no_price: float,
    fee_rate: float = None,
    market_id: str = "unknown",
    max_size: float = settings.ARB_EXECUTOR_MAX_SIZE,
) -> Optional[ArbOpportunity]:
    if fee_rate is None:
        fee_rate = _cfg("ARB_DEFAULT_FEE_RATE", 0.02)
    """
    Detect YES/NO intra-market arbitrage.

    If YES + NO < (1 - 2*fee_rate), buying both sides guarantees profit.
    The spread is the net edge after paying fees on both legs.
    """
    total = yes_price + no_price
    threshold = 1.0 - 2 * fee_rate
    if total >= threshold:
        return None

    spread = threshold - total  # net profit per dollar wagered
    return ArbOpportunity(
        arb_type="intra_market",
        market_id=market_id,
        spread=spread,
        max_size=max_size,
        details={
            "yes_price": yes_price,
            "no_price": no_price,
            "total": total,
            "fee_rate": fee_rate,
            "threshold": threshold,
        },
    )


def detect_cross_platform_arb(
    poly_price: float,
    kalshi_price: float,
    min_spread: float = None,
    market_id: str = "unknown",
    fee_rate: float = None,
    max_size: float = settings.ARB_EXECUTOR_MAX_SIZE,
) -> Optional[ArbOpportunity]:
    if min_spread is None:
        min_spread = _cfg("ARB_DEFAULT_MIN_SPREAD", 0.03)
    if fee_rate is None:
        fee_rate = _cfg("ARB_DEFAULT_FEE_RATE", 0.02)
    """
    Detect cross-platform arbitrage between Polymarket and Kalshi.

    If the absolute price difference exceeds min_spread after fees,
    buy the cheaper side and sell (or buy NO on) the more expensive side.
    """
    raw_spread = abs(poly_price - kalshi_price)
    net_spread = raw_spread - 2 * fee_rate  # pay fees on both legs

    if net_spread <= min_spread:
        return None

    cheaper_platform = "kalshi" if kalshi_price < poly_price else "polymarket"
    return ArbOpportunity(
        arb_type="cross_platform",
        market_id=market_id,
        spread=net_spread,
        max_size=max_size,
        details={
            "poly_price": poly_price,
            "kalshi_price": kalshi_price,
            "raw_spread": raw_spread,
            "net_spread": net_spread,
            "fee_rate": fee_rate,
            "buy_on": cheaper_platform,
        },
    )


def detect_negrisk_arb(
    outcome_prices: list[float],
    fee_rate: float = None,
    market_id: str = "unknown",
    max_size: float = settings.ARB_EXECUTOR_MAX_SIZE,
    min_deviation: float = settings.ARB_EXECUTOR_MIN_DEVIATION,
) -> Optional[ArbOpportunity]:
    if fee_rate is None:
        fee_rate = _cfg("ARB_DEFAULT_FEE_RATE", 0.02)
    """
    Detect neg-risk arbitrage across mutually exclusive outcomes.

    In a properly priced market the YES prices across all mutually exclusive
    outcomes should sum to 1.0. When the sum deviates sufficiently from 1.0
    (after accounting for fees on each leg), a riskless trade exists.

    sum < 1.0: buy all YES outcomes — guaranteed payout of 1.0
    sum > 1.0: sell (buy NO on) all YES outcomes — net credit > cost
    """
    if len(outcome_prices) < 2:
        return None

    price_sum = sum(outcome_prices)
    deviation = abs(price_sum - 1.0)
    total_fees = fee_rate * len(outcome_prices)
    profit_after_fees = deviation - total_fees

    if profit_after_fees <= min_deviation:
        return None

    direction = "buy_all_yes" if price_sum < 1.0 else "sell_all_yes"
    return ArbOpportunity(
        arb_type="negrisk",
        market_id=market_id,
        spread=profit_after_fees,
        max_size=max_size,
        details={
            "outcome_prices": outcome_prices,
            "num_outcomes": len(outcome_prices),
            "price_sum": price_sum,
            "deviation": deviation,
            "total_fees": total_fees,
            "profit_after_fees": profit_after_fees,
            "direction": direction,
            "fee_rate": fee_rate,
        },
    )
