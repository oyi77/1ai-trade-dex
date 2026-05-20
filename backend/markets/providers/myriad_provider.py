"""Myriad Markets prediction market provider."""
import os
from decimal import Decimal
from backend.markets.base_provider import (
    BaseMarketProvider, MarketProviderManifest, NormalizedOrder,
    NormalizedOrderResult, NormalizedBalance, NormalizedPosition, VenueCapability,
)
from backend.markets.order_types import MarketInfo, OrderStatus
from backend.markets.provider_registry import market_registry
from loguru import logger

try:
    from backend.clients.myriad_client import MyriadClient
    HAS_MYRIAD = True
except ImportError:
    HAS_MYRIAD = False

if not os.getenv("MYRIAD_API_URL"):
    logger.info("[MyriadProvider] MYRIAD_API_URL not set — provider disabled")


@market_registry.plugin
class MyriadProvider(BaseMarketProvider):
    """Myriad Markets prediction market provider plugin."""

    def __init__(self, paper_mode: bool = False):
        super().__init__(paper_mode=paper_mode)
        if not HAS_MYRIAD:
            raise ImportError("MyriadClient required")
        self._client = MyriadClient()

    @classmethod
    def manifest(cls) -> MarketProviderManifest:
        return MarketProviderManifest(
            name="myriad",
            display_name="Myriad Markets",
            version="1.0.0",
            venue_type="prediction_market",
            capabilities=[VenueCapability.LIMIT_ORDERS, VenueCapability.MARKET_ORDERS, VenueCapability.MARKET_SEARCH],
            supported_currencies=["USDC"],
            required_env_vars=["MYRIAD_API_URL"],
            supports_paper_mode=True,
            is_live_venue=True,
            min_order_size_usd=1.0,
            tags=["prediction_market", "polygon"],
        )

    async def place_order(self, order: NormalizedOrder) -> NormalizedOrderResult:
        if self._paper_mode:
            fill_price = order.price or Decimal("0.5")
            return NormalizedOrderResult(
                venue_order_id=f"paper_myriad_{order.market_id}",
                client_order_id=order.client_order_id,
                status=OrderStatus.FILLED,
                filled_size=order.size,
                filled_avg_price=fill_price,
                remaining_size=Decimal("0"),
                fees_paid=Decimal("0"),
            )

        if order.price is None:
            return self._rejected(order, "Myriad requires a limit price")

        result = await self._client.place_order(
            market_id=order.market_id,
            side=order.side.value,
            size=order.size,
            price=order.price,
        )

        if result.get("error"):
            return self._rejected(order, "Myriad API error")

        return NormalizedOrderResult(
            venue_order_id=str(result.get("order_id", "")),
            client_order_id=order.client_order_id,
            status=OrderStatus.FILLED,
            filled_size=order.size,
            filled_avg_price=order.price,
            remaining_size=Decimal("0"),
            fees_paid=Decimal("0"),
        )

    async def cancel_order(self, venue_order_id: str) -> bool:
        return await self._client.cancel_order(venue_order_id)

    async def get_balance(self) -> NormalizedBalance:
        bal = await self._client.get_balance()
        return NormalizedBalance(available=bal, locked=Decimal("0"), total=bal)

    async def get_positions(self, market_id=None) -> list:
        positions = await self._client.get_positions()
        return [
            NormalizedPosition(
                market_id=p.get("market_id", ""),
                side=p.get("side", "long"),
                size=Decimal(str(p.get("size", 0))),
                entry_price=Decimal(str(p.get("price", 0))),
                current_price=Decimal(str(p.get("current_price", 0))),
                unrealized_pnl=Decimal(str(p.get("pnl", 0))),
            )
            for p in positions
        ]

    async def search_markets(self, query: str, category=None, limit=20) -> list:
        markets = await self._client.get_markets(limit=limit)
        if query:
            markets = [m for m in markets if query.lower() in m.get("title", "").lower()]
        return [
            MarketInfo(
                market_id=m.get("id", ""),
                title=m.get("title", ""),
                description=m.get("description", ""),
                category=m.get("category", "other"),
                end_date=m.get("end_date"),
                outcomes=m.get("outcomes", []),
                active=m.get("status") == "active",
            )
            for m in markets[:limit]
        ]

    def _rejected(self, order, reason):
        logger.warning(f"[MyriadProvider] Order rejected: {reason}")
        return NormalizedOrderResult(
            venue_order_id="",
            client_order_id=order.client_order_id,
            status=OrderStatus.REJECTED,
            filled_size=Decimal("0"),
            filled_avg_price=None,
            remaining_size=order.size,
            fees_paid=Decimal("0"),
            reject_reason=reason,
        )
