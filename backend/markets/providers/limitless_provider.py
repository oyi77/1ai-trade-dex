"""Limitless Exchange market provider."""

import os
from decimal import Decimal
from backend.markets.base_provider import (
    BaseMarketProvider,
    MarketProviderManifest,
    NormalizedOrder,
    NormalizedOrderResult,
    NormalizedBalance,
    NormalizedPosition,
    VenueCapability,
)
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
            # Call SDK directly to avoid wrapper issues
            from limitless_sdk import LimitlessClient as SDKClient
            from limitless_sdk.models import CreateOrderDto
            sdk = SDKClient(
                private_key=private_key if private_key.startswith("0x") else f"0x{private_key}",
                api_key=os.getenv("LIMITLESS_API_KEY", None),
            )
            await sdk.create_session()
            outcome_index = 0
            side_int = 1 if order.side.value.upper() == "BUY" else 0
            dto = await sdk.create_order(
                market_id=order.market_id,
                market_slug=order.market_id,
                outcome_index=outcome_index,
                side=side_int,
                amount=float(order.size),
                price=float(order.price or Decimal("0.5")),
            )
            result = await sdk.place_order(dto)
            logger.info(f"[limitless] Order placed: {result}")
            return NormalizedOrderResult(
                venue_order_id=result.get("orderId", "unknown"),
                client_order_id=order.client_order_id,
                status=OrderStatus.OPEN,
                filled_size=Decimal("0"),
                filled_avg_price=order.price or Decimal("0.5"),
                remaining_size=order.size,
                fees_paid=Decimal(
                    str(
                        result.get("fee")
                        or result.get("fees")
                        or result.get("feePaid")
                        or result.get("fee_paid")
                        or "0"
                    )
                ),
            )
        except Exception as exc:
            import sys
            print(f"[limitless] ORDER ERROR: {exc}", file=sys.stderr, flush=True)
            import traceback
            traceback.print_exc(file=sys.stderr)
            return self._rejected(order, str(exc))

    async def cancel_order(self, venue_order_id: str) -> bool:
        """Cancel an open order."""
        private_key = os.getenv("LIMITLESS_PRIVATE_KEY", "")
        return await self._client.cancel_order(venue_order_id, private_key)

    async def search_markets(self, query=None, category=None, limit=50, **kwargs) -> list:
        """Search markets — delegates to get_markets since Limitless has no search API."""
        return await self.get_markets(limit=limit)

    @staticmethod
    def _rejected(order: NormalizedOrder, reason: str) -> NormalizedOrderResult:
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

    async def get_markets(self, limit: int = 50, **kwargs) -> list[MarketInfo]:
        """Get available markets from Limitless Exchange."""
        raw = await self._client.get_markets(limit=limit)
        result = []
        for m in raw:
            prices = m.get("prices", [])
            if not prices or len(prices) < 2:
                continue  # Skip markets with no price data
            yes_price = Decimal(str(prices[0]))
            no_price = Decimal(str(prices[1]))
            if yes_price <= 0 or no_price <= 0:
                continue  # Skip markets with zero prices
            title = m.get("title") or m.get("proxyTitle") or m.get("question", "")
            result.append(MarketInfo(
                venue="limitless",
                market_id=str(m.get("slug", "") or m.get("id", "")),
                title=title,
                description="",
                category="crypto",
                yes_price=yes_price,
                no_price=no_price,
                volume_24h=Decimal(str(m.get("volume", 0) or 0)),
                open_interest=Decimal("0"),
                closes_at=m.get("expirationTimestamp"),
                is_active=True,
                min_order_size=Decimal("1"),
                tick_size=Decimal("0.01"),
                raw=m,
            ))
        return result

    async def get_balance(self) -> NormalizedBalance:
        """Get account balance."""
        return NormalizedBalance(
            venue="limitless", available_cash=Decimal("0"), total_equity=Decimal("0"), reserved_margin=Decimal("0"), currency="USDC"
        )

    async def get_positions(self) -> list[NormalizedPosition]:
        """Get open positions."""
        return []

    async def health_check(self) -> bool:
        """Check if Limitless Exchange is accessible."""
        return await self._client.health_check()
