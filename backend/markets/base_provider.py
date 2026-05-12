"""Abstract base class and manifest for market provider plugins."""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import AsyncGenerator

from backend.markets.order_types import (
    MarketInfo,
    NormalizedBalance,
    NormalizedOrder,
    NormalizedOrderResult,
    NormalizedPosition,
    VenueCapability,
)


@dataclass
class MarketProviderManifest:
    """Declarative metadata for a market provider plugin."""

    name: str
    display_name: str
    version: str
    venue_type: str
    capabilities: list[VenueCapability]
    supported_currencies: list[str]
    required_env_vars: list[str]
    supports_paper_mode: bool = True
    is_live_venue: bool = True
    min_order_size_usd: float = 1.0
    maker_fee_bps: float = 0.0
    taker_fee_bps: float = 0.0
    tags: list[str] = field(default_factory=list)


class BaseMarketProvider(ABC):
    """Every trading venue plugin must subclass this."""

    def __init__(self, paper_mode: bool = False):
        self._paper_mode = paper_mode

    @classmethod
    @abstractmethod
    def manifest(cls) -> MarketProviderManifest:
        ...

    @abstractmethod
    async def place_order(self, order: NormalizedOrder) -> NormalizedOrderResult:
        """Submit an order to the venue."""
        ...

    @abstractmethod
    async def cancel_order(self, venue_order_id: str) -> bool:
        """Cancel an open order. Returns True if cancelled, False if already filled."""
        ...

    async def cancel_all_orders(self, market_id=None) -> int:
        raise NotImplementedError

    async def get_order(self, venue_order_id: str) -> NormalizedOrderResult:
        raise NotImplementedError

    @abstractmethod
    async def get_balance(self) -> NormalizedBalance:
        ...

    @abstractmethod
    async def get_positions(self, market_id=None) -> list[NormalizedPosition]:
        ...

    async def get_market(self, market_id) -> MarketInfo:
        raise NotImplementedError

    async def search_markets(self, query, category, limit) -> list[MarketInfo]:
        raise NotImplementedError

    async def stream_fills(self) -> AsyncGenerator:
        raise NotImplementedError

    async def health_check(self) -> bool:
        try:
            await self.get_balance()
            return True
        except Exception:
            return False

    async def teardown(self) -> None:
        pass
