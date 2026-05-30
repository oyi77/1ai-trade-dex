"""SignalGenerator ABC — pluggable signal generation for modular strategies.

A SignalGenerator produces raw market signals from data feeds (price data,
orderbooks, cross-platform prices).  Each implementation targets a specific
data source.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Signal:
    """Raw signal produced by a SignalGenerator."""

    signal_type: str  # e.g. "momentum", "orderbook_imbalance", "price_divergence"
    strength: float  # -1.0 (strong down) to +1.0 (strong up), 0 = neutral
    confidence: float  # 0.0 to 1.0
    market_ticker: str
    data: dict[str, Any] = field(default_factory=dict)  # signal-specific metadata
    reasoning: str = ""


class SignalGenerator(ABC):
    """Abstract base for pluggable signal generators.

    Subclasses implement `generate()` which reads market data and returns
    a list of Signal objects representing detected opportunities.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique identifier for this signal generator."""

    @property
    @abstractmethod
    def description(self) -> str:
        """Human-readable description."""

    @abstractmethod
    async def generate(
        self,
        markets: list[dict[str, Any]],
        params: dict[str, Any] | None = None,
    ) -> list[Signal]:
        """Generate signals from market data.

        Args:
            markets: List of market dicts, each containing at minimum:
                - 'ticker': str
                - 'yes_price': float
                - Additional keys depending on generator type
            params: Strategy-level parameters.

        Returns:
            List of Signal objects for detected opportunities.
        """
