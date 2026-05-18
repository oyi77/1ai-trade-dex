"""Tests for Enhanced Paper Trader."""

from backend.core.paper_trader_enhanced import (
    EnhancedPaperTrader,
    SimulatedFill,
    PaperTradeResult,
)


def make_book():
    return {
        "bids": [
            {"price": "0.48", "size": "100"},
            {"price": "0.47", "size": "200"},
        ],
        "asks": [
            {"price": "0.52", "size": "100"},
            {"price": "0.53", "size": "200"},
        ],
    }


class TestEnhancedPaperTrader:
    def setup_method(self):
        self.trader = EnhancedPaperTrader(
            initial_bankroll=100.0,
            platform_fee_pct=0.01,
            simulated_latency_ms=10.0,
            max_slippage_pct=0.10,
        )

    def test_initial_state(self):
        assert self.trader.bankroll == 100.0
        assert len(self.trader.positions) == 0
        assert len(self.trader.trade_history) == 0

    def test_update_order_book(self):
        book = make_book()
        self.trader.update_order_book("m1", book["bids"], book["asks"])
        assert "m1" in self.trader._order_book

    def test_trade_without_book(self):
        result = self.trader.execute_trade("m1", "yes", 10.0)
        assert result.success is False
        assert "No order book" in result.rejection_reason

    def test_trade_zero_size(self):
        result = self.trader.execute_trade("m1", "yes", 0.0)
        assert result.success is False

    def test_trade_insufficient_bankroll(self):
        self.trader.update_order_book("m1", **make_book())
        result = self.trader.execute_trade("m1", "yes", 200.0)
        assert result.success is False
        assert "Insufficient" in result.rejection_reason

    def test_trade_success(self):
        self.trader.update_order_book("m1", **make_book())
        result = self.trader.execute_trade("m1", "yes", 5.0)
        assert result.success is True
        assert result.fill is not None
        assert result.fill.price >= 0.52  # bought from asks
        assert "m1_yes" in self.trader.positions
        assert self.trader.bankroll < 100.0

    def test_close_position(self):
        self.trader.update_order_book("m1", **make_book())
        self.trader.execute_trade("m1", "yes", 5.0)
        result = self.trader.close_position("m1", "yes")
        assert result.success is True
        assert "m1_yes" not in self.trader.positions

    def test_close_no_position(self):
        result = self.trader.close_position("m1", "yes")
        assert result.success is False

    def test_portfolio_summary(self):
        self.trader.update_order_book("m1", **make_book())
        self.trader.execute_trade("m1", "yes", 5.0)
        summary = self.trader.get_portfolio_summary()
        assert summary["positions"] == 1
        assert summary["trades_executed"] == 1
        assert summary["total_exposure"] > 0

    def test_update_positions(self):
        self.trader.update_order_book("m1", **make_book())
        self.trader.execute_trade("m1", "yes", 5.0)
        self.trader.update_positions()
        pos = self.trader.positions["m1_yes"]
        assert pos.current_price > 0

    def test_multiple_fills_averages_in(self):
        self.trader.update_order_book("m1", **make_book())
        self.trader.execute_trade("m1", "yes", 2.0)
        self.trader.execute_trade("m1", "yes", 2.0)
        pos = self.trader.positions["m1_yes"]
        assert len(pos.fills) == 2
        assert pos.size > 2.0


class TestSimulatedFill:
    def test_fields(self):
        f = SimulatedFill(price=0.5, size=10.0, slippage=0.01, latency_ms=50.0, partial=False, timestamp=0.0)
        assert f.price == 0.5
        assert f.partial is False


class TestPaperTradeResult:
    def test_success_result(self):
        r = PaperTradeResult(success=True, order_value=5.0, fee=0.05)
        assert r.success is True
        assert r.rejection_reason is None

    def test_failure_result(self):
        r = PaperTradeResult(success=False, rejection_reason="no data")
        assert r.success is False
