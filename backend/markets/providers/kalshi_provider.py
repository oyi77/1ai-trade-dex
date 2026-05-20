"""Kalshi market provider plugin."""
import math
import os
from typing import List, Optional
from decimal import Decimal
import uuid

from backend.markets.base_provider import BaseMarketProvider, MarketProviderManifest, NormalizedOrder, NormalizedOrderResult, NormalizedBalance, NormalizedPosition, VenueCapability
from backend.markets.order_types import MarketInfo, OrderSide, OrderStatus, PositionSide
from backend.markets.provider_registry import market_registry
from loguru import logger

try:
    from backend.data.kalshi_client import KalshiClient
    HAS_KALSHI = True
except ImportError:
    HAS_KALSHI = False

KALSHI_TAKER_FEE_RATE = 0.07
KALSHI_MAKER_FEE_RATE = 0.0175


def _kalshi_fee(price: Decimal, size: Decimal, is_maker: bool = False) -> Decimal:
    """Kalshi fee model.

    Taker: ceil(contracts * P * (1-P) * 0.07 * 100)
    Maker: ceil(contracts * P * (1-P) * 0.0175 * 100)

    Fees peak at P=0.50 (max uncertainty), near zero at extremes.
    Returns fee in dollars (Decimal).
    """
    rate = KALSHI_MAKER_FEE_RATE if is_maker else KALSHI_TAKER_FEE_RATE
    p = float(price)
    p = max(0.01, min(0.99, p))
    fee_cents = math.ceil(float(size) * p * (1.0 - p) * rate * 100)
    return Decimal(str(fee_cents)) / Decimal("100")


if not os.getenv("KALSHI_API_KEY") and not os.getenv("KALSHI_API_KEY_ID"):
    logger.info("[KalshiProvider] KALSHI_API_KEY not set — provider disabled")


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
            maker_fee_bps=175,
            taker_fee_bps=700,
            tags=["primary", "prediction_market"],
        )

    async def place_order(self, order: NormalizedOrder) -> NormalizedOrderResult:
        if self._paper_mode:
            fill_price = order.price or Decimal("0.5")
            fee = _kalshi_fee(fill_price, order.size)
            return NormalizedOrderResult(
                venue_order_id=f"paper_{order.market_id}_{order.side.value}",
                client_order_id=order.client_order_id,
                status=OrderStatus.FILLED,
                filled_size=order.size,
                filled_avg_price=fill_price,
                remaining_size=Decimal("0"),
                fees_paid=fee,
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
        fees_paid_raw = order_result.get("fees", order_result.get("fee", 0))
        fees_paid = Decimal(str(fees_paid_raw)) if fees_paid_raw else _kalshi_fee(order.price, filled_size)
        remaining_size = max(order.size - filled_size, Decimal("0"))
        return NormalizedOrderResult(
            venue_order_id=venue_order_id,
            client_order_id=order.client_order_id,
            status=status,
            filled_size=filled_size,
            filled_avg_price=order.price if filled_size else None,
            remaining_size=remaining_size,
            fees_paid=fees_paid,
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
        try:
            raw_positions = await self._client.get_positions()
        except Exception as exc:
            logger.warning("KalshiProvider.get_positions failed: {}", exc)
            return []

        positions: List[NormalizedPosition] = []
        for p in raw_positions:
            ticker = p.get("ticker", p.get("market_id", ""))
            if market_id and ticker != market_id:
                continue
            side_raw = p.get("side", "yes")
            position_side = PositionSide.LONG if side_raw.lower() == "yes" else PositionSide.SHORT
            size = Decimal(str(p.get("count", p.get("count_fp", p.get("size", 0)))))
            entry_price = Decimal(str(p.get("average_price", p.get("entry_price", 0))))
            current_price_raw = p.get("current_price", p.get("last_price"))
            current_price = Decimal(str(current_price_raw)) if current_price_raw is not None else None
            positions.append(
                NormalizedPosition(
                    market_id=ticker,
                    side=position_side,
                    size=size,
                    avg_entry_price=entry_price,
                    venue="kalshi",
                    current_price=current_price,
                )
            )
        return positions

    async def search_markets(
        self, query: Optional[str] = None, category: Optional[str] = None, limit: int = 50
    ) -> List[MarketInfo]:
        params: dict = {"limit": min(limit, 200), "status": "open"}
        if category:
            params["category"] = category
        try:
            data = await self._client.get_markets(params=params)
        except Exception as exc:
            logger.warning("KalshiProvider.search_markets failed: {}", exc)
            return []

        raw_markets = data.get("markets", [])
        results: List[MarketInfo] = []
        for m in raw_markets:
            title = m.get("title", m.get("ticker", ""))
            if query and query.lower() not in title.lower():
                continue
            if category and m.get("category", "").lower() != category.lower():
                continue
            yes_price_raw = m.get("yes_bid", m.get("last_price", 50))
            yes_price = Decimal(str(yes_price_raw)) / Decimal("100") if float(yes_price_raw) > 1 else Decimal(str(yes_price_raw))
            no_price = Decimal("1") - yes_price
            volume_raw = m.get("volume", m.get("volume_24h", 0))
            open_interest_raw = m.get("open_interest", 0)
            results.append(
                MarketInfo(
                    venue="kalshi",
                    market_id=m.get("ticker", ""),
                    title=title,
                    description=m.get("subtitle", ""),
                    category=m.get("category", category or ""),
                    yes_price=yes_price,
                    no_price=no_price,
                    volume_24h=Decimal(str(volume_raw or 0)),
                    open_interest=Decimal(str(open_interest_raw or 0)),
                    closes_at=None,
                    is_active=m.get("status", "") == "open",
                    min_order_size=Decimal("1"),
                    tick_size=Decimal("0.01"),
                    raw=m,
                )
            )
            if len(results) >= limit:
                break
        return results

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
