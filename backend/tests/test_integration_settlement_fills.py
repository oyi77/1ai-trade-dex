"""Integration tests for settlement and fill processing system."""

from datetime import datetime, timezone
from decimal import Decimal

from backend.markets.order_types import NormalizedFillEvent, OrderSide
from backend.core.settlement_helpers import _looks_like_token_id, calculate_pnl
from backend.models.database import Trade


class TestFillEventProcessing:
    def test_create_fill_event(self):
        fill = NormalizedFillEvent(
            venue="polymarket",
            venue_order_id="order_123",
            market_id="BTC-USD",
            side=OrderSide.YES,
            filled_size=Decimal("10.5"),
            filled_price=Decimal("0.65"),
            fill_timestamp=datetime.now(timezone.utc).timestamp(),
            is_final=True
        )

        assert fill.venue == "polymarket"
        assert fill.filled_size == Decimal("10.5")
        assert fill.is_final is True

    def test_fill_event_marks_final(self):
        fill = NormalizedFillEvent(
            venue="kalshi",
            venue_order_id="order_456",
            market_id="TEMP-NYC",
            side=OrderSide.NO,
            filled_size=Decimal("50"),
            filled_price=Decimal("0.45"),
            fill_timestamp=datetime.now(timezone.utc).timestamp(),
            is_final=True
        )

        assert fill.is_final is True
        assert fill.venue_order_id == "order_456"

    def test_fill_event_partial_vs_final(self):
        partial = NormalizedFillEvent(
            venue="polymarket",
            venue_order_id="order_1",
            market_id="BTC-USD",
            side=OrderSide.BUY,
            filled_size=Decimal("5"),
            filled_price=Decimal("0.55"),
            fill_timestamp=datetime.now(timezone.utc).timestamp(),
            is_final=False
        )

        final = NormalizedFillEvent(
            venue="polymarket",
            venue_order_id="order_1",
            market_id="BTC-USD",
            side=OrderSide.BUY,
            filled_size=Decimal("10"),
            filled_price=Decimal("0.55"),
            fill_timestamp=datetime.now(timezone.utc).timestamp(),
            is_final=True
        )

        assert partial.is_final is False
        assert final.is_final is True

    def test_fill_event_venue_differentiation(self):
        Polymarket_event = NormalizedFillEvent(
            venue="polymarket",
            venue_order_id="pm_order",
            market_id="BTC-USD",
            side=OrderSide.YES,
            filled_size=Decimal("10"),
            filled_price=Decimal("0.60"),
            fill_timestamp=datetime.now(timezone.utc).timestamp(),
            is_final=True
        )

        Kalshi_event = NormalizedFillEvent(
            venue="kalshi",
            venue_order_id="kalshi_order",
            market_id="TEMP-NYC",
            side=OrderSide.NO,
            filled_size=Decimal("100"),
            filled_price=Decimal("0.50"),
            fill_timestamp=datetime.now(timezone.utc).timestamp(),
            is_final=True
        )

        assert Polymarket_event.venue == "polymarket"
        assert Kalshi_event.venue == "kalshi"


class TestTradeSettlementIntegration:
    def test_calculate_pnl_long_profit(self, db):
        trade = Trade(
            signal_id=1,
            strategy="test",
            market_ticker="BTC-USD",
            market_type="btc",
            direction="up",
            entry_price=0.60,
            size=100
        )
        db.add(trade)
        db.commit()

        settlement_value = 1.0
        pnl = calculate_pnl(trade, settlement_value)

        # size is dollars; calculate_pnl converts to shares: 100/0.60 = 166.67
        expected_pnl = round((1.0 - 0.60) * (100 / 0.60), 2)
        assert pnl == expected_pnl
        assert pnl > 0

    def test_calculate_pnl_long_loss(self, db):
        trade = Trade(
            signal_id=1,
            strategy="test",
            market_ticker="BTC-USD",
            market_type="btc",
            direction="up",
            entry_price=0.60,
            size=100
        )
        db.add(trade)
        db.commit()

        settlement_value = 0.0
        pnl = calculate_pnl(trade, settlement_value)

        # loss = -(entry_price * shares) = -(0.60 * 166.67) = -100.0
        expected_loss = round(-(0.60 * (100 / 0.60)), 2)
        assert pnl == expected_loss
        assert pnl < 0

    def test_calculate_pnl_short_profit(self, db):
        trade = Trade(
            signal_id=1,
            strategy="test",
            market_ticker="BTC-USD",
            market_type="btc",
            direction="down",
            entry_price=0.50,
            size=100
        )
        db.add(trade)
        db.commit()

        settlement_value = 0.0
        pnl = calculate_pnl(trade, settlement_value)

        # shares = 100/0.50 = 200; profit = (1.0 - 0.50) * 200 = 100.0
        expected_pnl = round((1.0 - 0.50) * (100 / 0.50), 2)
        assert pnl == expected_pnl
        assert pnl > 0

    def test_calculate_pnl_short_loss(self, db):
        trade = Trade(
            signal_id=1,
            strategy="test",
            market_ticker="BTC-USD",
            market_type="btc",
            direction="down",
            entry_price=0.50,
            size=100
        )
        db.add(trade)
        db.commit()

        settlement_value = 1.0
        pnl = calculate_pnl(trade, settlement_value)

        # loss = -(entry_price * shares) = -(0.50 * 200) = -100.0
        expected_loss = round(-(0.50 * (100 / 0.50)), 2)
        assert pnl == expected_loss
        assert pnl < 0


class TestMarketSettlementIntegration:
    def test_token_id_recognition(self):
        valid_token = "1000000000000000000000000000000000000000000000000000000000000000001"
        assert _looks_like_token_id(valid_token) is True

        invalid_token = "short"
        assert _looks_like_token_id(invalid_token) is False

        slug_like = "BTC-USD-slug"
        assert _looks_like_token_id(slug_like) is False

    def test_settlement_event_creation(self, db):
        settlement = Trade(
            signal_id=1,
            strategy="test",
            market_ticker="BTC-USD",
            market_type="btc",
            direction="up",
            entry_price=0.50,
            size=100,
            settled=True,
            settlement_time=datetime.now(timezone.utc),
            settlement_value=0.75
        )
        db.add(settlement)
        db.commit()

        retrieved = db.query(Trade).filter(Trade.market_ticker == "BTC-USD").first()
        assert retrieved is not None
        assert retrieved.settled is True

    def test_settlement_tracking_across_providers(self, db):
        Polymarket_trade = Trade(
            signal_id=1,
            strategy="test",
            market_ticker="BTC-USD",
            market_type="btc",
            direction="up",
            entry_price=0.50,
            size=100,
            source="polymarket"
        )
        Kalshi_trade = Trade(
            signal_id=2,
            strategy="test",
            market_ticker="TEMP-NYC",
            market_type="weather",
            direction="down",
            entry_price=0.50,
            size=100,
            source="kalshi"
        )

        db.add_all([Polymarket_trade, Kalshi_trade])
        db.commit()

        Polymarket_retrieved = db.query(Trade).filter(Trade.source == "polymarket").first()
        Kalshi_retrieved = db.query(Trade).filter(Trade.source == "kalshi").first()

        assert Polymarket_retrieved.market_ticker == "BTC-USD"
        assert Kalshi_retrieved.market_ticker == "TEMP-NYC"


class TestPnLSettlementIntegration:
    def test_pnl_from_multiple_fills(self, db):
        fills = [
            NormalizedFillEvent(
                venue="polymarket",
                venue_order_id="order_1",
                market_id="BTC-USD",
                side=OrderSide.YES,
                filled_size=Decimal("50"),
                filled_price=Decimal("0.60"),
                fill_timestamp=datetime.now(timezone.utc).timestamp(),
                is_final=False
            ),
            NormalizedFillEvent(
                venue="polymarket",
                venue_order_id="order_1",
                market_id="BTC-USD",
                side=OrderSide.YES,
                filled_size=Decimal("50"),
                filled_price=Decimal("0.62"),
                fill_timestamp=datetime.now(timezone.utc).timestamp(),
                is_final=True
            )
        ]

        total_size = sum(f.filled_size for f in fills)
        avg_price = sum(f.filled_price * f.filled_size for f in fills) / total_size

        assert total_size == Decimal("100")
        assert avg_price == Decimal("0.61")

    def test_pnl_result_marking(self, db):
        trade = Trade(
            signal_id=1,
            strategy="test_strategy",
            market_ticker="BTC-USD",
            pnl=10.0,
            result="pending",
            settled=False
        )
        db.add(trade)
        db.commit()

        if trade.pnl > 0:
            trade.result = "win"
        elif trade.pnl < 0:
            trade.result = "loss"
        else:
            trade.result = "push"

        db.commit()

        retrieved = db.query(Trade).filter_by(id=trade.id).first()
        assert retrieved.result == "win"

    def test_settlement_timestamp_recording(self, db):
        settlement_time = datetime.now(timezone.utc)
        trade = Trade(
            signal_id=1,
            strategy="test_strategy",
            market_ticker="BTC-USD",
            pnl=5.0,
            settled=True,
            result="win",
            settlement_time=settlement_time
        )
        db.add(trade)
        db.commit()

        retrieved = db.query(Trade).filter_by(id=trade.id).first()
        assert retrieved.settlement_time is not None
        assert retrieved.result == "win"
