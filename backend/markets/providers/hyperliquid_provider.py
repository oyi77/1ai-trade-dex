"""Hyperliquid DEX market provider plugin."""

from decimal import Decimal

from backend.markets.base_provider import (
    BaseMarketProvider,
    MarketProviderManifest,
    NormalizedBalance,
    NormalizedOrder,
    NormalizedOrderResult,
    NormalizedPosition,
    VenueCapability,
)
from backend.markets.order_types import OrderSide, OrderStatus, PositionSide
from backend.markets.provider_registry import market_registry
from loguru import logger


@market_registry.plugin
class HyperliquidProvider(BaseMarketProvider):
    """Hyperliquid perpetuals DEX market provider."""

    def __init__(self, paper_mode: bool = False):
        super().__init__(paper_mode=paper_mode)
        from backend.clients.hyperliquid_client import HyperliquidClient

        self._client = HyperliquidClient()

    @classmethod
    def manifest(cls) -> MarketProviderManifest:
        return MarketProviderManifest(
            name="hyperliquid",
            display_name="Hyperliquid",
            version="1.0.0",
            venue_type="dex",
            capabilities=[
                VenueCapability.LIMIT_ORDERS,
                VenueCapability.MARKET_ORDERS,
                VenueCapability.SHORT_SELLING,
            ],
            supported_currencies=["USDC"],
            required_env_vars=["WALLET_PRIVATE_KEY"],
            supports_paper_mode=True,
            is_live_venue=True,
            min_order_size_usd=1.0,
            tags=["perps", "dex"],
        )

    async def place_order(self, order: NormalizedOrder) -> NormalizedOrderResult:
        """Place an order on Hyperliquid."""
        if self._paper_mode:
            return NormalizedOrderResult(
                venue_order_id=f"paper_hl_{order.market_id}_{order.side.value}",
                client_order_id=order.client_order_id,
                status=OrderStatus.FILLED,
                filled_size=order.size,
                filled_avg_price=order.price or Decimal("0"),
                remaining_size=Decimal("0"),
                fees_paid=Decimal("0"),
            )
        try:
            is_buy = order.side in (OrderSide.YES, OrderSide.BUY)
            order_type = "market" if order.order_type.value == "market" else "limit"
            result = await self._client.place_order(
                asset=order.market_id,
                is_buy=is_buy,
                size=float(order.size),
                price=float(order.price or Decimal("0")),
                order_type=order_type,
            )
            return NormalizedOrderResult(
                venue_order_id=str(
                    result.get("oid", result.get("order_id", "unknown"))
                ),
                client_order_id=order.client_order_id,
                status=OrderStatus.OPEN,
                filled_size=Decimal("0"),
                filled_avg_price=order.price,
                remaining_size=order.size,
                fees_paid=Decimal("0"),
                raw=result if isinstance(result, dict) else {},
            )
        except Exception as exc:
            logger.exception("Hyperliquid order failed")
            return self._rejected(order, str(exc))

    async def cancel_order(self, venue_order_id: str) -> bool:
        """Cancel an open order."""
        try:
            # venue_order_id format: "{asset}:{order_id}"
            parts = venue_order_id.split(":", 1)
            asset = parts[0] if len(parts) > 1 else venue_order_id
            order_id = int(parts[1]) if len(parts) > 1 else int(venue_order_id)
            await self._client.cancel_order(asset, order_id)
            return True
        except Exception as exc:
            logger.warning(f"Hyperliquid cancel failed: {exc}")
            return False

    async def get_balance(self) -> NormalizedBalance:
        """Get account balance via SDK (skip_ws=True for fast init)."""
        try:
            state = await asyncio.wait_for(
                asyncio.to_thread(self._client.get_balance), timeout=10
            )
            margin = state.get("marginSummary", {})
            return NormalizedBalance(
                venue="hyperliquid",
                available_cash=Decimal(str(margin.get("accountValue", "0"))),
                total_equity=Decimal(str(margin.get("accountValue", "0"))),
                reserved_margin=Decimal(str(margin.get("totalMarginUsed", "0"))),
                currency="USDC",
                raw=state,
            )
        except Exception as exc:
            logger.warning(f"[HyperliquidProvider] get_balance failed: {exc}")
            return NormalizedBalance(venue="hyperliquid", available_cash=Decimal("0"),
                                     total_equity=Decimal("0"), reserved_margin=Decimal("0"), currency="USDC")

    async def get_positions(self, market_id=None) -> list[NormalizedPosition]:
        """Get open positions."""
        raw_positions = await self._client.get_positions()
        result = []
        for pos in raw_positions:
            position = pos.get("position", pos)
            size = Decimal(str(abs(float(position.get("szi", "0")))))
            if size == 0:
                continue
            side = (
                PositionSide.LONG
                if float(position.get("szi", "0")) > 0
                else PositionSide.SHORT
            )
            result.append(
                NormalizedPosition(
                    market_id=position.get("coin", "unknown"),
                    side=side,
                    size=size,
                    avg_entry_price=Decimal(str(position.get("entryPx", "0"))),
                    venue="hyperliquid",
                    current_price=Decimal(str(position.get("oraclePx", "0"))),
                    unrealized_pnl=Decimal(str(position.get("unrealizedPnl", "0"))),
                )
            )
        return result

    @staticmethod
    def _rejected(order: NormalizedOrder, reason: str) -> NormalizedOrderResult:
        logger.warning(f"[HyperliquidProvider] Order rejected: {reason}")
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

    async def health_check(self) -> bool:
        """Check if Hyperliquid is accessible."""
        return await self._client.health_check()

    def subscribe_user_fills(self, callback):
        """Subscribe to real-time fill notifications via client."""
        return self._client.subscribe_user_fills(callback)

    def subscribe_order_updates(self, callback):
        """Subscribe to real-time order updates via client."""
        return self._client.subscribe_order_updates(callback)
