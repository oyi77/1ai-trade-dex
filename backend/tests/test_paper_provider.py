"""Test suite for paper trading provider."""
import pytest
from decimal import Decimal

from backend.markets.providers.paper_provider import PaperProvider
from backend.markets.order_types import (
    NormalizedOrder, OrderSide, OrderType, OrderStatus,
)


@pytest.fixture
def paper_provider():
    """Create a paper provider instance."""
    return PaperProvider(paper_mode=True)


class TestPaperProviderInitialization:
    """Tests for paper provider initialization (Task 32)."""

    def test_initializes_correctly(self, paper_provider):
        """Paper provider initializes with correct default values."""
        assert paper_provider._paper_mode is True
        assert paper_provider._orders == {}
        assert paper_provider._positions == {}
        assert paper_provider._balance == Decimal("100000")
        assert paper_provider._total_pnl == Decimal("0")

    def test_paper_mode_injected(self, paper_provider):
        """Paper mode is correctly injected and always True."""
        assert paper_provider._paper_mode is True
        assert paper_provider.manifest().supports_paper_mode is True
        assert paper_provider.manifest().is_live_venue is False


class TestPaperProviderPlaceOrder:
    """Tests for paper provider order placement."""

    @pytest.mark.asyncio
    async def test_place_order_market_returns_mock_result(self, paper_provider):
        """Place order returns mock result for market orders."""
        order = NormalizedOrder(
            market_id="TEST_MARKET",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            size=Decimal("100"),
            price=None,
        )

        result = await paper_provider.place_order(order)

        assert result.venue_order_id.startswith("paper_")
        assert result.status == OrderStatus.FILLED
        assert result.filled_size == Decimal("100")
        assert result.filled_avg_price == Decimal("0.5")

    @pytest.mark.asyncio
    async def test_place_order_limit_stored_as_open(self, paper_provider):
        """Place order stores limit orders as open."""
        order = NormalizedOrder(
            market_id="TEST_MARKET",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            size=Decimal("100"),
            price=Decimal("0.6"),
        )

        result = await paper_provider.place_order(order)

        assert result.venue_order_id.startswith("paper_")
        assert result.status == OrderStatus.OPEN
        assert result.filled_size == Decimal("0")

    @pytest.mark.asyncio
    async def test_place_order_limit_does_not_update_position(self, paper_provider):
        """Open limit orders must not create exposure before a fill."""
        order = NormalizedOrder(
            market_id="TEST_MARKET",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            size=Decimal("100"),
            price=Decimal("0.6"),
        )

        result = await paper_provider.place_order(order)
        positions = await paper_provider.get_positions()

        assert result.status == OrderStatus.OPEN
        assert result.filled_size == Decimal("0")
        assert result.remaining_size == Decimal("100")
        assert positions == []

    @pytest.mark.asyncio
    async def test_place_order_updates_position(self, paper_provider):
        """Place order updates internal position tracking."""
        order = NormalizedOrder(
            market_id="TEST_MARKET",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            size=Decimal("100"),
            price=None,
        )

        await paper_provider.place_order(order)

        positions = await paper_provider.get_positions()
        assert len(positions) == 1
        assert positions[0].market_id == "TEST_MARKET"
        assert positions[0].side.value == "long"


class TestPaperProviderCancelOrder:
    """Tests for paper provider order cancellation."""

    @pytest.mark.asyncio
    async def test_cancel_order_works(self, paper_provider):
        """Cancel order removes order from registry."""
        order = NormalizedOrder(
            market_id="TEST_MARKET",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            size=Decimal("100"),
            price=Decimal("0.6"),
        )

        result = await paper_provider.place_order(order)
        venue_id = result.venue_order_id

        success = await paper_provider.cancel_order(venue_id)

        assert success is True
        assert venue_id not in paper_provider._orders

    @pytest.mark.asyncio
    async def test_cancel_order_returns_false_for_missing(self, paper_provider):
        """Cancel order returns False for non-existent order."""
        success = await paper_provider.cancel_order("nonexistent")
        assert success is False


class TestPaperProviderGetBalance:
    """Tests for paper provider balance queries."""

    @pytest.mark.asyncio
    async def test_get_balance_returns_mock_balance(self, paper_provider):
        """Get balance returns initial mock balance."""
        balance = await paper_provider.get_balance()

        assert balance.venue == "paper"
        assert balance.available_cash == Decimal("100000")
        assert balance.total_equity == Decimal("100000")
        assert balance.reserved_margin == Decimal("0")


class TestPaperProviderGetPositions:
    """Tests for paper provider position queries."""

    @pytest.mark.asyncio
    async def test_get_positions_returns_empty_list(self, paper_provider):
        """Get positions returns empty list when no positions."""
        positions = await paper_provider.get_positions()
        assert positions == []

    @pytest.mark.asyncio
    async def test_get_positions_with_trade(self, paper_provider):
        """Get positions returns positions after placing orders."""
        order = NormalizedOrder(
            market_id="TEST_MARKET",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            size=Decimal("100"),
            price=None,
        )

        await paper_provider.place_order(order)

        positions = await paper_provider.get_positions()
        assert len(positions) == 1
        assert positions[0].market_id == "TEST_MARKET"


class TestPaperProviderGetOrder:
    """Tests for paper provider order retrieval."""

    @pytest.mark.asyncio
    async def test_get_order_returns_open_status(self, paper_provider):
        """Get order returns open status for limit orders."""
        order = NormalizedOrder(
            market_id="TEST_MARKET",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            size=Decimal("100"),
            price=Decimal("0.6"),
        )

        result = await paper_provider.place_order(order)
        venue_id = result.venue_order_id

        retrieved = await paper_provider.get_order(venue_id)

        assert retrieved.venue_order_id == venue_id
        assert retrieved.status == OrderStatus.OPEN
        assert retrieved.filled_size == Decimal("0")
        assert retrieved.remaining_size == Decimal("100")

    @pytest.mark.asyncio
    async def test_get_order_raises_for_not_found(self, paper_provider):
        """Get order raises ValueError for missing order."""
        with pytest.raises(ValueError):
            await paper_provider.get_order("nonexistent")


class TestPaperProviderCancelAllOrders:
    """Tests for paper provider bulk order cancellation."""

    @pytest.mark.asyncio
    async def test_cancel_all_orders_works(self, paper_provider):
        """Cancel all orders removes all stored orders."""
        order1 = NormalizedOrder(
            market_id="TEST_MARKET_1",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            size=Decimal("100"),
            price=Decimal("0.6"),
        )
        order2 = NormalizedOrder(
            market_id="TEST_MARKET_2",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            size=Decimal("100"),
            price=Decimal("0.6"),
        )

        await paper_provider.place_order(order1)
        await paper_provider.place_order(order2)

        count = await paper_provider.cancel_all_orders()

        assert count == 2
        assert paper_provider._orders == {}

    @pytest.mark.asyncio
    async def test_cancel_all_orders_market_filter(self, paper_provider):
        """Cancel all orders filters by market_id when provided."""
        order1 = NormalizedOrder(
            market_id="TEST_MARKET_1",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            size=Decimal("100"),
            price=Decimal("0.6"),
        )
        order2 = NormalizedOrder(
            market_id="TEST_MARKET_2",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            size=Decimal("100"),
            price=Decimal("0.6"),
        )

        await paper_provider.place_order(order1)
        await paper_provider.place_order(order2)

        count = await paper_provider.cancel_all_orders(market_id="TEST_MARKET_1")

        assert count == 1
        assert len(paper_provider._orders) == 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
