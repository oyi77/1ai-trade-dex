"""Abstract base class and manifest for market provider plugins."""

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import AsyncGenerator

from decimal import Decimal

from backend.markets.order_types import (
    MarketInfo,
    NormalizedBalance,
    NormalizedOrder,
    NormalizedOrderResult,
    NormalizedPosition,
    OrderStatus,
    VenueCapability,
)

logger = logging.getLogger(__name__)


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
    def manifest(cls) -> MarketProviderManifest: ...

    @abstractmethod
    async def place_order(self, order: NormalizedOrder) -> NormalizedOrderResult:
        """Submit an order to the venue."""
        ...

    @abstractmethod
    async def cancel_order(self, venue_order_id: str) -> bool:
        """Cancel an open order. Returns True if cancelled, False if already filled."""
        ...

    async def cancel_all_orders(self, market_id=None) -> int:
        logger.debug(f"{type(self).__name__} does not implement cancel_all_orders")
        return 0

    async def get_order(self, venue_order_id: str) -> NormalizedOrderResult:
        logger.debug(f"{type(self).__name__} does not implement get_order")
        return None

    @abstractmethod
    async def get_balance(self) -> NormalizedBalance: ...

    @abstractmethod
    async def get_positions(self, market_id=None) -> list[NormalizedPosition]: ...

    async def get_market(self, market_id) -> MarketInfo:
        logger.debug(f"{type(self).__name__} does not implement get_market")
        return None

    async def search_markets(self, query, category, limit) -> list[MarketInfo]:
        logger.debug(f"{type(self).__name__} does not implement search_markets")
        return []

    async def stream_fills(self) -> AsyncGenerator:
        logger.debug(f"{type(self).__name__} does not implement stream_fills")
        return
        yield  # make this an async generator

    async def health_check(self) -> bool:
        try:
            await self.get_balance()
            return True
        except Exception as e:
            logger.debug(f"Health check failed: {e}")
            return False

    async def teardown(self) -> None:
        pass

    @staticmethod
    def _rejected(order: NormalizedOrder, reason: str) -> NormalizedOrderResult:
        """Helper: create rejection result for order failure."""
        return NormalizedOrderResult(
            venue_order_id="",
            client_order_id=order.client_order_id,
            status=OrderStatus.REJECTED,
            filled_size=Decimal("0"),
            filled_avg_price=None,
            remaining_size=order.size,
            fees_paid=Decimal("0"),
            raw={"error": reason},
        )
