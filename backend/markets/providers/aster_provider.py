"""Aster DEX market provider plugin."""

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
class AsterProvider(BaseMarketProvider):
    """Aster perpetuals DEX market provider (Binance-compatible)."""

    def __init__(self, paper_mode: bool = False):
        super().__init__(paper_mode=paper_mode)
        from backend.clients.aster_client import AsterClient

        self._client = AsterClient()

    @classmethod
    def manifest(cls) -> MarketProviderManifest:
        return MarketProviderManifest(
            name="aster",
            display_name="Aster",
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
        """Place an order on Aster."""
        if self._paper_mode:
            return NormalizedOrderResult(
                venue_order_id=f"paper_ast_{order.market_id}_{order.side.value}",
                client_order_id=order.client_order_id,
                status=OrderStatus.FILLED,
                filled_size=order.size,
                filled_avg_price=order.price or Decimal("0"),
                remaining_size=Decimal("0"),
                fees_paid=Decimal("0"),
            )
        try:
            side = "buy" if order.side in (OrderSide.YES, OrderSide.BUY) else "sell"
            order_type = order.order_type.value
            result = await self._client.place_order(
                symbol=order.market_id,
                side=side,
                amount=float(order.size),
                price=float(order.price) if order.price else None,
                order_type=order_type,
            )
            return NormalizedOrderResult(
                venue_order_id=str(result.get("id", result.get("orderId", "unknown"))),
                client_order_id=order.client_order_id,
                status=OrderStatus.OPEN,
                filled_size=Decimal(str(result.get("filled", "0"))),
                filled_avg_price=Decimal(str(result.get("average", "0"))) if result.get("average") else order.price,
                remaining_size=order.size - Decimal(str(result.get("filled", "0"))),
                fees_paid=Decimal(str(result.get("fee", {}).get("cost", "0"))) if isinstance(result.get("fee"), dict) else Decimal("0"),
                raw=result if isinstance(result, dict) else {},
            )
        except Exception as exc:
            logger.exception("Aster order failed")
            return self._rejected(order, str(exc))

    async def cancel_order(self, venue_order_id: str) -> bool:
        """Cancel an open order."""
        try:
            parts = venue_order_id.split(":", 1)
            order_id = parts[0]
            symbol = parts[1] if len(parts) > 1 else ""
            await self._client.cancel_order(order_id, symbol)
            return True
        except Exception as exc:
            logger.warning(f"Aster cancel failed: {exc}")
            return False

    async def get_balance(self) -> NormalizedBalance:
        """Get account balance."""
        bal = await self._client.get_balance()
        usdc = bal.get("USDC", bal.get("total", {}))
        if isinstance(usdc, dict):
            free = Decimal(str(usdc.get("free", usdc.get("available", "0"))))
            total = Decimal(str(usdc.get("total", usdc.get("equity", "0"))))
            used = Decimal(str(usdc.get("used", usdc.get("margin", "0"))))
        else:
            free = Decimal("0")
            total = Decimal("0")
            used = Decimal("0")
        return NormalizedBalance(
            venue="aster",
            available_cash=free,
            total_equity=total,
            reserved_margin=used,
            currency="USDC",
            raw=bal,
        )

    async def get_positions(self, market_id=None) -> list[NormalizedPosition]:
        """Get open positions."""
        raw_positions = await self._client.get_positions()
        result = []
        for pos in raw_positions:
            contracts = abs(float(pos.get("contracts", pos.get("size", "0"))))
            if contracts == 0:
                continue
            side_str = pos.get("side", "long")
            side = PositionSide.LONG if side_str == "long" else PositionSide.SHORT
            result.append(
                NormalizedPosition(
                    market_id=pos.get("symbol", "unknown"),
                    side=side,
                    size=Decimal(str(contracts)),
                    avg_entry_price=Decimal(str(pos.get("entryPrice", "0"))),
                    venue="aster",
                    current_price=Decimal(str(pos.get("markPrice", "0"))),
                    unrealized_pnl=Decimal(str(pos.get("unrealizedPnl", "0"))),
                )
            )
        return result

    @staticmethod
    def _rejected(order: NormalizedOrder, reason: str) -> NormalizedOrderResult:
        logger.warning(f"[AsterProvider] Order rejected: {reason}")
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
        """Check if Aster is accessible."""
        return await self._client.health_check()

    async def watch_balance(self) -> NormalizedBalance:
        """Real-time balance via WebSocket, normalized."""
        bal = await self._client.watch_balance()
        usdc = bal.get("USDC", bal.get("total", {}))
        if isinstance(usdc, dict):
            free = Decimal(str(usdc.get("free", usdc.get("available", "0"))))
            total = Decimal(str(usdc.get("total", usdc.get("equity", "0"))))
            used = Decimal(str(usdc.get("used", usdc.get("margin", "0"))))
        else:
            free = total = used = Decimal("0")
        return NormalizedBalance(
            venue="aster",
            available_cash=free,
            total_equity=total,
            reserved_margin=used,
            currency="USDC",
            raw=bal,
        )

    async def watch_positions(self, market_id=None) -> list[NormalizedPosition]:
        """Real-time positions via WebSocket, normalized."""
        raw_positions = await self._client.watch_positions()
        result = []
        for pos in raw_positions:
            contracts = abs(float(pos.get("contracts", pos.get("size", "0"))))
            if contracts == 0:
                continue
            side_str = pos.get("side", "long")
            side = PositionSide.LONG if side_str == "long" else PositionSide.SHORT
            result.append(
                NormalizedPosition(
                    market_id=pos.get("symbol", "unknown"),
                    side=side,
                    size=Decimal(str(contracts)),
                    avg_entry_price=Decimal(str(pos.get("entryPrice", "0"))),
                    venue="aster",
                    current_price=Decimal(str(pos.get("markPrice", "0"))),
                    unrealized_pnl=Decimal(str(pos.get("unrealizedPnl", "0"))),
                )
            )
        return result
