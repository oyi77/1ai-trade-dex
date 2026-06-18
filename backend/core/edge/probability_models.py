"""Probability models for binary option fair-value estimation.

Implements Brownian bridge and near-resolution models for computing
time-decay-aware fair-value on Polymarket binary options.
"""

from __future__ import annotations

import math
from abc import ABC, abstractmethod
from datetime import timedelta

from backend.core.edge.edge_types import ProbabilityEstimate, MarketSnapshot


def clamp(value: float, lo: float, hi: float) -> float:
    """Clamp a value between lo and hi."""
    return max(lo, min(hi, value))


class ProbabilityModel(ABC):
    """Base class for probability estimation models."""

    @abstractmethod
    async def estimate_probability(
        self,
        snapshot: MarketSnapshot,
        market_price: float,
        time_to_resolution: timedelta,
    ) -> ProbabilityEstimate | None:
        """Estimate true probability for a binary option.

        Returns None if this model doesn't apply to the given market.
        """


class BrownianBridgeModel(ProbabilityModel):
    """Time-decay aware probability model for binary options.

    Uses a Brownian bridge to model probability drift toward resolution.
    Key insight: binary options near resolution with high certainty have
    predictable price paths (theta decay). Far from resolution, the
    bridge model adjusts probability toward 0.5 (uncertainty increases
    with time).
    """

    def __init__(self, volatility_source: str = "market"):
        self.volatility_source = volatility_source

    async def estimate_probability(
        self,
        snapshot: MarketSnapshot,
        market_price: float,
        time_to_resolution: timedelta,
    ) -> ProbabilityEstimate | None:
        T_hours = time_to_resolution.total_seconds() / 3600

        # Skip very short timeframes (market price ≈ true probability)
        if T_hours < 0.5:
            return None

        T_years = time_to_resolution.total_seconds() / (365.25 * 24 * 3600)
        sigma = self._estimate_volatility(snapshot, market_price)

        # Near resolution (< 1 hour): high confidence, price ≈ probability
        if T_hours < 1.0:
            return ProbabilityEstimate(
                probability=clamp(market_price, 0.01, 0.99),
                confidence=0.90,
                model_name="brownian_bridge",
                time_to_resolution_hours=T_hours,
                metadata={"sigma": sigma, "T_years": T_years, "regime": "near_resolution"},
            )

        # Brownian bridge: pull probability toward 0.5 proportionally to
        # sqrt(T) * sigma (uncertainty increases with time)
        if market_price <= 0.01 or market_price >= 0.99:
            # Extreme prices: bridge has minimal effect
            adjusted_prob = market_price
        else:
            logit_p = math.log(market_price / (1 - market_price))
            # Bridge adjustment: shrink logit toward 0 (0.5 probability)
            # as time increases — more time = more uncertainty
            shrinkage = 1 + sigma * math.sqrt(max(T_years, 1e-10))
            adjusted_logit = logit_p / shrinkage
            adjusted_prob = 1 / (1 + math.exp(-adjusted_logit))

        # Confidence decreases with time and volatility
        confidence = clamp(1.0 - sigma * math.sqrt(max(T_years, 1e-10)) * 2, 0.1, 0.95)

        return ProbabilityEstimate(
            probability=clamp(adjusted_prob, 0.01, 0.99),
            confidence=confidence,
            model_name="brownian_bridge",
            time_to_resolution_hours=T_hours,
            metadata={"sigma": sigma, "T_years": T_years, "shrinkage": shrinkage if market_price > 0.01 and market_price < 0.99 else 1.0},
        )

    def _estimate_volatility(self, snapshot: MarketSnapshot, market_price: float) -> float:
        """Estimate probability volatility (sigma) for the bridge model.

        Uses spread as a proxy for market uncertainty:
        - Wide spread → high volatility
        - Narrow spread → low volatility
        - Also factors in price level (extreme prices have lower sigma)
        """
        # Spread-based volatility estimate
        spread_vol = snapshot.spread * 2 if snapshot.spread > 0 else 0.05

        # Price-level adjustment: extreme prices are more stable
        price_factor = 4 * market_price * (1 - market_price)  # max at 0.5

        # Combine: higher spread + moderate price = higher volatility
        sigma = clamp(spread_vol * (0.3 + 0.7 * price_factor), 0.02, 0.50)

        return sigma


class NearResolutionModel(ProbabilityModel):
    """For markets within hours of resolution.

    High-confidence model: if market price > threshold with limited time
    remaining, probability of that outcome resolving is very high.
    Market slightly underprices near-certain outcomes due to risk premium.
    """

    def __init__(
        self,
        min_hours: float = 1.0,
        max_hours: float = 72.0,
        min_price: float = 0.85,
    ):
        self.min_hours = min_hours
        self.max_hours = max_hours
        self.min_price = min_price

    async def estimate_probability(
        self,
        snapshot: MarketSnapshot,
        market_price: float,
        time_to_resolution: timedelta,
    ) -> ProbabilityEstimate | None:
        hours = time_to_resolution.total_seconds() / 3600

        # Only applies to markets within the time window
        if not (self.min_hours <= hours <= self.max_hours):
            return None

        if market_price > self.min_price:
            # YES is likely — market underprices near-certain outcomes
            # Small upward adjustment reflecting resolution certainty
            prob = market_price + (1 - market_price) * 0.1
            # More time = less certainty
            confidence = 0.7 + 0.3 * (1 - hours / self.max_hours)
        elif market_price < (1 - self.min_price):
            # NO is likely — symmetric to YES case
            prob = market_price - market_price * 0.1
            confidence = 0.7 + 0.3 * (1 - hours / self.max_hours)
        else:
            # Uncertain for 50/50 markets near resolution
            prob = market_price
            confidence = 0.3

        return ProbabilityEstimate(
            probability=clamp(prob, 0.01, 0.99),
            confidence=clamp(confidence, 0.1, 0.99),
            model_name="near_resolution",
            time_to_resolution_hours=hours,
            metadata={"hours_to_resolution": hours, "regime": "near_resolution"},
        )
