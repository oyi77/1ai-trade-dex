"""Abstract base classes for signal generators."""

from abc import ABC, abstractmethod
from typing import List, Optional, Dict, Any
from dataclasses import dataclass, field
from datetime import datetime

from loguru import logger


@dataclass
class Signal:
    """A trading signal with metadata."""

    market_id: str
    direction: str  # 'up' or 'down'
    confidence: float  # 0.0 to 1.0
    edge: float  # expected edge percentage
    suggested_size: float
    timestamp: datetime
    source: str
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if self.confidence < 0 or self.confidence > 1:
            raise ValueError(
                f"Confidence must be between 0 and 1, got {self.confidence}"
            )
        if self.edge < 0:
            raise ValueError(f"Edge must be non-negative, got {self.edge}")


@dataclass
class MarketData:
    """Market data for signal generation."""

    market_id: str
    current_price: float
    volume_24h: float
    liquidity: float
    price_history: List[float]
    last_updated: datetime


class BaseSignalGenerator(ABC):
    """Abstract base class for all signal generators."""

    def __init__(self, name: str, config: Optional[Dict] = None):
        self.name = name
        self.config = config or {}
        self.enabled = True

    @abstractmethod
    async def generate_signals(
        self, market_data: Optional[MarketData] = None
    ) -> List[Signal]:
        """
        Generate trading signals.

        Args:
            market_data: Optional market data to use for signal generation

        Returns:
            List of Signal objects
        """
        pass

    @abstractmethod
    async def get_market_data(self, market_id: str) -> Optional[MarketData]:
        """
        Fetch market data for a specific market.

        Args:
            market_id: The market identifier

        Returns:
            MarketData object or None if not available
        """
        pass

    def get_name(self) -> str:
        """Get the name of this signal generator."""
        return self.name

    def is_enabled(self) -> bool:
        """Check if this generator is enabled."""
        return self.enabled

    def set_enabled(self, enabled: bool):
        """Enable or disable this generator."""
        self.enabled = enabled

    def get_config(self) -> Dict:
        """Get the configuration for this generator."""
        return self.config

    def update_config(self, config: Dict):
        """Update the configuration for this generator."""
        self.config.update(config)


class SignalAggregator:
    """Aggregate signals from multiple generators."""

    def __init__(self):
        self.generators: List[BaseSignalGenerator] = []

    def register_generator(self, generator: BaseSignalGenerator):
        """Register a signal generator."""
        self.generators.append(generator)

    def unregister_generator(self, name: str):
        """Unregister a signal generator by name."""
        self.generators = [g for g in self.generators if g.get_name() != name]

    async def generate_all_signals(self) -> List[Signal]:
        """Generate signals from all enabled generators."""
        all_signals = []
        for generator in self.generators:
            if generator.is_enabled():
                try:
                    signals = await generator.generate_signals()
                    all_signals.extend(signals)
                except Exception as e:
                    # Log error but continue with other generators
                    logger.error(f"Error in signal generator {generator.get_name()}: {e}")
        return all_signals

    def get_generator(self, name: str) -> Optional[BaseSignalGenerator]:
        """Get a generator by name."""
        for generator in self.generators:
            if generator.get_name() == name:
                return generator
        return None
