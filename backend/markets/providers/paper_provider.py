"""Paper trading provider for sandbox and testing."""
import logging
import uuid
from dataclasses import dataclass
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

logger = logging.getLogger(__name__)

# Polymarket taker fee: 100 bps (1%)
_POLYMARKET_TAKER_FEE_BPS = 100


@dataclass(frozen=True)
class OrderbookLevel:
    """Single price level in an orderbook."""
    price: Decimal
    size: Decimal  # shares available at this level


@dataclass(frozen=True)
class FillResult:
    """Result of orderbook-level fill simulation."""
    avg_price: Decimal
    total_cost: Decimal
    fee: Decimal
    slippage_bps: Decimal
    filled_size: Decimal
    levels_consumed: int


def _polymarket_fee(price: Decimal, size: Decimal, fee_bps: int = _POLYMARKET_TAKER_FEE_BPS) -> Decimal:
    """Exact Polymarket fee formula.

    fee = (fee_bps / 10000) * min(price, 1 - price) * size
    Fee is proportional to uncertainty — max at 0.50, near zero at extremes.
    """
    if fee_bps <= 0:
        return Decimal("0")
    uncertainty = min(price, Decimal("1") - price)
    fee = (Decimal(str(fee_bps)) / Decimal("10000")) * uncertainty * size
    if fee > 0:
        fee = max(fee, Decimal("0.0001"))
    return fee


def simulate_orderbook_fill(
    side: OrderSide,
    size: Decimal,
    orderbook: List[OrderbookLevel],
    fee_bps: int = _POLYMARKET_TAKER_FEE_BPS,
) -> FillResult:
    """Walk orderbook levels consuming liquidity to simulate a realistic fill.

    For BUY orders, walks ask levels (ascending price). For SELL orders, walks
    bid levels (descending price). Tracks weighted-average fill price, total
    cost, cumulative fees per level, and slippage in basis points vs best
    price.

    Args:
        side: BUY consumes asks, SELL consumes bids.
        size: Total shares to fill.
        orderbook: Levels sorted ascending (asks) or descending (bids).
        fee_bps: Fee in basis points per fill level.

    Returns:
        FillResult with avg_price, total_cost, fee, slippage_bps, filled_size,
        levels_consumed.

    Raises:
        ValueError: If orderbook is empty or insufficient liquidity.
    """
    if not orderbook:
        raise ValueError("Orderbook is empty")

    best_price = orderbook[0].price
    remaining = size
    total_cost = Decimal("0")
    total_fee = Decimal("0")
    total_filled = Decimal("0")
    levels_consumed = 0

    for level in orderbook:
        if remaining <= 0:
            break
        fill_qty = min(remaining, level.size)
        level_cost = level.price * fill_qty
        level_fee = _polymarket_fee(level.price, fill_qty, fee_bps)
        total_cost += level_cost
        total_fee += level_fee
        total_filled += fill_qty
        remaining -= fill_qty
        levels_consumed += 1

    if total_filled == 0:
        raise ValueError("Insufficient liquidity to fill any size")

    avg_price = total_cost / total_filled

    # Slippage in bps vs best price
    if best_price > 0:
        slippage_bps = abs(avg_price - best_price) / best_price * Decimal("10000")
    else:
        slippage_bps = Decimal("0")

    return FillResult(
        avg_price=avg_price,
        total_cost=total_cost,
        fee=total_fee,
        slippage_bps=slippage_bps,
        filled_size=total_filled,
        levels_consumed=levels_consumed,
    )


def check_limit_order_fill(
    order: NormalizedOrder,
    best_bid: Decimal,
    best_ask: Decimal,
) -> bool:
    """Check if a limit order should fill given current best bid/ask.

    BUY limit fills when ask <= limit price.
    SELL limit fills when bid >= limit price.
    """
    if order.price is None:
        return False
    if order.side == OrderSide.BUY:
        return best_ask <= order.price
    else:
        return best_bid >= order.price


@market_registry.plugin
class PaperProvider(BaseMarketProvider):
    """In-memory paper trading provider for testing and sandbox."""

    def __init__(self, paper_mode: bool = False):
        super().__init__(paper_mode=True)  # Always paper mode
        self._orders: Dict[str, NormalizedOrder] = {}
        self._positions: Dict[str, NormalizedPosition] = {}
        self._balance = Decimal("100000")
        self._total_pnl = Decimal("0")
        # Per-market orderbook snapshots: market_id -> list of levels (asks for BUY, bids for SELL)
        self._orderbooks: Dict[str, List[OrderbookLevel]] = {}

    def set_orderbook(self, market_id: str, levels: List[OrderbookLevel]) -> None:
        """Store orderbook snapshot for a market (used by orderbook fill simulation)."""
        self._orderbooks[market_id] = list(levels)

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
            taker_fee_bps=_POLYMARKET_TAKER_FEE_BPS,
            tags=["paper", "simulation", "testing"],
        )

    async def place_order(self, order: NormalizedOrder) -> NormalizedOrderResult:
        venue_id = f"paper_{uuid.uuid4().hex[:12]}"
        self._orders[venue_id] = order

        # Simulate fill for market orders
        if order.order_type == OrderType.MARKET:
            return self._fill_market_order(venue_id, order)

        # Limit orders stay open until price crosses
        return NormalizedOrderResult(
            venue_order_id=venue_id,
            client_order_id=order.client_order_id,
            status=OrderStatus.OPEN,
            filled_size=Decimal("0"),
            filled_avg_price=None,
            remaining_size=order.size,
            fees_paid=Decimal("0"),
        )

    def _fill_market_order(self, venue_id: str, order: NormalizedOrder) -> NormalizedOrderResult:
        """Fill a market order using orderbook simulation when available, single-price fallback otherwise."""
        levels = self._orderbooks.get(order.market_id)
        if levels:
            try:
                result = simulate_orderbook_fill(order.side, order.size, levels)
                self._update_position(order.market_id, order.side, result.filled_size, result.avg_price)
                return NormalizedOrderResult(
                    venue_order_id=venue_id,
                    client_order_id=order.client_order_id,
                    status=OrderStatus.FILLED,
                    filled_size=result.filled_size,
                    filled_avg_price=result.avg_price,
                    remaining_size=Decimal("0"),
                    fees_paid=result.fee,
                )
            except ValueError:
                # Insufficient orderbook liquidity -- fall through to single-price
                logger.debug("Orderbook fill failed for %s, falling back to single-price", order.market_id)

        # Fallback: single-price fill
        fill_price = order.price or Decimal("0.5")
        fee = _polymarket_fee(fill_price, order.size)
        self._update_position(order.market_id, order.side, order.size, fill_price)
        return NormalizedOrderResult(
            venue_order_id=venue_id,
            client_order_id=order.client_order_id,
            status=OrderStatus.FILLED,
            filled_size=order.size,
            filled_avg_price=fill_price,
            remaining_size=Decimal("0"),
            fees_paid=fee,
        )

    async def try_fill_limit_orders(self, market_id: str, best_bid: Decimal, best_ask: Decimal) -> List[NormalizedOrderResult]:
        """Check open limit orders against current market and fill those whose price has crossed.

        BUY limit fills at limit price when ask <= limit price.
        SELL limit fills at limit price when bid >= limit price.
        Returns list of filled order results.
        """
        filled: List[NormalizedOrderResult] = []
        to_remove: List[str] = []

        for venue_id, order in self._orders.items():
            if order.order_type != OrderType.LIMIT:
                continue
            if order.market_id != market_id:
                continue
            if order.price is None:
                continue

            should_fill = check_limit_order_fill(order, best_bid, best_ask)
            if not should_fill:
                continue

            # Fill at limit price (no slippage for limit orders)
            fill_price = order.price
            fee = _polymarket_fee(fill_price, order.size)
            self._update_position(order.market_id, order.side, order.size, fill_price)

            result = NormalizedOrderResult(
                venue_order_id=venue_id,
                client_order_id=order.client_order_id,
                status=OrderStatus.FILLED,
                filled_size=order.size,
                filled_avg_price=fill_price,
                remaining_size=Decimal("0"),
                fees_paid=fee,
            )
            filled.append(result)
            to_remove.append(venue_id)

        for vid in to_remove:
            del self._orders[vid]

        return filled

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
