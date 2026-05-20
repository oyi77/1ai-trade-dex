"""Tests for orderbook-level fill simulation in the paper provider."""
import asyncio
from decimal import Decimal

import pytest

from backend.markets.providers.paper_provider import (
    FillResult,
    OrderbookLevel,
    PaperProvider,
    _polymarket_fee,
    check_limit_order_fill,
    simulate_orderbook_fill,
)
from backend.markets.order_types import NormalizedOrder, OrderSide, OrderStatus, OrderType


# ---------------------------------------------------------------------------
# Helper to run async functions in tests
# ---------------------------------------------------------------------------
def run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


# ---------------------------------------------------------------------------
# simulate_orderbook_fill -- unit tests
# ---------------------------------------------------------------------------

class TestSimulateOrderbookFill:
    """Test the simulate_orderbook_fill function."""

    def test_market_buy_walks_multiple_levels(self):
        """BUY order consuming liquidity across 3 ask levels."""
        asks = [
            OrderbookLevel(price=Decimal("0.50"), size=Decimal("10")),
            OrderbookLevel(price=Decimal("0.52"), size=Decimal("15")),
            OrderbookLevel(price=Decimal("0.55"), size=Decimal("20")),
        ]
        # Want to buy 25 shares: 10 @ 0.50, 15 @ 0.52
        result = simulate_orderbook_fill(OrderSide.BUY, Decimal("25"), asks)

        assert result.filled_size == Decimal("25")
        assert result.levels_consumed == 2
        # avg_price = (0.50*10 + 0.52*15) / 25 = (5 + 7.8) / 25 = 12.8/25 = 0.512
        assert result.avg_price == Decimal("12.8") / Decimal("25")

    def test_market_sell_walks_bid_levels(self):
        """SELL order consuming liquidity across bid levels."""
        bids = [
            OrderbookLevel(price=Decimal("0.48"), size=Decimal("10")),
            OrderbookLevel(price=Decimal("0.46"), size=Decimal("10")),
        ]
        result = simulate_orderbook_fill(OrderSide.SELL, Decimal("15"), bids)

        assert result.filled_size == Decimal("15")
        # 10 @ 0.48, 5 @ 0.46 = (4.8 + 2.3) / 15 = 7.1/15
        assert result.avg_price == Decimal("7.1") / Decimal("15")

    def test_slippage_single_level_no_slippage(self):
        """Single-level fill has zero slippage."""
        levels = [OrderbookLevel(price=Decimal("0.50"), size=Decimal("100"))]
        result = simulate_orderbook_fill(OrderSide.BUY, Decimal("50"), levels)

        assert result.slippage_bps == Decimal("0")

    def test_slippage_multiple_levels_nonzero(self):
        """Multi-level fill has slippage vs best price."""
        asks = [
            OrderbookLevel(price=Decimal("0.50"), size=Decimal("10")),
            OrderbookLevel(price=Decimal("0.60"), size=Decimal("10")),
        ]
        result = simulate_orderbook_fill(OrderSide.BUY, Decimal("20"), asks)
        # avg_price = (0.50*10 + 0.60*10) / 20 = 0.55
        # slippage = |0.55 - 0.50| / 0.50 * 10000 = 0.05/0.50 * 10000 = 1000 bps
        assert result.slippage_bps == Decimal("1000")

    def test_fee_per_level(self):
        """Fee is accumulated across all fill levels."""
        asks = [
            OrderbookLevel(price=Decimal("0.50"), size=Decimal("10")),
            OrderbookLevel(price=Decimal("0.50"), size=Decimal("10")),
        ]
        result = simulate_orderbook_fill(OrderSide.BUY, Decimal("20"), asks)

        # Each level: fee = 100/10000 * min(0.50, 0.50) * 10 = 0.01 * 0.50 * 10 = 0.05
        # Two levels: total fee = 0.10
        expected_fee = _polymarket_fee(Decimal("0.50"), Decimal("10")) * 2
        assert result.fee == expected_fee

    def test_empty_orderbook_raises(self):
        """Empty orderbook raises ValueError."""
        with pytest.raises(ValueError, match="empty"):
            simulate_orderbook_fill(OrderSide.BUY, Decimal("10"), [])

    def test_exact_single_level_fill(self):
        """Filling exactly the size of one level works."""
        levels = [OrderbookLevel(price=Decimal("0.50"), size=Decimal("10"))]
        result = simulate_orderbook_fill(OrderSide.BUY, Decimal("10"), levels)

        assert result.filled_size == Decimal("10")
        assert result.avg_price == Decimal("0.50")
        assert result.levels_consumed == 1

    def test_partial_level_fill(self):
        """Partial fill on the last level."""
        levels = [
            OrderbookLevel(price=Decimal("0.50"), size=Decimal("10")),
            OrderbookLevel(price=Decimal("0.55"), size=Decimal("20")),
        ]
        # Want 15: 10 @ 0.50, 5 @ 0.55
        result = simulate_orderbook_fill(OrderSide.BUY, Decimal("15"), levels)

        assert result.filled_size == Decimal("15")
        # (0.50*10 + 0.55*5) / 15 = (5 + 2.75) / 15 = 7.75/15
        assert result.avg_price == Decimal("7.75") / Decimal("15")
        assert result.levels_consumed == 2


# ---------------------------------------------------------------------------
# check_limit_order_fill -- unit tests
# ---------------------------------------------------------------------------

class TestCheckLimitOrderFill:
    """Test the check_limit_order_fill function."""

    def test_buy_limit_fills_when_ask_crosses(self):
        """BUY limit at 0.50 fills when ask is at or below 0.50."""
        order = NormalizedOrder(
            market_id="m1",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            size=Decimal("10"),
            price=Decimal("0.50"),
        )
        assert check_limit_order_fill(order, Decimal("0.48"), Decimal("0.50")) is True

    def test_buy_limit_stays_open_when_ask_above(self):
        """BUY limit at 0.50 stays open when ask is 0.52."""
        order = NormalizedOrder(
            market_id="m1",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            size=Decimal("10"),
            price=Decimal("0.50"),
        )
        assert check_limit_order_fill(order, Decimal("0.48"), Decimal("0.52")) is False

    def test_sell_limit_fills_when_bid_crosses(self):
        """SELL limit at 0.50 fills when bid is at or above 0.50."""
        order = NormalizedOrder(
            market_id="m1",
            side=OrderSide.SELL,
            order_type=OrderType.LIMIT,
            size=Decimal("10"),
            price=Decimal("0.50"),
        )
        assert check_limit_order_fill(order, Decimal("0.50"), Decimal("0.52")) is True

    def test_sell_limit_stays_open_when_bid_below(self):
        """SELL limit at 0.50 stays open when bid is 0.48."""
        order = NormalizedOrder(
            market_id="m1",
            side=OrderSide.SELL,
            order_type=OrderType.LIMIT,
            size=Decimal("10"),
            price=Decimal("0.50"),
        )
        assert check_limit_order_fill(order, Decimal("0.48"), Decimal("0.50")) is False

    def test_no_price_returns_false(self):
        """Order with no price returns False."""
        order = NormalizedOrder(
            market_id="m1",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            size=Decimal("10"),
        )
        assert check_limit_order_fill(order, Decimal("0.48"), Decimal("0.50")) is False


# ---------------------------------------------------------------------------
# PaperProvider integration tests
# ---------------------------------------------------------------------------

class TestPaperProviderOrderbookFill:
    """Test PaperProvider orderbook fill integration."""

    @pytest.mark.asyncio
    async def test_market_order_walks_levels_with_orderbook(self):
        """Market BUY uses orderbook simulation when orderbook is set."""
        provider = PaperProvider()
        provider.set_orderbook("m1", [
            OrderbookLevel(price=Decimal("0.50"), size=Decimal("10")),
            OrderbookLevel(price=Decimal("0.55"), size=Decimal("20")),
        ])
        order = NormalizedOrder(
            market_id="m1",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            size=Decimal("15"),
        )
        result = await provider.place_order(order)

        assert result.status == OrderStatus.FILLED
        assert result.filled_size == Decimal("15")
        # 10 @ 0.50, 5 @ 0.55 = (5 + 2.75)/15 = 0.51666...
        expected_avg = (Decimal("0.50") * 10 + Decimal("0.55") * 5) / 15
        assert result.filled_avg_price == expected_avg
        assert result.fees_paid > 0

    @pytest.mark.asyncio
    async def test_market_order_fallback_no_orderbook(self):
        """Market order falls back to single-price fill when no orderbook data."""
        provider = PaperProvider()
        order = NormalizedOrder(
            market_id="m1",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            size=Decimal("10"),
            price=Decimal("0.45"),
        )
        result = await provider.place_order(order)

        assert result.status == OrderStatus.FILLED
        assert result.filled_avg_price == Decimal("0.45")
        assert result.filled_size == Decimal("10")

    @pytest.mark.asyncio
    async def test_limit_order_stays_open(self):
        """Limit order returns OPEN status and does not fill on placement."""
        provider = PaperProvider()
        order = NormalizedOrder(
            market_id="m1",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            size=Decimal("10"),
            price=Decimal("0.50"),
        )
        result = await provider.place_order(order)

        assert result.status == OrderStatus.OPEN
        assert result.filled_size == Decimal("0")
        assert result.filled_avg_price is None

    @pytest.mark.asyncio
    async def test_limit_order_fills_on_price_crossing(self):
        """Limit BUY fills at limit price when ask drops to or below limit."""
        provider = PaperProvider()
        order = NormalizedOrder(
            market_id="m1",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            size=Decimal("10"),
            price=Decimal("0.50"),
        )
        place_result = await provider.place_order(order)
        assert place_result.status == OrderStatus.OPEN

        # Price crosses: ask drops to 0.50
        filled = await provider.try_fill_limit_orders("m1", Decimal("0.48"), Decimal("0.50"))
        assert len(filled) == 1
        assert filled[0].status == OrderStatus.FILLED
        assert filled[0].filled_avg_price == Decimal("0.50")
        assert filled[0].filled_size == Decimal("10")

    @pytest.mark.asyncio
    async def test_limit_order_stays_open_when_price_doesnt_cross(self):
        """Limit BUY stays open when ask is above limit price."""
        provider = PaperProvider()
        order = NormalizedOrder(
            market_id="m1",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            size=Decimal("10"),
            price=Decimal("0.50"),
        )
        await provider.place_order(order)

        # Ask at 0.55 -- doesn't cross limit at 0.50
        filled = await provider.try_fill_limit_orders("m1", Decimal("0.48"), Decimal("0.55"))
        assert len(filled) == 0

        # Order should still be in the provider's open orders
        assert len(provider._orders) == 1

    @pytest.mark.asyncio
    async def test_limit_sell_fills_on_bid_crossing(self):
        """Limit SELL fills when bid rises to or above limit price."""
        provider = PaperProvider()
        order = NormalizedOrder(
            market_id="m1",
            side=OrderSide.SELL,
            order_type=OrderType.LIMIT,
            size=Decimal("10"),
            price=Decimal("0.50"),
        )
        await provider.place_order(order)

        filled = await provider.try_fill_limit_orders("m1", Decimal("0.50"), Decimal("0.52"))
        assert len(filled) == 1
        assert filled[0].filled_avg_price == Decimal("0.50")

    @pytest.mark.asyncio
    async def test_limit_order_fee_applied_on_fill(self):
        """Limit order fill applies Polymarket fee."""
        provider = PaperProvider()
        order = NormalizedOrder(
            market_id="m1",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            size=Decimal("10"),
            price=Decimal("0.50"),
        )
        await provider.place_order(order)
        filled = await provider.try_fill_limit_orders("m1", Decimal("0.48"), Decimal("0.50"))

        expected_fee = _polymarket_fee(Decimal("0.50"), Decimal("10"))
        assert filled[0].fees_paid == expected_fee
