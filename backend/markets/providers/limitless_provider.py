"""Limitless Exchange market provider."""
import os
from decimal import Decimal
from backend.markets.base_provider import BaseMarketProvider, MarketProviderManifest, NormalizedOrder, NormalizedOrderResult, NormalizedBalance, NormalizedPosition, VenueCapability
from backend.markets.order_types import MarketInfo, OrderStatus
from backend.markets.provider_registry import market_registry
from loguru import logger

try:
    from backend.clients.limitless_client import LimitlessClient
    HAS_LIMITLESS = True
except ImportError:
    HAS_LIMITLESS = False

if not os.getenv("LIMITLESS_API_URL"):
    logger.info("[LimitlessProvider] LIMITLESS_API_URL not set — provider disabled")


@market_registry.plugin
class LimitlessProvider(BaseMarketProvider):
    """Limitless Exchange market provider plugin."""

    def __init__(self, paper_mode: bool = False):
        super().__init__(paper_mode=paper_mode)
        if not HAS_LIMITLESS:
            raise ImportError("LimitlessClient required")
        self._client = LimitlessClient()

    @classmethod
    def manifest(cls) -> MarketProviderManifest:
        return MarketProviderManifest(
            name="limitless",
            display_name="Limitless Exchange",
            version="1.0.0",
            venue_type="prediction_market",
            capabilities=[VenueCapability.LIMIT_ORDERS, VenueCapability.MARKET_SEARCH],
            supported_currencies=["USDC"],
            required_env_vars=["LIMITLESS_API_URL"],
            supports_paper_mode=True,
            is_live_venue=True,
            min_order_size_usd=1.0,
            tags=["prediction_market"],
        )

    async def place_order(self, order: NormalizedOrder) -> NormalizedOrderResult:
        """Place an order on Limitless Exchange."""
        if self._paper_mode:
            return NormalizedOrderResult(
                venue_order_id=f"paper_{order.market_id}",
                client_order_id=order.client_order_id,
                status=OrderStatus.FILLED,
                filled_size=order.size,
                filled_avg_price=order.price or Decimal("0.5"),
                remaining_size=Decimal("0"),
                fees_paid=Decimal("0"),
            )
        private_key = os.getenv("LIMITLESS_PRIVATE_KEY", "")
        if not private_key:
            return self._rejected(order, "LIMITLESS_PRIVATE_KEY not set")
        try:
            result = await self._client.place_order(
                market_id=order.market_id,
                side=order.side.value,
                size=float(order.size),
                price=float(order.price or Decimal("0.5")),
                private_key=private_key,
            )
            return NormalizedOrderResult(
                venue_order_id=result.get("orderId", "unknown"),
                client_order_id=order.client_order_id,
                status=OrderStatus.OPEN,
                filled_size=Decimal("0"),
                filled_avg_price=order.price or Decimal("0.5"),
                remaining_size=order.size,
                fees_paid=Decimal(str(
                    result.get("fee") or result.get("fees") or result.get("feePaid") or result.get("fee_paid") or "0"
                )),
            )
        except Exception as exc:
            logger.exception("Limitless order failed")
            return self._rejected(order, str(exc))

    async def cancel_order(self, venue_order_id: str) -> bool:
        """Cancel an open order."""
        private_key = os.getenv("LIMITLESS_PRIVATE_KEY", "")
        return await self._client.cancel_order(venue_order_id, private_key)

    async def get_markets(self, limit: int = 50, **kwargs) -> list[MarketInfo]:
        """Get available markets from Limitless Exchange."""
        raw = await self._client.get_markets(limit=limit)
        return [MarketInfo(market_id=str(m.get("id", "")), question=str(m.get("question", "")), yes_price=0.5, no_price=0.5) for m in raw]

    async def get_balance(self) -> NormalizedBalance:
        """Get account balance."""
        return NormalizedBalance(available=Decimal("0"), total=Decimal("0"), currency="USDC")

    async def get_positions(self) -> list[NormalizedPosition]:
        """Get open positions."""
        return []

    async def health_check(self) -> bool:
        """Check if Limitless Exchange is accessible."""
        return await self._client.health_check()
