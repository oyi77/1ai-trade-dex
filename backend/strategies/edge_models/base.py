"""EdgeCalculator ABC — pluggable edge calculation for modular strategies.

An EdgeCalculator computes the probability edge between a model's estimated
probability and the market price.  Each implementation targets a specific
alpha source (technical indicators, arbitrage, sentiment, market making).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


@dataclass
class EdgeResult:
    """Output of an edge calculation."""

    edge: float  # raw probability edge (model_prob - market_price)
    model_probability: float  # estimated true probability [0, 1]
    confidence: float  # confidence in the estimate [0, 1]
    direction: str  # "up" or "down"
    reasoning: str  # human-readable explanation
    metadata: dict[str, Any] | None = None  # calculator-specific extras


class EdgeCalculator(ABC):
    """Abstract base for pluggable edge calculators.

    Subclasses implement `calculate()` which receives market data and returns
    an EdgeResult describing the edge and recommended direction.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique identifier for this edge calculator."""

    @property
    @abstractmethod
    def description(self) -> str:
        """Human-readable description."""

    @abstractmethod
    async def calculate(
        self,
        market_price: float,
        market_data: dict[str, Any],
        params: dict[str, Any] | None = None,
    ) -> EdgeResult | None:
        """Calculate edge from market data.

        Args:
            market_price: Current market price (yes price, 0-1).
            market_data: Dict with keys depending on the calculator:
                - 'klines': list of OHLCV dicts (for technical)
                - 'prices': dict[str, float] platform->price (for arb)
                - 'sentiment': float -1 to 1 (for sentiment)
                - 'bid': float, 'ask': float (for market_making)
            params: Strategy-level parameters (min_edge, etc.)

        Returns:
            EdgeResult if a tradeable edge exists, None otherwise.
        """
