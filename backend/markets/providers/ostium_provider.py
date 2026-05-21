"""Ostium DEX market provider plugin."""

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
class OstiumProvider(BaseMarketProvider):
    """Ostium perpetuals DEX market provider."""

    def __init__(self, paper_mode: bool = False):
        super().__init__(paper_mode=paper_mode)
        from backend.clients.ostium_client import OstiumClient

        self._client = OstiumClient()

    @classmethod
    def manifest(cls) -> MarketProviderManifest:
        return MarketProviderManifest(
            name="ostium",
            display_name="Ostium",
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
            tags=["perps", "dex", "arbitrum"],
        )

    async def place_order(self, order: NormalizedOrder) -> NormalizedOrderResult:
        """Place an order on Ostium."""
        if self._paper_mode:
            return NormalizedOrderResult(
                venue_order_id=f"paper_ost_{order.market_id}_{order.side.value}",
                client_order_id=order.client_order_id,
                status=OrderStatus.FILLED,
                filled_size=order.size,
                filled_avg_price=order.price or Decimal("0"),
                remaining_size=Decimal("0"),
                fees_paid=Decimal("0"),
            )
        try:
            direction = order.side in (OrderSide.YES, OrderSide.BUY)
            order_type = (
                "MARKET" if order.order_type.value == "market" else "LIMIT"
            )
            result = await self._client.place_order(
                pair_id=int(order.market_id),
                direction=direction,
                collateral=float(order.size),
                leverage=int(order.metadata.get("leverage", 1)),
                order_type=order_type,
                price=float(order.price) if order.price else None,
                tp=order.metadata.get("tp"),
                sl=order.metadata.get("sl"),
            )
            return NormalizedOrderResult(
                venue_order_id=str(result.get("order_id", result.get("txHash", "unknown"))),
                client_order_id=order.client_order_id,
                status=OrderStatus.OPEN,
                filled_size=Decimal("0"),
                filled_avg_price=order.price,
                remaining_size=order.size,
                fees_paid=Decimal("0"),
                raw=result if isinstance(result, dict) else {},
            )
        except Exception as exc:
            logger.exception("Ostium order failed")
            return self._rejected(order, str(exc))

    async def cancel_order(self, venue_order_id: str) -> bool:
        """Cancel an open order."""
        try:
            parts = venue_order_id.split(":", 1)
            pair_id = int(parts[0])
            index = int(parts[1]) if len(parts) > 1 else 0
            await self._client.cancel_order(pair_id, index)
            return True
        except Exception as exc:
            logger.warning(f"Ostium cancel failed: {exc}")
            return False

    async def get_balance(self) -> NormalizedBalance:
        """Get account balance."""
        bal = await self._client.get_balance()
        return NormalizedBalance(
            venue="ostium",
            available_cash=Decimal(str(bal.get("balance", bal.get("available", "0")))),
            total_equity=Decimal(str(bal.get("balance", bal.get("total", "0")))),
            reserved_margin=Decimal("0"),
            currency="USDC",
            raw=bal,
        )

    async def get_positions(self, market_id=None) -> list[NormalizedPosition]:
        """Get open positions."""
        raw_positions = await self._client.get_positions()
        result = []
        for pos in raw_positions:
            size = Decimal(str(abs(float(pos.get("collateral", pos.get("size", "0"))))))
            if size == 0:
                continue
            is_long = pos.get("direction", pos.get("isLong", True))
            side = PositionSide.LONG if is_long else PositionSide.SHORT
            result.append(
                NormalizedPosition(
                    market_id=str(pos.get("pairId", pos.get("pair_id", "unknown"))),
                    side=side,
                    size=size,
                    avg_entry_price=Decimal(str(pos.get("entryPrice", pos.get("open_price", "0")))),
                    venue="ostium",
                    current_price=Decimal(str(pos.get("currentPrice", "0"))),
                    unrealized_pnl=Decimal(str(pos.get("pnl", "0"))),
                )
            )
        return result

    @staticmethod
    def _rejected(order: NormalizedOrder, reason: str) -> NormalizedOrderResult:
        logger.warning(f"[OstiumProvider] Order rejected: {reason}")
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
        """Check if Ostium is accessible."""
        return await self._client.health_check()
