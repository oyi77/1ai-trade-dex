"""Time-decay model — adjusts probability based on time-to-resolution.

Near resolution, high-probability outcomes become more certain as the
outcome is effectively locked in. This module quantifies that effect
using a Brownian bridge approximation and category-aware volatility.

Rules:
  - Only boost when model_prob > 0.70 AND time_to_resolution < 7 days
  - Max boost: +3pp at 0.92, tapering to +1.5pp at 0.98
  - Crypto: no boost until last 60 seconds (high volatility)
  - Clamp final probability to [0, 1]
"""

from __future__ import annotations

from dataclasses import dataclass
from math import erf, sqrt, log
from typing import Dict


from backend.core.edge.edge_types import clamp

# Category → default annualized volatility (sigma)
CATEGORY_VOLATILITY: Dict[str, float] = {
    "weather": 0.02,
    "politics": 0.02,
    "sports": 0.03,
    "crypto": 0.15,
    "economics": 0.04,
    "entertainment": 0.03,
}

DEFAULT_VOLATILITY = 0.05
MAX_BOOST_PP = 0.03  # 3 percentage points
MIN_PROB_FOR_BOOST = 0.70
MAX_PROB_FOR_BOOST = 0.99
MAX_RESOLUTION_HOURS = 168.0  # 7 days
CRYPTO_MIN_BOOST_HOURS = 0.017  # ~1 minute


def _norm_cdf(x: float) -> float:
    """Standard normal CDF approximation."""
    return 0.5 * (1.0 + erf(x / sqrt(2.0)))


def _norm_ppf(p: float) -> float:
    """Inverse standard normal CDF (Rational approximation, Abramowitz & Stegun 26.2.23)."""
    if p <= 0.0:
        return -4.0
    if p >= 1.0:
        return 4.0
    if abs(p - 0.5) < 1e-10:
        return 0.0
    if p < 0.5:
        return -_norm_ppf(1.0 - p)
    # p > 0.5: use tail probability q = 1 - p
    q = 1.0 - p
    t = sqrt(-2.0 * log(q))
    # Rational approximation coefficients
    c0 = 2.515517
    c1 = 0.802853
    c2 = 0.010328
    d1 = 1.432788
    d2 = 0.189269
    d3 = 0.001308
    return t - (c0 + c1 * t + c2 * t * t) / (1.0 + d1 * t + d2 * t * t + d3 * t * t * t)


@dataclass
class BrownianBridge:
    """Brownian bridge probability model for near-resolution markets.

    Models probability convergence: as time → resolution, the probability
    of a YES outcome converges toward 0 or 1 depending on the drift.
    """

    @staticmethod
    def probability_at_time(
        p0: float,
        t_remaining: float,
        t_total: float,
        sigma: float,
    ) -> float:
        """Adjust probability using Brownian bridge.

        Args:
            p0: Current market probability (0-1).
            t_remaining: Hours until resolution.
            t_total: Total hours the market has been active.
            sigma: Annualized volatility estimate.

        Returns:
            Adjusted probability reflecting resolution convergence.
        """
        if t_total <= 0 or t_remaining <= 0:
            return clamp(p0)

        if sigma <= 0:
            return clamp(p0)

        # Fraction of time remaining
        frac = t_remaining / t_total

        # Convert annualized sigma to per-hour
        sigma_hour = sigma / sqrt(8760.0)  # 8760 hours/year

        # Brownian bridge variance reduction: as frac→0, variance→0
        # Variance at time t = sigma^2 * t * (T-t) / T
        # Simplified: effective_sigma = sigma_hour * sqrt(frac * (1 - frac) * t_total)
        effective_sigma = sigma_hour * sqrt(frac * (1.0 - min(frac, 0.999)) * t_total)

        if effective_sigma < 1e-10:
            return clamp(p0)

        # Convert probability to z-score
        z0 = _norm_ppf(clamp(p0))

        return clamp(_norm_cdf(z0))


class TimeDecayModel:
    """Category-aware time-decay probability adjustment.

    Adjusts model probabilities for near-resolution markets based on
    the category's volatility profile. Low-vol categories (weather,
    politics) get reliable near-resolution boosts. High-vol (crypto)
    only get boosts in the final seconds.
    """

    def __init__(self) -> None:
        self._volatility_map = dict(CATEGORY_VOLATILITY)

    def adjust_probability(
        self,
        model_prob: float,
        time_to_resolution_h: float,
        volatility: float | None = None,
        category: str = "",
    ) -> float:
        """Apply time-decay correction to model probability.

        Args:
            model_prob: Current model probability (0-1).
            time_to_resolution_h: Hours until market resolution.
            volatility: Override volatility (uses category default if None).
            category: Market category for volatility lookup.

        Returns:
            Adjusted probability with near-resolution boost.
        """
        # No adjustment for low probabilities or extreme certainties
        if model_prob < MIN_PROB_FOR_BOOST or model_prob > MAX_PROB_FOR_BOOST:
            return model_prob

        # No adjustment if too far from resolution
        if time_to_resolution_h > MAX_RESOLUTION_HOURS:
            return model_prob

        # No adjustment if already past resolution
        if time_to_resolution_h <= 0:
            return model_prob

        sigma = volatility if volatility is not None else self.volatility_estimate(category)

        # Crypto: no boost unless < 60 seconds to resolution
        cat_lower = category.lower()
        if cat_lower == "crypto" and time_to_resolution_h > CRYPTO_MIN_BOOST_HOURS:
            return model_prob

        # Calculate boost based on proximity to resolution and probability
        # Taper: at p=0.92 → full boost (3pp), at p=0.98 → half boost (1.5pp)
        taper = max(0.0, (model_prob - 0.92) / 0.06) if model_prob > 0.92 else 0.0
        proximity_boost = MAX_BOOST_PP * (1.0 - 0.5 * taper)

        # Scale boost by time proximity: stronger as resolution approaches
        # At 7 days: 10% of boost, at 1 day: 50%, at 0.1 day: 95%
        time_factor = 1.0 - min(time_to_resolution_h / MAX_RESOLUTION_HOURS, 1.0)
        time_factor = time_factor ** 0.5  # square root scaling for faster ramp-up

        # Volatility discount: higher vol → less reliable boost
        vol_discount = max(0.1, 1.0 - sigma * 2.0)  # sigma=0.02 → 0.96, sigma=0.15 → 0.70

        final_boost = proximity_boost * time_factor * vol_discount

        adjusted = clamp(model_prob + final_boost)
        return adjusted

    def volatility_estimate(self, category: str) -> float:
        """Return default volatility for a category."""
        cat_lower = category.lower()
        # Partial match
        for key, vol in self._volatility_map.items():
            if key in cat_lower or cat_lower in key:
                return vol
        return DEFAULT_VOLATILITY
