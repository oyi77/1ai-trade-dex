"""Lighter DEX market provider plugin."""

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
class LighterProvider(BaseMarketProvider):
    """Lighter DEX market provider (zkLighter)."""

    def __init__(self, paper_mode: bool = False):
        super().__init__(paper_mode=paper_mode)
        from backend.clients.lighter_client import LighterClient

        self._client = LighterClient()

    @classmethod
    def manifest(cls) -> MarketProviderManifest:
        return MarketProviderManifest(
            name="lighter",
            display_name="Lighter",
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
            tags=["perps", "dex", "zk"],
        )

    async def place_order(self, order: NormalizedOrder) -> NormalizedOrderResult:
        """Place an order on Lighter."""
        if self._paper_mode:
            return NormalizedOrderResult(
                venue_order_id=f"paper_lt_{order.market_id}_{order.side.value}",
                client_order_id=order.client_order_id,
                status=OrderStatus.FILLED,
                filled_size=order.size,
                filled_avg_price=order.price or Decimal("0"),
                remaining_size=Decimal("0"),
                fees_paid=Decimal("0"),
            )
        try:
            side = "buy" if order.side in (OrderSide.YES, OrderSide.BUY) else "sell"
            # Lighter uses integer sizes/prices; pass as-is from normalized order
            order_type = 1 if order.order_type.value == "market" else 0
            time_in_force = 0 if order.order_type.value == "market" else 1
            result = await self._client.place_order(
                market_id=int(order.market_id),
                side=side,
                size=int(order.size),
                price=int(order.price) if order.price else 0,
                order_type=order_type,
                time_in_force=time_in_force,
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
            logger.exception("Lighter order failed")
            return self._rejected(order, str(exc))

    async def cancel_order(self, venue_order_id: str) -> bool:
        """Cancel an open order."""
        try:
            parts = venue_order_id.split(":", 1)
            market_id = int(parts[0])
            order_id = int(parts[1]) if len(parts) > 1 else int(venue_order_id)
            await self._client.cancel_order(market_id, order_id)
            return True
        except Exception as exc:
            logger.warning(f"Lighter cancel failed: {exc}")
            return False

    async def get_balance(self) -> NormalizedBalance:
        """Get account balance."""
        assets = await self._client.get_balance()
        # assets may be a list or dict depending on SDK version
        if isinstance(assets, list):
            usdc = next((a for a in assets if a.get("symbol") == "USDC"), {})
        elif isinstance(assets, dict):
            usdc = assets.get("USDC", assets)
        else:
            usdc = {}
        return NormalizedBalance(
            venue="lighter",
            available_cash=Decimal(str(usdc.get("availableBalance", usdc.get("free", "0")))),
            total_equity=Decimal(str(usdc.get("balance", usdc.get("total", "0")))),
            reserved_margin=Decimal(str(usdc.get("initialMargin", usdc.get("used", "0")))),
            currency="USDC",
            raw=assets if isinstance(assets, dict) else {"assets": assets},
        )

    async def get_positions(self, market_id=None) -> list[NormalizedPosition]:
        """Get open positions."""
        raw_positions = await self._client.get_positions()
        if not isinstance(raw_positions, list):
            raw_positions = raw_positions.get("positions", []) if isinstance(raw_positions, dict) else []
        result = []
        for pos in raw_positions:
            size = abs(int(pos.get("size", pos.get("contracts", "0"))))
            if size == 0:
                continue
            side_str = pos.get("side", "long")
            side = PositionSide.LONG if side_str == "long" else PositionSide.SHORT
            result.append(
                NormalizedPosition(
                    market_id=str(pos.get("market_id", pos.get("marketId", "unknown"))),
                    side=side,
                    size=Decimal(str(size)),
                    avg_entry_price=Decimal(str(pos.get("entry_price", pos.get("entryPrice", "0")))),
                    venue="lighter",
                    current_price=Decimal(str(pos.get("mark_price", pos.get("markPrice", "0")))),
                    unrealized_pnl=Decimal(str(pos.get("unrealized_pnl", pos.get("unrealizedPnl", "0")))),
                )
            )
        return result

    @staticmethod
    def _rejected(order: NormalizedOrder, reason: str) -> NormalizedOrderResult:
        logger.warning(f"[LighterProvider] Order rejected: {reason}")
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
        """Check if Lighter is accessible."""
        return await self._client.health_check()

    async def watch_account(self, on_update=None):
        """Subscribe to real-time account updates via WebSocket.

        Delegates to LighterClient.watch_account(). Pass a custom handler
        ``on_update(account_id, data)`` or use the client's default logger.
        """
        return await self._client.watch_account(on_update=on_update)
