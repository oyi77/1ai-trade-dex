"""Paper trading provider for sandbox and testing."""
import uuid
from typing import Dict, List, Optional
from decimal import Decimal

from backend.markets.base_provider import (
    BaseMarketProvider, MarketProviderManifest, NormalizedOrder,
    NormalizedOrderResult, NormalizedBalance, NormalizedPosition, VenueCapability,
)
from backend.markets.order_types import (
    MarketInfo, OrderSide, OrderType, OrderStatus,
    PositionSide,
)
from backend.markets.provider_registry import market_registry


@market_registry.plugin
class PaperProvider(BaseMarketProvider):
    """In-memory paper trading provider for testing and sandbox."""

    def __init__(self, paper_mode: bool = False):
        super().__init__(paper_mode=True)  # Always paper mode
        self._orders: Dict[str, NormalizedOrder] = {}
        self._positions: Dict[str, NormalizedPosition] = {}
        self._balance = Decimal("100000")
        self._total_pnl = Decimal("0")

    @classmethod
    def manifest(cls) -> MarketProviderManifest:
        return MarketProviderManifest(
            name="paper",
            display_name="Paper Trading",
            version="1.0.0",
            venue_type="simulation",
            capabilities=[
                VenueCapability.LIMIT_ORDERS,
                VenueCapability.MARKET_ORDERS,
                VenueCapability.BATCH_ORDERS,
            ],
            supported_currencies=["USDC"],
            required_env_vars=[],
            supports_paper_mode=True,
            is_live_venue=False,
            min_order_size_usd=0.01,
            maker_fee_bps=0,
            taker_fee_bps=0,
            tags=["paper", "simulation", "testing"],
        )

    async def place_order(self, order: NormalizedOrder) -> NormalizedOrderResult:
        venue_id = f"paper_{uuid.uuid4().hex[:12]}"
        self._orders[venue_id] = order

        # Simulate fill for market orders
        if order.order_type == OrderType.MARKET:
            fill_price = order.price or Decimal("0.5")
            self._update_position(order.market_id, order.side, order.size, fill_price)
            return NormalizedOrderResult(
                venue_order_id=venue_id,
                client_order_id=order.client_order_id,
                status=OrderStatus.FILLED,
                filled_size=order.size,
                filled_avg_price=fill_price,
                remaining_size=Decimal("0"),
                fees_paid=Decimal("0"),
            )

        # Limit orders stored as open
        if order.side == OrderSide.BUY:
            self._update_position(order.market_id, order.side, order.size, order.price or Decimal("0.5"))

        return NormalizedOrderResult(
            venue_order_id=venue_id,
            client_order_id=order.client_order_id,
            status=OrderStatus.OPEN,
            filled_size=Decimal("0"),
            filled_avg_price=None,
            remaining_size=order.size,
            fees_paid=Decimal("0"),
        )

    async def cancel_order(self, venue_order_id: str) -> bool:
        if venue_order_id in self._orders:
            del self._orders[venue_order_id]
            return True
        return False

    async def cancel_all_orders(self, market_id: Optional[str] = None) -> int:
        count = 0
        to_remove = []
        for oid, order in self._orders.items():
            if market_id is None or order.market_id == market_id:
                to_remove.append(oid)
                count += 1
        for oid in to_remove:
            del self._orders[oid]
        return count

    async def get_order(self, venue_order_id: str) -> NormalizedOrderResult:
        order = self._orders.get(venue_order_id)
        if not order:
            raise ValueError(f"Order {venue_order_id} not found")
        return NormalizedOrderResult(
            venue_order_id=venue_order_id,
            client_order_id=order.client_order_id,
            status=OrderStatus.OPEN,
            filled_size=Decimal("0"),
            filled_avg_price=None,
            remaining_size=order.size,
            fees_paid=Decimal("0"),
        )

    async def get_balance(self) -> NormalizedBalance:
        return NormalizedBalance(
            venue="paper",
            available_cash=self._balance,
            total_equity=self._balance + self._total_pnl,
            reserved_margin=Decimal("0"),
        )

    async def get_positions(
        self, market_id: Optional[str] = None
    ) -> List[NormalizedPosition]:
        positions = list(self._positions.values())
        if market_id:
            positions = [p for p in positions if p.market_id == market_id]
        return positions

    async def search_markets(
        self, query: Optional[str] = None, category: Optional[str] = None, limit: int = 50
    ) -> List[MarketInfo]:
        return []

    def _update_position(self, market_id: str, side: OrderSide, size: Decimal, price: Decimal):
        key = market_id
        if key in self._positions:
            pos = self._positions[key]
            new_size = pos.size + size if pos.side == side else pos.size - size
            if new_size <= 0:
                pnl = new_size * price
                self._total_pnl += pnl
                del self._positions[key]
            else:
                pos.size = new_size
        else:
            self._positions[key] = NormalizedPosition(
                market_id=market_id,
                side=PositionSide.LONG if side == OrderSide.BUY else PositionSide.SHORT,
                size=size,
                avg_entry_price=price,
                venue="paper",
            )
