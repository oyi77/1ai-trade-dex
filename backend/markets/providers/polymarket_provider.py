"""Polymarket market provider plugin."""
from typing import List, Optional
from decimal import Decimal
import uuid

from backend.markets.base_provider import BaseMarketProvider, MarketProviderManifest, NormalizedOrder, NormalizedOrderResult, NormalizedBalance, NormalizedPosition, VenueCapability
from backend.markets.order_types import MarketInfo, OrderSide, OrderStatus
from backend.markets.provider_registry import market_registry
from backend.config import settings
from loguru import logger

try:
    from backend.data.polymarket_clob import clob_from_settings
    HAS_POLYMARKET = True
except ImportError:
    HAS_POLYMARKET = False


@market_registry.plugin
class PolymarketProvider(BaseMarketProvider):
    """Polymarket CLOB market provider plugin."""

    def __init__(self, paper_mode: bool = False):
        super().__init__(paper_mode=paper_mode)
        if not HAS_POLYMARKET:
            raise ImportError("py-clob-client not installed")
        self._mode = "paper" if paper_mode else settings.TRADING_MODE

    @classmethod
    def manifest(cls) -> MarketProviderManifest:
        return MarketProviderManifest(
            name="polymarket",
            display_name="Polymarket",
            version="1.0.0",
            venue_type="prediction_market",
            capabilities=[
                VenueCapability.LIMIT_ORDERS,
                VenueCapability.MARKET_ORDERS,
                VenueCapability.MARKET_SEARCH,
                VenueCapability.STREAMING_FILLS,
            ],
            supported_currencies=["USDC"],
            required_env_vars=["POLYMARKET_API_KEY", "POLYMARKET_API_SECRET"],
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

        price = order.price
        if price is None:
            return self._rejected(order, "Polymarket live provider requires a limit price")

        token_id = self._resolve_token_id(order)
        if not token_id:
            return self._rejected(order, "Polymarket live provider requires a CLOB token_id")

        clob_side = "SELL" if order.side == OrderSide.SELL else "BUY"
        try:
            async with clob_from_settings(mode=self._mode) as clob:
                result = await clob.place_limit_order(
                    token_id=token_id,
                    side=clob_side,
                    price=float(price),
                    size=float(order.size),
                )
        except Exception as exc:
            logger.exception("Polymarket provider order failed")
            return self._rejected(order, str(exc))

        if not result.success:
            return self._rejected(order, result.error or "Polymarket rejected order")

        filled_size = Decimal(str(result.fill_size or 0))
        fill_price = Decimal(str(result.fill_price)) if result.fill_price is not None else price
        remaining = Decimal("0") if filled_size else order.size
        status = OrderStatus.FILLED if filled_size else OrderStatus.OPEN
        return NormalizedOrderResult(
            venue_order_id=result.order_id or f"polymarket_{uuid.uuid4().hex}",
            client_order_id=order.client_order_id,
            status=status,
            filled_size=filled_size,
            filled_avg_price=fill_price if filled_size else None,
            remaining_size=remaining,
            fees_paid=Decimal("0"),
            raw={"idempotency_key": result.idempotency_key},
        )

    async def cancel_order(self, venue_order_id: str) -> bool:
        if self._paper_mode:
            return True
        async with clob_from_settings(mode=self._mode) as clob:
            return await clob.cancel_order(venue_order_id)

    async def get_balance(self) -> NormalizedBalance:
        if not self._paper_mode:
            async with clob_from_settings(mode=self._mode) as clob:
                raw = await clob.get_wallet_balance()
            available = Decimal(str(raw.get("usdc_balance", 0)))
            return NormalizedBalance(
                venue="polymarket",
                available_cash=available,
                total_equity=available,
                reserved_margin=Decimal("0"),
                raw=raw,
            )
        return NormalizedBalance(
            venue="polymarket",
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

    def _resolve_token_id(self, order: NormalizedOrder) -> str:
        metadata = order.metadata or {}
        if order.side == OrderSide.NO:
            return str(metadata.get("no_token_id") or metadata.get("token_id") or order.market_id)
        return str(metadata.get("yes_token_id") or metadata.get("clob_token_id") or metadata.get("token_id") or order.market_id)

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
