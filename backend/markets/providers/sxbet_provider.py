"""SX.bet market provider."""

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
    from backend.clients.sxbet_client import SXBetClient

    HAS_SXBET = True
except ImportError:
    HAS_SXBET = False

if not os.getenv("SXBET_API_URL"):
    logger.info("[SXBetProvider] SXBET_API_URL not set — provider disabled")


@market_registry.plugin
class SXBetProvider(BaseMarketProvider):
    """SX.bet market provider plugin."""

    def __init__(self, paper_mode: bool = False):
        super().__init__(paper_mode=paper_mode)
        if not HAS_SXBET:
            raise ImportError("SXBetClient required")
        self._client = SXBetClient()

    @classmethod
    def manifest(cls) -> MarketProviderManifest:
        return MarketProviderManifest(
            name="sxbet",
            display_name="SX.bet",
            version="1.0.0",
            venue_type="sports_prediction",
            capabilities=[VenueCapability.LIMIT_ORDERS, VenueCapability.MARKET_SEARCH],
            supported_currencies=["USDC"],
            required_env_vars=["SXBET_API_URL"],
            supports_paper_mode=True,
            is_live_venue=True,
            min_order_size_usd=1.0,
            tags=["sports", "prediction_market"],
        )

    async def place_order(self, order: NormalizedOrder) -> NormalizedOrderResult:
        """Place an order on SX.bet."""
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
        private_key = os.getenv("SXBET_PRIVATE_KEY", "")
        if not private_key:
            return self._rejected(order, "SXBET_PRIVATE_KEY not set")
        try:
            result = await self._client.place_maker_order(
                market_hash=order.market_id,
                outcome_index=0,
                odds=float(order.price or Decimal("0.5")),
                stake_wei=int(order.size * 10**18),
                private_key=private_key,
            )
            fees_paid = Decimal(
                str(
                    result.get("fee")
                    or result.get("fees")
                    or result.get("gasUsed")
                    or result.get("txFee")
                    or "0"
                )
            )
            return NormalizedOrderResult(
                venue_order_id=result.get("orderId", "unknown"),
                client_order_id=order.client_order_id,
                status=OrderStatus.OPEN,
                filled_size=Decimal("0"),
                filled_avg_price=order.price or Decimal("0.5"),
                remaining_size=order.size,
                fees_paid=fees_paid,
            )
        except Exception as exc:
            logger.exception("SXBet order failed")
            return self._rejected(order, str(exc))

    async def cancel_order(self, venue_order_id: str) -> bool:
        """SX.bet doesn't support cancel."""
        return False

    async def get_markets(self, limit: int = 50, **kwargs) -> list[MarketInfo]:
        """Get available markets from SX.bet."""
        raw = await self._client.get_markets(limit=limit)
        if isinstance(raw, dict):
            raw = raw.get("data", raw.get("markets", []))
        return [
            MarketInfo(
                market_id=str(m.get("marketHash", "")),
                question=str(m.get("title", "")),
                yes_price=0.5,
                no_price=0.5,
            )
            for m in raw
        ]

    async def get_balance(self) -> NormalizedBalance:
        """Get account balance."""
        return NormalizedBalance(
            venue="sxbet", available_cash=Decimal("0"), total_equity=Decimal("0"), reserved_margin=Decimal("0"), currency="USDC"
        )

    async def get_positions(self) -> list[NormalizedPosition]:
        """Get open positions."""
        return []

    async def health_check(self) -> bool:
        """Check if SX.bet is accessible."""
        return await self._client.health_check()
