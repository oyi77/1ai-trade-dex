"""Kalshi market provider plugin."""
from typing import List, Optional
from decimal import Decimal
import uuid

from backend.markets.base_provider import BaseMarketProvider, MarketProviderManifest, NormalizedOrder, NormalizedOrderResult, NormalizedBalance, NormalizedPosition, VenueCapability
from backend.markets.order_types import MarketInfo, OrderSide, OrderStatus
from backend.markets.provider_registry import market_registry
from loguru import logger

try:
    from backend.data.kalshi_client import KalshiClient
    HAS_KALSHI = True
except ImportError:
    HAS_KALSHI = False


@market_registry.plugin
class KalshiProvider(BaseMarketProvider):
    """Kalshi market provider plugin."""

    def __init__(self, paper_mode: bool = False):
        super().__init__(paper_mode=paper_mode)
        if not HAS_KALSHI:
            raise ImportError("Kalshi client not installed")
        self._client = KalshiClient()

    @classmethod
    def manifest(cls) -> MarketProviderManifest:
        return MarketProviderManifest(
            name="kalshi",
            display_name="Kalshi",
            version="1.0.0",
            venue_type="prediction_market",
            capabilities=[
                VenueCapability.LIMIT_ORDERS,
                VenueCapability.MARKET_ORDERS,
                VenueCapability.MARKET_SEARCH,
            ],
            supported_currencies=["USDC"],
            required_env_vars=["KALSHI_API_KEY_ID", "KALSHI_PRIVATE_KEY_PATH"],
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

        if order.price is None:
            return self._rejected(order, "Kalshi live provider requires a limit price")

        payload = self._to_kalshi_order(order)
        try:
            response = await self._client.batch_create_orders([payload])
        except Exception as exc:
            logger.exception("Kalshi provider order failed")
            return self._rejected(order, str(exc))

        order_result = self._extract_order_response(response)
        venue_order_id = str(
            order_result.get("order_id")
            or order_result.get("id")
            or payload["client_order_id"]
        )
        status = self._map_status(str(order_result.get("status", "open")))
        filled_size = Decimal(str(order_result.get("filled_count", order_result.get("filled_count_fp", 0))))
        remaining_size = max(order.size - filled_size, Decimal("0"))
        return NormalizedOrderResult(
            venue_order_id=venue_order_id,
            client_order_id=order.client_order_id,
            status=status,
            filled_size=filled_size,
            filled_avg_price=order.price if filled_size else None,
            remaining_size=remaining_size,
            fees_paid=Decimal("0"),
            raw=response,
        )

    async def cancel_order(self, venue_order_id: str) -> bool:
        if self._paper_mode:
            return True
        response = await self._client.batch_cancel_orders([venue_order_id])
        return bool(response)

    async def get_balance(self) -> NormalizedBalance:
        if not self._paper_mode:
            raw = await self._client.get_balance()
            available = Decimal(str(raw.get("available", raw.get("balance", raw.get("cash_balance", 0)))))
            locked = Decimal(str(raw.get("locked", raw.get("exposure", 0))))
            return NormalizedBalance(
                venue="kalshi",
                available_cash=available,
                total_equity=available + locked,
                reserved_margin=locked,
                raw=raw,
            )
        return NormalizedBalance(
            venue="kalshi",
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

    def _to_kalshi_order(self, order: NormalizedOrder) -> dict:
        side = "no" if order.side == OrderSide.NO else "yes"
        action = "sell" if order.side == OrderSide.SELL else "buy"
        price = order.price or Decimal("0.5")
        payload = {
            "ticker": order.market_id,
            "action": action,
            "side": side,
            "count_fp": f"{order.size:.2f}",
            "type": "limit",
            "client_order_id": order.client_order_id or str(uuid.uuid4()),
        }
        if side == "yes":
            payload["yes_price_dollars"] = float(price)
        else:
            payload["no_price_dollars"] = float(price)
        return payload

    @staticmethod
    def _extract_order_response(response: dict) -> dict:
        orders = response.get("orders") or response.get("order") or []
        if isinstance(orders, list) and orders:
            return orders[0]
        if isinstance(orders, dict):
            return orders
        return response if isinstance(response, dict) else {}

    @staticmethod
    def _map_status(status: str) -> OrderStatus:
        normalized = status.lower()
        if normalized in {"filled", "executed"}:
            return OrderStatus.FILLED
        if normalized in {"canceled", "cancelled"}:
            return OrderStatus.CANCELLED
        if normalized in {"rejected", "failed"}:
            return OrderStatus.REJECTED
        return OrderStatus.OPEN

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
