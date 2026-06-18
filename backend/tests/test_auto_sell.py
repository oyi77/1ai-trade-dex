"""Tests for backend.core.auto_sell — pre-settlement profit-taking."""

import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

from backend.core.auto_sell import (
    AutoSellManager,
    AutoSellResult,
    _get_auto_sell_config,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_trade(
    trade_id: int = 1,
    ticker: str = "test-market",
    direction: str = "yes",
    entry_price: float = 0.50,
    size: float = 20.0,
    token_id: str = "tok123",
    settled: bool = False,
    timestamp: datetime | None = None,
) -> MagicMock:
    """Build a mock Trade object."""
    trade = MagicMock()
    trade.id = trade_id
    trade.market_ticker = ticker
    trade.direction = direction
    trade.entry_price = entry_price
    trade.size = size
    trade.token_id = token_id
    trade.settled = settled
    trade.timestamp = timestamp or datetime.now(timezone.utc) - timedelta(seconds=10)
    return trade


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


def test_get_auto_sell_config_defaults():
    cfg = _get_auto_sell_config()
    assert cfg["profit_target_pct"] == 0.06
    assert cfg["stop_loss_pct"] == 0.04
    assert cfg["max_hold_seconds"] == 600


# ---------------------------------------------------------------------------
# Profit target
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_profit_target_triggers_sell():
    """YES position with price up 1% should trigger TAKE_PROFIT (target=0.8%)."""
    manager = AutoSellManager(
        profit_target_pct=0.008, stop_loss_pct=0.008, max_hold_seconds=300
    )
    trade = _make_trade(entry_price=0.50, direction="yes")
    # 0.50 -> 0.515 = +3% gross PnL > 0.8% target + 2% round-trip fee
    result = await manager.check_and_sell(trade, current_price=0.515)
    assert result is not None
    assert result.triggered is True
    assert result.trigger_reason == "TAKE_PROFIT"
    assert result.pnl_pct > 0.008


@pytest.mark.asyncio
async def test_no_sell_within_bounds():
    """Price within +/- 0.8% should NOT trigger any sell."""
    manager = AutoSellManager(
        profit_target_pct=0.008, stop_loss_pct=0.008, max_hold_seconds=9999
    )
    trade = _make_trade(entry_price=0.50, direction="yes")
    # 0.50 -> 0.51 = +2% gross - 2% fee = 0% net PnL (within bounds)
    result = await manager.check_and_sell(trade, current_price=0.51)
    assert result is None


# ---------------------------------------------------------------------------
# Stop loss
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_stop_loss_triggers_sell():
    """YES position with price down 1% should trigger STOP_LOSS."""
    manager = AutoSellManager(
        profit_target_pct=0.008, stop_loss_pct=0.008, max_hold_seconds=300
    )
    trade = _make_trade(entry_price=0.50, direction="yes")
    # 0.50 -> 0.495 = -1% PnL < -0.8% stop
    result = await manager.check_and_sell(trade, current_price=0.495)
    assert result is not None
    assert result.triggered is True
    assert result.trigger_reason == "STOP_LOSS"
    assert result.pnl_pct < -0.008


# ---------------------------------------------------------------------------
# Time exit
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_time_exit_triggers_sell():
    """Position held longer than max_hold should trigger TIME_EXIT."""
    manager = AutoSellManager(
        profit_target_pct=0.50, stop_loss_pct=0.50, max_hold_seconds=60
    )
    old_ts = datetime.now(timezone.utc) - timedelta(seconds=120)
    trade = _make_trade(entry_price=0.50, direction="yes", timestamp=old_ts)
    # Price unchanged (0.50 -> 0.50) so no profit/loss trigger, but 120s > 60s max_hold
    result = await manager.check_and_sell(trade, current_price=0.50)
    assert result is not None
    assert result.triggered is True
    assert result.trigger_reason == "TIME_EXIT"


# ---------------------------------------------------------------------------
# Direction handling (NO positions)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_no_direction_profit():
    """NO position: entry=0.50, current=0.52 means NO side gained (NO price rose from 0.50 to 0.52)."""
    manager = AutoSellManager(
        profit_target_pct=0.008, stop_loss_pct=0.008, max_hold_seconds=300
    )
    trade = _make_trade(entry_price=0.50, direction="no")
    # For NO: pnl = (current - entry) / entry = (0.52 - 0.50) / 0.50 = 0.04 = 4%
    # 4% gross - 2% fee = 2% net > 0.8% profit target
    result = await manager.check_and_sell(trade, current_price=0.52)
    assert result is not None
    assert result.trigger_reason == "TAKE_PROFIT"


@pytest.mark.asyncio
async def test_no_direction_stop_loss():
    """NO position: entry=0.50, current=0.485 means NO side lost (NO price fell from 0.50 to 0.485)."""
    manager = AutoSellManager(
        profit_target_pct=0.008, stop_loss_pct=0.008, max_hold_seconds=300
    )
    trade = _make_trade(entry_price=0.50, direction="no")
    # For NO: pnl = (current - entry) / entry = (0.485 - 0.50) / 0.50 = -0.03 = -3%
    # -3% gross - 2% fee = -5% net < -0.8% stop loss
    result = await manager.check_and_sell(trade, current_price=0.485)
    assert result is not None
    assert result.trigger_reason == "STOP_LOSS"


# ---------------------------------------------------------------------------
# Invalid entry price
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_invalid_entry_price_returns_none():
    """Entry price <= 0 or >= 1 should be skipped."""
    manager = AutoSellManager()
    trade = _make_trade(entry_price=0.0)
    result = await manager.check_and_sell(trade, current_price=0.50)
    assert result is None


# ---------------------------------------------------------------------------
# CLOB order placement
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sell_order_placed_with_clob_client():
    """When clob_client is provided and sell triggers, order is placed."""
    manager = AutoSellManager(
        profit_target_pct=0.008, stop_loss_pct=0.008, max_hold_seconds=300
    )
    trade = _make_trade(entry_price=0.50, direction="yes", token_id="tok_abc")

    clob = AsyncMock()
    mock_clob_client = MagicMock()
    mock_clob_client.get_balance_allowance.return_value = {"balance": 20_000_000}
    clob._clob_client = mock_clob_client
    mock_order_result = MagicMock()
    mock_order_result.order_id = "order-42"
    clob.place_limit_order.return_value = mock_order_result

    # 0.50 -> 0.52 = +4% gross - 2% fee = 2% net > 0.8% profit target
    result = await manager.check_and_sell(trade, current_price=0.52, clob_client=clob)
    assert result is not None
    assert result.triggered is True
    assert result.order_id == "order-42"
    clob.place_limit_order.assert_awaited_once_with(
        token_id="tok_abc",
        side="SELL",
        price=0.52,
        size=20.0,
    )


@pytest.mark.asyncio
async def test_no_order_when_clob_is_none():
    """Without clob_client, sell is signalled but no order placed."""
    manager = AutoSellManager(
        profit_target_pct=0.008, stop_loss_pct=0.008, max_hold_seconds=300
    )
    trade = _make_trade(entry_price=0.50, direction="yes")
    # 0.50 -> 0.52 = +4% gross - 2% fee = 2% net > 0.8% profit target
    result = await manager.check_and_sell(trade, current_price=0.52, clob_client=None)
    assert result is not None
    assert result.triggered is True
    assert result.order_id is None


# ---------------------------------------------------------------------------
# scan_and_sell_all
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_scan_and_sell_all():
    """Bulk scan should evaluate all trades and return only triggered ones."""
    manager = AutoSellManager(
        profit_target_pct=0.008, stop_loss_pct=0.008, max_hold_seconds=300
    )
    t1 = _make_trade(
        trade_id=1, entry_price=0.50, direction="yes"
    )  # will trigger (price up)
    t2 = _make_trade(
        trade_id=2, entry_price=0.50, direction="yes"
    )  # won't trigger (price same)
    prices = {"test-market": 0.52}  # t1: 4% gross - 2% fee = 2% net > 0.8% target

    # Give t2 a different ticker with price that keeps net PnL within bounds
    t2.market_ticker = "other-market"
    prices["other-market"] = 0.51  # t2: 2% gross - 2% fee = 0% net (no trigger)

    results = await manager.scan_and_sell_all([t1, t2], prices)
    assert len(results) == 1
    assert results[0].trade_id == 1


# ---------------------------------------------------------------------------
# AutoSellResult.to_dict
# ---------------------------------------------------------------------------


def test_auto_sell_result_to_dict():
    r = AutoSellResult(
        trade_id=5,
        market_ticker="mkt",
        triggered=True,
        trigger_reason="TAKE_PROFIT",
        entry_price=0.50,
        current_price=0.51,
        pnl_pct=0.02,
    )
    d = r.to_dict()
    assert d["trade_id"] == 5
    assert d["trigger_reason"] == "TAKE_PROFIT"
    assert d["triggered"] is True


@pytest.mark.asyncio
async def test_check_strategy_positions_for_auto_sell_kwargs(monkeypatch):
    """Verify check_strategy_positions_for_auto_sell passes kwargs to AutoSellManager."""
    from unittest.mock import AsyncMock, patch
    from backend.core.auto_sell import check_strategy_positions_for_auto_sell

    mock_trade = _make_trade(trade_id=1, entry_price=0.50, direction="yes")
    mock_db = MagicMock()
    mock_db.query.return_value.filter.return_value.filter.return_value.all.return_value = [
        mock_trade
    ]

    # Mock SessionLocal (imported inside _load from backend.models.database)
    monkeypatch.setattr("backend.models.database.SessionLocal", lambda: mock_db)

    # Mock fetch_prices_bulk
    monkeypatch.setattr(
        "backend.core.position_monitor._fetch_prices_bulk",
        lambda x: {"test-market": 0.505},
    )

    # Mock scan_and_sell_all to check manager configuration
    call_params = {}

    async def mock_scan(self, trades, prices, clob_client=None):
        call_params["profit_target"] = self.profit_target
        call_params["stop_loss"] = self.stop_loss
        call_params["max_hold"] = self.max_hold
        return []

    monkeypatch.setattr(AutoSellManager, "scan_and_sell_all", mock_scan)

    # Invoke with overrides
    await check_strategy_positions_for_auto_sell(
        "test_strat",
        profit_target_pct=0.05,
        stop_loss_pct=0.10,
        max_hold_seconds=600,
    )

    assert call_params["profit_target"] == 0.05
    assert call_params["stop_loss"] == 0.10
    assert call_params["max_hold"] == 600

    # Invoke without overrides to ensure global defaults are used
    await check_strategy_positions_for_auto_sell("test_strat")
    assert call_params["profit_target"] == 0.06
    assert call_params["stop_loss"] == 0.04
    assert call_params["max_hold"] == 600
