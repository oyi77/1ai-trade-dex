"""Probability utility functions for PolyEdge AI modules.

Centralized clamping and validation of probability values to prevent
extreme values (0.0 or 1.0) that would cause infinite Kelly fractions
or division-by-zero errors downstream.
"""

from __future__ import annotations

import logging

logger = logging.getLogger("trading_bot.probability_utils")


def clamp_probability(p: float, epsilon: float = 0.01) -> float:
    """Clamp a probability to [epsilon, 1.0 - epsilon].

    Logs a warning when the input value is out of bounds, which helps
    detect upstream bugs that produce degenerate probabilities.

    Args:
        p: Raw probability value.
        epsilon: Minimum distance from 0.0 and 1.0.  Default 0.01 keeps
                 probabilities in [0.01, 0.99].

    Returns:
        Clamped probability in [epsilon, 1.0 - epsilon].
    """
    clamped = max(epsilon, min(1.0 - epsilon, p))
    if clamped != p:
        logger.warning(
            "clamp_probability: %.6f outside [%.4f, %.4f], clamped to %.6f",
            p, epsilon, 1.0 - epsilon, clamped,
        )
    return clamped
