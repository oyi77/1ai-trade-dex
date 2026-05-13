from decimal import Decimal
from backend.markets.order_types import (
    OrderSide,
    OrderType,
    OrderStatus,
    PositionSide,
    VenueCapability,
    NormalizedOrder,
    NormalizedOrderResult,
    NormalizedPosition,
    NormalizedBalance,
    NormalizedFillEvent,
)


class TestOrderSide:
    def test_order_side_yes(self):
        assert OrderSide.YES.value == "yes"

    def test_order_side_no(self):
        assert OrderSide.NO.value == "no"

    def test_order_side_buy(self):
        assert OrderSide.BUY.value == "buy"

    def test_order_side_sell(self):
        assert OrderSide.SELL.value == "sell"


class TestOrderType:
    def test_order_type_market(self):
        assert OrderType.MARKET.value == "market"

    def test_order_type_limit(self):
        assert OrderType.LIMIT.value == "limit"

    def test_order_type_fok(self):
        assert OrderType.FOK.value == "fill_or_kill"

    def test_order_type_ioc(self):
        assert OrderType.IOC.value == "immediate_or_cancel"


class TestOrderStatus:
    def test_order_status_pending(self):
        assert OrderStatus.PENDING.value == "pending"

    def test_order_status_open(self):
        assert OrderStatus.OPEN.value == "open"

    def test_order_status_partial(self):
        assert OrderStatus.PARTIAL.value == "partially_filled"

    def test_order_status_filled(self):
        assert OrderStatus.FILLED.value == "filled"

    def test_order_status_cancelled(self):
        assert OrderStatus.CANCELLED.value == "cancelled"

    def test_order_status_rejected(self):
        assert OrderStatus.REJECTED.value == "rejected"

    def test_order_status_expired(self):
        assert OrderStatus.EXPIRED.value == "expired"


class TestPositionSide:
    def test_position_side_long(self):
        assert PositionSide.LONG.value == "long"

    def test_position_side_short(self):
        assert PositionSide.SHORT.value == "short"


class TestVenueCapability:
    def test_venue_capability_limit_orders(self):
        assert VenueCapability.LIMIT_ORDERS.value == "limit_orders"

    def test_venue_capability_market_orders(self):
        assert VenueCapability.MARKET_ORDERS.value == "market_orders"

    def test_venue_capability_fok_orders(self):
        assert VenueCapability.FOK_ORDERS.value == "fok_orders"

    def test_venue_capability_short_selling(self):
        assert VenueCapability.SHORT_SELLING.value == "short_selling"

    def test_venue_capability_streaming_fills(self):
        assert VenueCapability.STREAMING_FILLS.value == "streaming_fills"

    def test_venue_capability_market_search(self):
        assert VenueCapability.MARKET_SEARCH.value == "market_search"

    def test_venue_capability_batch_orders(self):
        assert VenueCapability.BATCH_ORDERS.value == "batch_orders"


class TestNormalizedOrder:
    def test_normalized_order_basic(self):
        order = NormalizedOrder(
            market_id="BTC-USD",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            size=Decimal("100"),
            price=Decimal("50000"),
            client_order_id="client-123",
        )

        assert order.market_id == "BTC-USD"
        assert order.side == OrderSide.BUY
        assert order.order_type == OrderType.LIMIT
        assert order.size == Decimal("100")
        assert order.price == Decimal("50000")
        assert order.client_order_id == "client-123"
        assert order.time_in_force_seconds is None
        assert order.metadata == {}

    def test_normalized_order_no_price(self):
        order = NormalizedOrder(
            market_id="BTC-USD",
            side=OrderSide.SELL,
            order_type=OrderType.MARKET,
            size=Decimal("50"),
        )

        assert order.price is None
        assert order.order_type == OrderType.MARKET

    def test_normalized_order_with_metadata(self):
        order = NormalizedOrder(
            market_id="BTC-USD",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            size=Decimal("100"),
            metadata={"strategy": "test", "priority": 1},
        )

        assert order.metadata == {"strategy": "test", "priority": 1}


class TestNormalizedOrderResult:
    def test_normalized_order_result_basic(self):
        result = NormalizedOrderResult(
            venue_order_id="venue-123",
            client_order_id="client-123",
            status=OrderStatus.FILLED,
            filled_size=Decimal("100"),
            filled_avg_price=Decimal("50000"),
            remaining_size=Decimal("0"),
            fees_paid=Decimal("10"),
        )

        assert result.venue_order_id == "venue-123"
        assert result.client_order_id == "client-123"
        assert result.status == OrderStatus.FILLED
        assert result.filled_size == Decimal("100")
        assert result.filled_avg_price == Decimal("50000")
        assert result.remaining_size == Decimal("0")
        assert result.fees_paid == Decimal("10")
        assert result.raw == {}

    def test_normalized_order_result_no_client_id(self):
        result = NormalizedOrderResult(
            venue_order_id="venue-123",
            client_order_id=None,
            status=OrderStatus.PENDING,
            filled_size=Decimal("0"),
            filled_avg_price=None,
            remaining_size=Decimal("100"),
            fees_paid=Decimal("0"),
        )

        assert result.client_order_id is None
        assert result.filled_avg_price is None
        assert result.remaining_size == Decimal("100")

    def test_normalized_order_result_with_raw(self):
        result = NormalizedOrderResult(
            venue_order_id="venue-123",
            client_order_id="client-123",
            status=OrderStatus.PENDING,
            filled_size=Decimal("0"),
            filled_avg_price=None,
            remaining_size=Decimal("100"),
            fees_paid=Decimal("0"),
            raw={"extra_field": "value"},
        )

        assert result.raw == {"extra_field": "value"}


class TestNormalizedPosition:
    def test_normalized_position_basic(self):
        position = NormalizedPosition(
            market_id="BTC-USD",
            side=PositionSide.LONG,
            size=Decimal("100"),
            avg_entry_price=Decimal("50000"),
            venue="polymarket",
        )

        assert position.market_id == "BTC-USD"
        assert position.side == PositionSide.LONG
        assert position.size == Decimal("100")
        assert position.avg_entry_price == Decimal("50000")
        assert position.venue == "polymarket"
        assert position.current_price is None
        assert position.unrealized_pnl is None

    def test_normalized_position_with_pnl(self):
        position = NormalizedPosition(
            market_id="BTC-USD",
            side=PositionSide.SHORT,
            size=Decimal("50"),
            avg_entry_price=Decimal("51000"),
            venue="polymarket",
            current_price=Decimal("50000"),
            unrealized_pnl=Decimal("500"),
        )

        assert position.current_price == Decimal("50000")
        assert position.unrealized_pnl == Decimal("500")


class TestNormalizedBalance:
    def test_normalized_balance_basic(self):
        balance = NormalizedBalance(
            venue="polymarket",
            available_cash=Decimal("10000"),
            total_equity=Decimal("10000"),
            reserved_margin=Decimal("0"),
        )

        assert balance.venue == "polymarket"
        assert balance.available_cash == Decimal("10000")
        assert balance.total_equity == Decimal("10000")
        assert balance.reserved_margin == Decimal("0")
        assert balance.currency == "USDC"
        assert balance.raw == {}

    def test_normalized_balance_custom_currency(self):
        balance = NormalizedBalance(
            venue="test_venue",
            available_cash=Decimal("5000"),
            total_equity=Decimal("5000"),
            reserved_margin=Decimal("0"),
            currency="USD",
        )

        assert balance.currency == "USD"


class TestNormalizedFillEvent:
    def test_normalized_fill_event_basic(self):
        fill = NormalizedFillEvent(
            venue="polymarket",
            venue_order_id="venue-123",
            market_id="BTC-USD",
            side=OrderSide.BUY,
            filled_size=Decimal("100"),
            filled_price=Decimal("50000"),
            fill_timestamp=1234567890.0,
            is_final=True,
        )

        assert fill.venue == "polymarket"
        assert fill.venue_order_id == "venue-123"
        assert fill.market_id == "BTC-USD"
        assert fill.side == OrderSide.BUY
        assert fill.filled_size == Decimal("100")
        assert fill.filled_price == Decimal("50000")
        assert fill.fill_timestamp == 1234567890.0
        assert fill.is_final is True


def test_order_side_all_values():
    sides = [OrderSide.YES, OrderSide.NO, OrderSide.BUY, OrderSide.SELL]
    assert len(sides) == 4


def test_order_type_all_values():
    types = [OrderType.MARKET, OrderType.LIMIT, OrderType.FOK, OrderType.IOC]
    assert len(types) == 4


def test_order_status_all_values():
    statuses = [
        OrderStatus.PENDING,
        OrderStatus.OPEN,
        OrderStatus.PARTIAL,
        OrderStatus.FILLED,
        OrderStatus.CANCELLED,
        OrderStatus.REJECTED,
        OrderStatus.EXPIRED,
    ]
    assert len(statuses) == 7
