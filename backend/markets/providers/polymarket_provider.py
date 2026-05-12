"""Polymarket market provider plugin."""
import os
from typing import List, Optional
from decimal import Decimal

from backend.core.plugin_errors import MarketProviderError
from backend.markets.base_provider import BaseMarketProvider, MarketProviderManifest, NormalizedOrder, NormalizedOrderResult, NormalizedBalance, NormalizedPosition, VenueCapability
from backend.markets.order_types import NormalizedFillEvent, MarketInfo, OrderSide, OrderType, OrderStatus, PositionSide
from backend.markets.provider_registry import market_registry

try:
    from backend.data.polymarket_clob import PolymarketCLOB
    HAS_POLYMARKET = True
except ImportError:
    HAS_POLYMARKET = False


@market_registry.plugin
class PolymarketProvider(BaseMarketProvider):
    """Polymarket CLOB market provider plugin."""

    def __init__(self, paper_mode: bool = False):
        super().__init__(paper_mode=paper_mode)
        if not HAS_POLYMARKET:
            raise ImportError("py-clob-client not installed")
        api_key = os.environ.get("POLYMARKET_API_KEY", "")
        api_secret = os.environ.get("POLYMARKET_API_SECRET", "")
        self._client = PolymarketCLOB(api_key=api_key, api_secret=api_secret)

    @classmethod
    def manifest(cls) -> MarketProviderManifest:
        return MarketProviderManifest(
            name="polymarket",
            display_name="Polymarket",
            version="1.0.0",
            venue_type="prediction_market",
            capabilities=[
                VenueCapability.LIMIT_ORDERS,
                VenueCapability.MARKET_ORDERS,
                VenueCapability.MARKET_SEARCH,
                VenueCapability.STREAMING_FILLS,
            ],
            supported_currencies=["USDC"],
            required_env_vars=["POLYMARKET_API_KEY", "POLYMARKET_API_SECRET"],
            supports_paper_mode=True,
            is_live_venue=True,
            min_order_size_usd=1.0,
            maker_fee_bps=0,
            taker_fee_bps=0,
            tags=["primary", "prediction_market"],
        )

    async def place_order(self, order: NormalizedOrder) -> NormalizedOrderResult:
        if self._paper_mode:
            return NormalizedOrderResult(
                venue_order_id=f"paper_{order.market_id}_{order.side.value}",
                client_order_id=order.client_order_id,
                status=OrderStatus.FILLED,
                filled_size=order.size,
                filled_avg_price=order.price or Decimal("0.5"),
                remaining_size=Decimal("0"),
                fees_paid=Decimal("0"),
            )
        raise NotImplementedError

    async def cancel_order(self, venue_order_id: str) -> bool:
        if self._paper_mode:
            return True
        raise NotImplementedError

    async def get_balance(self) -> NormalizedBalance:
        return NormalizedBalance(
            venue="polymarket",
            available_cash=Decimal("10000"),
            total_equity=Decimal("10000"),
            reserved_margin=Decimal("0"),
        )

    async def get_positions(
        self, market_id: Optional[str] = None
    ) -> List[NormalizedPosition]:
        return []

    async def search_markets(
        self, query: Optional[str] = None, category: Optional[str] = None, limit: int = 50
    ) -> List[MarketInfo]:
        return []