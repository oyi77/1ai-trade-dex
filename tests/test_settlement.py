"""Tests for trade settlement logic."""
import pytest
from unittest.mock import AsyncMock, patch

from backend.core.settlement import calculate_pnl, _parse_market_resolution, check_market_settlement
from backend.models.database import Trade


def make_trade(**kwargs) -> Trade:
    """Factory for Trade objects with sensible defaults."""
    t = Trade()
    t.id = kwargs.get("id", 1)
    t.market_ticker = kwargs.get("market_ticker", "test-market")
    t.event_slug = kwargs.get("event_slug", None)
    t.direction = kwargs.get("direction", "up")
    t.entry_price = kwargs.get("entry_price", 0.60)
    t.size = kwargs.get("size", 100.0)
    t.settled = False
    t.signal_id = None
    t.market_type = kwargs.get("market_type", "btc")
    t.trading_mode = kwargs.get("trading_mode", "paper")
    return t


def pnl_win(size: float, entry: float) -> float:
    """Expected P&L on a win (with Polymarket taker fee).

    Pipeline stores `size` as DOLLAR AMOUNT. calculate_pnl converts
    dollars to shares: shares = dollar_cost / entry_price.
    Fee = (100/10000) * min(entry, 1-entry) * size
    dollar_cost = size + fee
    Net profit = shares - dollar_cost.
    """
    fee_bps = 100
    uncertainty = min(entry, 1.0 - entry)
    fee = (fee_bps / 10000.0) * uncertainty * size
    dollar_cost = size + fee
    shares = dollar_cost / entry
    return round(shares - dollar_cost, 2)


def pnl_loss(size: float, entry: float) -> float:
    """Expected P&L on a loss (with Polymarket taker fee).

    dollar_cost = size + fee. Loss = -dollar_cost.
    """
    fee_bps = 100
    uncertainty = min(entry, 1.0 - entry)
    fee = (fee_bps / 10000.0) * uncertainty * size
    dollar_cost = size + fee
    return round(-dollar_cost, 2)


class TestCalculatePnl:
    """Test P&L calculation for all direction/outcome combinations.

    Polymarket CLOB economics (size = shares, not dollars):
      - `size` = number of shares purchased.
      - `entry_price` = cost per share (0.0–1.0).
      - On a win, each share pays $1.00 → pnl = (1 - entry_price) * size.
      - On a loss, shares are worth $0 → pnl = -(entry_price * size).
    """

    def test_up_wins(self):
        trade = make_trade(direction="up", entry_price=0.65, size=100.0)
        pnl = calculate_pnl(trade, settlement_value=1.0)
        assert pnl == pnl_win(100.0, 0.65)  # +35.00

    def test_up_loses(self):
        trade = make_trade(direction="up", entry_price=0.65, size=100.0)
        pnl = calculate_pnl(trade, settlement_value=0.0)
        assert pnl == pnl_loss(100.0, 0.65)  # -65.00

    def test_down_wins(self):
        trade = make_trade(direction="down", entry_price=0.40, size=100.0)
        pnl = calculate_pnl(trade, settlement_value=0.0)
        assert pnl == pnl_win(100.0, 0.40)  # +60.00

    def test_down_loses(self):
        trade = make_trade(direction="down", entry_price=0.40, size=100.0)
        pnl = calculate_pnl(trade, settlement_value=1.0)
        assert pnl == pnl_loss(100.0, 0.40)  # -40.00

    def test_yes_wins(self):
        trade = make_trade(direction="yes", entry_price=0.70, size=50.0)
        pnl = calculate_pnl(trade, settlement_value=1.0)
        assert pnl == pnl_win(50.0, 0.70)  # +15.00

    def test_no_wins(self):
        trade = make_trade(direction="no", entry_price=0.30, size=50.0)
        pnl = calculate_pnl(trade, settlement_value=0.0)
        assert pnl == pnl_win(50.0, 0.30)  # +35.00

    def test_pnl_rounded_to_two_decimal_places(self):
        trade = make_trade(direction="up", entry_price=1/3, size=100.0)
        pnl = calculate_pnl(trade, settlement_value=1.0)
        assert pnl == pnl_win(100.0, 1/3)  # +66.67

    def test_pnl_at_entry_price_50_percent(self):
        """Edge case: 50c entry price — symmetric win/loss."""
        trade = make_trade(direction="up", entry_price=0.50, size=100.0)
        win_pnl = calculate_pnl(trade, settlement_value=1.0)
        loss_pnl = calculate_pnl(trade, settlement_value=0.0)
        assert win_pnl == pnl_win(100.0, 0.50)    # +50.00
        assert loss_pnl == pnl_loss(100.0, 0.50)   # -50.00


class TestParseMarketResolution:
    """Test market outcome parsing."""

    def test_first_outcome_wins_returns_1(self):
        market = {"closed": True, "outcomePrices": ["0.999", "0.001"], "id": "m1"}
        resolved, value = _parse_market_resolution(market)
        assert resolved is True
        assert value == 1.0

    def test_second_outcome_wins_returns_0(self):
        market = {"closed": True, "outcomePrices": ["0.001", "0.999"], "id": "m1"}
        resolved, value = _parse_market_resolution(market)
        assert resolved is True
        assert value == 0.0

    def test_not_closed_returns_unresolved(self):
        market = {"closed": False, "outcomePrices": ["0.55", "0.45"], "id": "m1"}
        resolved, value = _parse_market_resolution(market)
        assert resolved is False
        assert value is None

    def test_mid_price_not_resolved(self):
        """Market still trading — prices not near 0 or 1."""
        market = {"closed": True, "outcomePrices": ["0.55", "0.45"], "id": "m1"}
        resolved, value = _parse_market_resolution(market)
        assert resolved is False
        assert value is None

    def test_json_string_prices(self):
        """outcomePrices as JSON string (as Polymarket sometimes returns)."""
        market = {"closed": True, "outcomePrices": '["0.999", "0.001"]', "id": "m1"}
        resolved, value = _parse_market_resolution(market)
        assert resolved is True
        assert value == 1.0

    def test_empty_outcome_prices(self):
        market = {"closed": True, "outcomePrices": [], "id": "m1"}
        resolved, value = _parse_market_resolution(market)
        assert resolved is False
        assert value is None


class TestCheckMarketSettlement:
    """Test check_market_settlement integration."""

    @pytest.mark.asyncio
    async def test_settled_trade_returns_pnl(self):
        trade = make_trade(direction="up", entry_price=0.60, size=100.0)

        with patch("backend.core.settlement.settlement_helpers.fetch_polymarket_resolution", new_callable=AsyncMock) as mock_fetch:
            mock_fetch.return_value = (True, 1.0)
            is_settled, settlement_value, pnl = await check_market_settlement(trade)

        assert is_settled is True
        assert settlement_value == 1.0
        assert pnl == pnl_win(100.0, 0.60)  # +66.67

    @pytest.mark.asyncio
    async def test_unresolved_market_returns_none(self):
        trade = make_trade(direction="up", entry_price=0.60, size=100.0)

        with patch("backend.core.settlement.settlement_helpers.fetch_polymarket_resolution", new_callable=AsyncMock) as mock_fetch:
            mock_fetch.return_value = (False, None)
            is_settled, settlement_value, pnl = await check_market_settlement(trade)

        assert is_settled is False
        assert settlement_value is None
        assert pnl is None
