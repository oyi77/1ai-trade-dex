"""Tests for settlement P&L calculation and trade processing logic."""

import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch, AsyncMock
from types import SimpleNamespace
from contextlib import asynccontextmanager

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.models.database import Base, Trade, BotState, SettlementEvent
from backend.core.settlement.settlement_helpers import (
    calculate_pnl,
    calculate_exit_pnl,
    process_settled_trade,
    total_loss_settlement_value,
)
from backend.config import settings

# ---------------------------------------------------------------------------
# In-memory SQLite fixture (per-test isolation)
# ---------------------------------------------------------------------------


@pytest.fixture()
def db():
    """Provide a fresh in-memory SQLite session for each test."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


def _make_trade(
    db,
    *,
    direction: str = "up",
    entry_price: float = 0.40,
    size: float = 10.0,
    market_ticker: str = "TEST-MKT-001",
    settled: bool = False,
    event_slug: str = None,
    signal_id: int = None,
    trading_mode: str = "paper",
) -> Trade:
    """Create and persist a Trade record for testing."""
    trade = Trade(
        market_ticker=market_ticker,
        platform="polymarket",
        event_slug=event_slug,
        direction=direction,
        entry_price=entry_price,
        size=size,
        timestamp=datetime.now(timezone.utc),
        settled=settled,
        result="pending",
        pnl=None,
        model_probability=0.55,
        market_price_at_entry=entry_price,
        edge_at_entry=0.10,
        trading_mode=trading_mode,
        signal_id=signal_id,
    )
    db.add(trade)
    db.flush()
    return trade


def _state_for_mode(db, mode: str) -> BotState:
    state = db.query(BotState).filter_by(mode=mode).first()
    if state is None:
        state = BotState(mode=mode)
        db.add(state)
        db.flush()
    return state


# ---------------------------------------------------------------------------
# P&L calculation — calculate_pnl()
# ---------------------------------------------------------------------------


class TestPnlWin:
    def test_up_position_wins_at_settlement_1(self):
        """Bought UP at 0.40, market settled UP (1.0) → profit.
        size is SHARES (25 shares = $10 at $0.40).
        Win PnL = (1.0 - entry_price) * shares = 0.60 * 25 = 15.0.
        """
        trade = MagicMock(spec=Trade)
        trade.direction = "up"
        trade.entry_price = 0.40
        trade.size = 25.0  # shares (=$10 at $0.40)

        pnl = calculate_pnl(trade, settlement_value=1.0)

        # Polymarket fee: 30bps * min(0.40,0.60) * $10 = $0.012.
        # shares = 25; gross payout = 25; pnl = 25 - 10 - 0.012 = 14.988.
        assert pnl == pytest.approx(14.99)
        assert pnl > 0.0

    def test_down_position_wins_at_settlement_0(self):
        """Bought DOWN at 0.40, market settled DOWN (0.0) → profit.
        size is SHARES (25 shares = $10 at $0.40).
        Polymarket fee: 30bps * min(0.40,0.60) * $10 = $0.04; fee reduces PnL.
        """
        trade = MagicMock(spec=Trade)
        trade.direction = "down"
        trade.entry_price = 0.40
        trade.size = 25.0  # shares (=$10 at $0.40)

        pnl = calculate_pnl(trade, settlement_value=0.0)

        assert pnl == pytest.approx(14.99)
        assert pnl > 0.0


class TestPnlLoss:
    def test_up_position_loses_at_settlement_0(self):
        """Bought UP at 0.40, market settled DOWN (0.0) → loss.
        size is SHARES (25 shares = $10 at $0.40).
        New fee: 30bps * min(0.40,0.60) * $10 = $0.04, cost = $10.04. Loss = -cost."""
        trade = MagicMock(spec=Trade)
        trade.direction = "up"
        trade.entry_price = 0.40
        trade.size = 25.0  # shares (=$10 at $0.40)

        pnl = calculate_pnl(trade, settlement_value=0.0)

        # -10.01 (Polymarket fee: 0.003*min(0.40,0.60)*10=0.04)
        assert pnl == pytest.approx(-10.01)
        assert pnl < 0.0

    def test_down_position_loses_at_settlement_1(self):
        """Bought DOWN at 0.40, market settled UP (1.0) → loss.
        size is SHARES (25 shares = $10 at $0.40).
        New fee: 30bps * min(0.40,0.60) * $10 = $0.04, cost = $10.04. Loss = -cost."""
        trade = MagicMock(spec=Trade)
        trade.direction = "down"
        trade.entry_price = 0.40
        trade.size = 25.0  # shares (=$10 at $0.40)

        pnl = calculate_pnl(trade, settlement_value=1.0)

        # -10.01 (Polymarket fee: 0.003*min(0.40,0.60)*10=0.04)
        assert pnl == pytest.approx(-10.01)
        assert pnl < 0.0

    def test_loss_magnitude(self):
        """Loss includes fee. size=20 shares at 0.55 entry = $11 notional. fee=0.003*min(0.55,0.45)*11=0.01485, cost=$11.01485. Loss = -cost."""
        trade = MagicMock(spec=Trade)
        trade.direction = "up"
        trade.entry_price = 0.55
        trade.size = 20.0  # shares (=$11 at $0.55)

        pnl = calculate_pnl(trade, settlement_value=0.0)
        # Loss = -cost = -(shares * entry_price + fee)
        # fee = 0.003 * min(0.55, 0.45) * (20 * 0.55) = 0.003 * 0.45 * 11 = 0.01485
        # cost = 11 + 0.01485 = 11.01485, loss = -11.01485
        assert pnl == pytest.approx(-11.01, abs=0.01)
    def test_loss_magnitude(self):
        """Loss includes fee. size=20 shares at 0.55 entry = $11 notional. fee=0.003*min(0.55,0.45)*11=0.01485, cost=$11.01485. Loss = -cost."""
        trade = MagicMock(spec=Trade)
        trade.direction = "up"
        trade.entry_price = 0.55
        trade.size = 20.0  # shares (=$11 at $0.55)

        pnl = calculate_pnl(trade, settlement_value=0.0)
        # Loss = -cost = -(shares * entry_price + fee)
        # fee = 0.003 * min(0.55, 0.45) * (20 * 0.55) = 0.003 * 0.45 * 11 = 0.01485
        # cost = 11 + 0.01485 = 11.01485, loss = -11.01485
        assert pnl == pytest.approx(-11.01, abs=0.01)
    def test_loss_magnitude(self):
        """Loss includes fee. size=20 shares at 0.55 entry = $11 notional. fee=0.003*min(0.55,0.45)*11=0.01485, cost=$11.01485. Loss = -cost."""
        trade = MagicMock(spec=Trade)
        trade.direction = "up"
        trade.entry_price = 0.55
        trade.size = 20.0  # shares (=$11 at $0.55)

        pnl = calculate_pnl(trade, settlement_value=0.0)
        # Loss = -cost = -(shares * entry_price + fee)
        # fee = 0.003 * min(0.55, 0.45) * (20 * 0.55) = 0.003 * 0.45 * 11 = 0.01485
        # cost = 11 + 0.01485 = 11.01485, loss = -11.01485
        assert pnl == pytest.approx(-11.01, abs=0.01)
    def test_loss_magnitude(self):
        """Loss includes fee. size=20 shares at 0.55 entry = $11 notional. fee=0.003*min(0.55,0.45)*11=0.01485, cost=$11.01485. Loss = -cost."""
        trade = MagicMock(spec=Trade)
        trade.direction = "up"
        trade.entry_price = 0.55
        trade.size = 20.0  # shares (=$11 at $0.55)

        pnl = calculate_pnl(trade, settlement_value=0.0)
        # Loss = -cost = -(shares * entry_price + fee)
        # fee = 0.003 * min(0.55, 0.45) * (20 * 0.55) = 0.003 * 0.45 * 11 = 0.01485
        # cost = 11 + 0.01485 = 11.01485, loss = -11.01485
        assert pnl == pytest.approx(-11.01, abs=0.01)
    def test_loss_magnitude(self):
        """Loss includes fee. size=20 shares at 0.55 entry = $11 notional. fee=0.003*min(0.55,0.45)*11=0.01485, cost=$11.01485. Loss = -cost."""
        trade = MagicMock(spec=Trade)
        trade.direction = "up"
        trade.entry_price = 0.55
        trade.size = 20.0  # shares (=$11 at $0.55)

        pnl = calculate_pnl(trade, settlement_value=0.0)
        # Loss = -cost = -(shares * entry_price + fee)
        # fee = 0.003 * min(0.55, 0.45) * (20 * 0.55) = 0.003 * 0.45 * 11 = 0.01485
        # cost = 11 + 0.01485 = 11.01485, loss = -11.01485
        assert pnl == pytest.approx(-11.01, abs=0.01)
    def test_loss_magnitude(self):
        """Loss includes fee. size=20 shares at 0.55 entry = $11 notional. fee=0.003*min(0.55,0.45)*11=0.01485, cost=$11.01485. Loss = -cost."""
        trade = MagicMock(spec=Trade)
        trade.direction = "up"
        trade.entry_price = 0.55
        trade.size = 20.0  # shares (=$11 at $0.55)

        pnl = calculate_pnl(trade, settlement_value=0.0)
        # Loss = -cost = -(shares * entry_price + fee)
        # fee = 0.003 * min(0.55, 0.45) * (20 * 0.55) = 0.003 * 0.45 * 11 = 0.01485
        # cost = 11 + 0.01485 = 11.01485, loss = -11.01485
        assert pnl == pytest.approx(-11.01, abs=0.01)
    def test_loss_magnitude(self):
        """Loss includes fee. size=20 shares at 0.55 entry = $11 notional. fee=0.003*min(0.55,0.45)*11=0.01485, cost=$11.01485. Loss = -cost."""
        trade = MagicMock(spec=Trade)
        trade.direction = "up"
        trade.entry_price = 0.55
        trade.size = 20.0  # shares (=$11 at $0.55)

        pnl = calculate_pnl(trade, settlement_value=0.0)
        # Loss = -cost = -(shares * entry_price + fee)
        # fee = 0.003 * min(0.55, 0.45) * (20 * 0.55) = 0.003 * 0.45 * 11 = 0.01485
        # cost = 11 + 0.01485 = 11.01485, loss = -11.01485
        assert pnl == pytest.approx(-11.01, abs=0.01)
    def test_loss_magnitude(self):
        """Loss includes fee. size=20 shares at 0.55 entry = $11 notional. fee=0.003*min(0.55,0.45)*11=0.01485, cost=$11.01485. Loss = -cost."""
        trade = MagicMock(spec=Trade)
        trade.direction = "up"
        trade.entry_price = 0.55
        trade.size = 20.0  # shares (=$11 at $0.55)

        pnl = calculate_pnl(trade, settlement_value=0.0)
        # Loss = -cost = -(shares * entry_price + fee)
        # fee = 0.003 * min(0.55, 0.45) * (20 * 0.55) = 0.003 * 0.45 * 11 = 0.01485
        # cost = 11 + 0.01485 = 11.01485, loss = -11.01485
        assert pnl == pytest.approx(-11.01, abs=0.01)
    def test_loss_magnitude(self):
        """Loss includes fee. size=20 shares at 0.55 entry = $11 notional. fee=0.003*min(0.55,0.45)*11=0.01485, cost=$11.01485. Loss = -cost."""
        trade = MagicMock(spec=Trade)
        trade.direction = "up"
        trade.entry_price = 0.55
        trade.size = 20.0  # shares (=$11 at $0.55)

        pnl = calculate_pnl(trade, settlement_value=0.0)
        # Loss = -cost = -(shares * entry_price + fee)
        # fee = 0.003 * min(0.55, 0.45) * (20 * 0.55) = 0.003 * 0.45 * 11 = 0.01485
        # cost = 11 + 0.01485 = 11.01485, loss = -11.01485
        assert pnl == pytest.approx(-11.01, abs=0.01)
    def test_loss_magnitude(self):
        """Loss includes fee. size=20 shares at 0.55 entry = $11 notional. fee=0.003*min(0.55,0.45)*11=0.01485, cost=$11.01485. Loss = -cost."""
        trade = MagicMock(spec=Trade)
        trade.direction = "up"
        trade.entry_price = 0.55
        trade.size = 20.0  # shares (=$11 at $0.55)

        pnl = calculate_pnl(trade, settlement_value=0.0)
        # Loss = -cost = -(shares * entry_price + fee)
        # fee = 0.003 * min(0.55, 0.45) * (20 * 0.55) = 0.003 * 0.45 * 11 = 0.01485
        # cost = 11 + 0.01485 = 11.01485, loss = -11.01485
        assert pnl == pytest.approx(-11.01, abs=0.01)
    def test_loss_magnitude(self):
        """Loss includes fee. size=20 shares at 0.55 entry = $11 notional. fee=0.003*min(0.55,0.45)*11=0.01485, cost=$11.01485. Loss = -cost."""
        trade = MagicMock(spec=Trade)
        trade.direction = "up"
        trade.entry_price = 0.55
        trade.size = 20.0  # shares (=$11 at $0.55)

        pnl = calculate_pnl(trade, settlement_value=0.0)
        # Loss = -cost = -(shares * entry_price + fee)
        # fee = 0.003 * min(0.55, 0.45) * (20 * 0.55) = 0.003 * 0.45 * 11 = 0.01485
        # cost = 11 + 0.01485 = 11.01485, loss = -11.01485
        assert pnl == pytest.approx(-11.01, abs=0.01)


class TestForceClosedUnresolvedPnl:
    """force_closed_unresolved trades must record pnl consistent with
    result="loss". scheduler.py previously hardcoded pnl=0.0 for these
    trades, which combined with result="loss" made real losses invisible in
    PnL totals while still counting against win rate (2830 unified_arb
    trades, ~$14k hidden loss). See
    docs/architecture/adr-016-force-closed-unresolved-pnl.md.
    """

    def test_yes_direction_loss_settlement_value_is_zero(self):
        assert total_loss_settlement_value("yes") == 0.0
        assert total_loss_settlement_value("YES") == 0.0
        assert total_loss_settlement_value("up") == 0.0
        assert total_loss_settlement_value(None) == 0.0

    def test_no_direction_loss_settlement_value_is_one(self):
        assert total_loss_settlement_value("no") == 1.0
        assert total_loss_settlement_value("NO") == 1.0
        assert total_loss_settlement_value("down") == 1.0

    def test_yes_position_force_closed_as_loss_is_negative(self):
        """unified_arb-style trade: YES @ 0.4944, size=10 -> pnl ~ -4.94, not 0."""
        trade = MagicMock(spec=Trade)
        trade.direction = "YES"
        trade.entry_price = 0.4944
        trade.size = 10.0

        sv = total_loss_settlement_value(trade.direction)
        pnl = calculate_pnl(trade, sv)

        assert pnl < 0.0
        assert pnl == pytest.approx(-4.944, abs=0.1)

    def test_no_position_force_closed_as_loss_is_negative(self):
        """bond_scanner-style trade: NO @ 0.0658, size=5 -> pnl ~ -0.33, not 0."""
        trade = MagicMock(spec=Trade)
        trade.direction = "no"
        trade.entry_price = 0.0658
        trade.size = 5.0

        sv = total_loss_settlement_value(trade.direction)
        pnl = calculate_pnl(trade, sv)

        assert pnl < 0.0
        assert pnl == pytest.approx(-0.329, abs=0.1)


class TestUnresolvedLossConsistency:
    """`closed_unresolved`/`expired_unresolved`/`stale_expired`/
    `btc_5min_unresolved` force-settle a trade as result="loss" when no real
    market resolution is available. Before total_loss_settlement_value() was
    wired into these branches, they called calculate_pnl(trade, 0.0) — for a
    'no'/'down' position this is the WIN formula (positive pnl), producing
    e.g. trade #25753 (NO @ 0.23, size=5, pnl=+3.85, result="loss"). See
    docs/architecture/adr-016-force-closed-unresolved-pnl.md.
    """

    @pytest.mark.asyncio
    async def test_expired_unresolved_no_position_settles_as_negative_loss(self, db):
        from backend.core.settlement.settlement import settle_pending_trades

        trade = _make_trade(
            db,
            market_ticker="will-some-event-happen-by-2026",
            direction="no",
            entry_price=0.23,
            size=5.0,
        )
        trade.market_end_date = datetime.now(timezone.utc) - timedelta(hours=100)
        db.commit()

        with patch(
            "backend.core.settlement.settlement._resolve_markets",
            AsyncMock(return_value={}),
        ):
            results = await settle_pending_trades(db)

        assert len(results) == 1
        settled = results[0]
        assert settled.result == "loss"
        assert settled.settlement_source == "expired_unresolved"
        assert settled.settlement_value == 1.0  # total_loss_settlement_value("no")
        assert settled.pnl < 0.0

    @pytest.mark.asyncio
    async def test_btc_5min_unresolved_down_position_settles_as_negative_loss(self, db):
        from backend.core.settlement.settlement import _settle_btc_5min_trade

        now = datetime.now(timezone.utc)
        window_start_ts = int((now - timedelta(hours=25)).timestamp())
        trade = _make_trade(
            db,
            market_ticker=f"btc-updown-5m-{window_start_ts}",
            direction="down",
            entry_price=0.30,
            size=10.0,
        )
        trade.timestamp = now - timedelta(hours=25)
        db.commit()

        with (
            patch(
                "backend.data.btc_markets.fetch_btc_market_for_settlement",
                AsyncMock(return_value=None),
            ),
            patch(
                "backend.data.crypto.fetch_binance_klines",
                AsyncMock(return_value=[]),
            ),
        ):
            result = await _settle_btc_5min_trade(trade, now)

        assert result is not None
        assert result.result == "loss"
        assert result.settlement_source == "btc_5min_unresolved"
        assert result.settlement_value == 1.0  # total_loss_settlement_value("down")
        assert result.pnl < 0.0


class TestPnlPush:
    def test_push_is_zero_at_entry_price_win(self):
        """When entry_price=1.0 (degenerate), pnl = 0 on win."""
        trade = MagicMock(spec=Trade)
        trade.direction = "up"
        trade.entry_price = 1.0
        trade.size = 10.0

        pnl = calculate_pnl(trade, settlement_value=1.0)
        # pnl = size * (1.0 - 1.0) = 0
        assert pnl == pytest.approx(0.0)

    def test_approximate_push_when_entry_near_settlement(self):
        """Entry price of 0.50, size 0 → pnl is always 0."""
        trade = MagicMock(spec=Trade)
        trade.direction = "up"
        trade.entry_price = 0.50
        trade.size = 0.0  # zero size = push semantics

        pnl_win = calculate_pnl(trade, settlement_value=1.0)
        pnl_loss = calculate_pnl(trade, settlement_value=0.0)
        assert pnl_win == pytest.approx(0.0)
        assert pnl_loss == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# Direction aliases (up/down ↔ yes/no)
# ---------------------------------------------------------------------------


class TestDirectionAliases:
    def test_yes_direction_treated_as_up(self):
        """Direction 'yes' behaves identically to 'up'."""
        trade_up = MagicMock(spec=Trade)
        trade_up.direction = "up"
        trade_up.entry_price = 0.40
        trade_up.size = 10.0

        trade_yes = MagicMock(spec=Trade)
        trade_yes.direction = "yes"
        trade_yes.entry_price = 0.40
        trade_yes.size = 10.0

        for sv in [0.0, 1.0]:
            assert calculate_pnl(trade_up, sv) == pytest.approx(
                calculate_pnl(trade_yes, sv)
            )

    def test_no_direction_treated_as_down(self):
        """Direction 'no' behaves identically to 'down'."""
        trade_down = MagicMock(spec=Trade)
        trade_down.direction = "down"
        trade_down.entry_price = 0.40
        trade_down.size = 10.0

        trade_no = MagicMock(spec=Trade)
        trade_no.direction = "no"
        trade_no.entry_price = 0.40
        trade_no.size = 10.0

        for sv in [0.0, 1.0]:
            assert calculate_pnl(trade_down, sv) == pytest.approx(
                calculate_pnl(trade_no, sv)
            )


# ---------------------------------------------------------------------------
# Bankroll update via settle_pending_trades / update_bot_state_with_settlements
# ---------------------------------------------------------------------------


class TestBankrollUpdate:
    @pytest.mark.asyncio
    async def test_bankroll_increases_on_win(self, db):
        """After settling a winning trade, paper_bankroll should increase."""
        from backend.core.settlement.settlement import update_bot_state_with_settlements

        state = _state_for_mode(db, "paper")
        state.bankroll = settings.INITIAL_BANKROLL
        state.paper_bankroll = (
            settings.INITIAL_BANKROLL - 10.0
        )  # stake deducted at open
        state.paper_pnl = 0.0
        state.paper_trades = 0
        state.paper_wins = 0
        state.total_trades = 0
        state.winning_trades = 0
        state.total_pnl = 0.0
        state.is_running = True
        db.flush()

        trade = _make_trade(db, direction="up", entry_price=0.40, size=10.0)
        trade.settled = True
        trade.result = "win"
        trade.pnl = 6.0  # (1.0 - 0.40) * 10.0 = 6.0
        trade.trading_mode = "paper"
        db.flush()

        await update_bot_state_with_settlements(db, [trade])

        db.refresh(state)
        # bankroll = (100 - 10) + 10 + 6 = 106
        assert state.paper_bankroll > settings.INITIAL_BANKROLL
        assert state.paper_pnl > 0.0

    @pytest.mark.asyncio
    async def test_bankroll_decreases_on_loss(self, db):
        """After settling a losing trade, paper_bankroll should decrease."""
        from backend.core.settlement.settlement import update_bot_state_with_settlements

        state = _state_for_mode(db, "paper")
        state.bankroll = settings.INITIAL_BANKROLL
        state.paper_bankroll = (
            settings.INITIAL_BANKROLL - 10.0
        )  # stake deducted at open
        state.paper_pnl = 0.0
        state.paper_trades = 0
        state.paper_wins = 0
        state.total_trades = 0
        state.winning_trades = 0
        state.total_pnl = 0.0
        state.is_running = True
        db.flush()

        trade = _make_trade(db, direction="up", entry_price=0.40, size=10.0)
        trade.settled = True
        trade.result = "loss"
        trade.pnl = -(0.40 * 10.0)  # -4.0: entry_price * size
        trade.trading_mode = "paper"
        db.flush()

        await update_bot_state_with_settlements(db, [trade])

        db.refresh(state)
        # bankroll = (100 - 10) + 10 + (-4) = 96
        assert state.paper_bankroll < settings.INITIAL_BANKROLL
        assert state.paper_pnl < 0.0

    @pytest.mark.asyncio
    async def test_simulated_bankroll_never_goes_negative_after_large_loss(self, db):
        """Available simulated balance is floored even when cumulative PnL is negative."""
        from backend.core.settlement.settlement import update_bot_state_with_settlements

        state = _state_for_mode(db, "paper")
        state.bankroll = 2.0
        state.paper_bankroll = 2.0
        state.paper_pnl = -98.0
        state.paper_trades = 0
        state.paper_wins = 0
        state.is_running = True
        db.flush()

        trade = _make_trade(db, direction="up", entry_price=0.40, size=10.0)
        trade.settled = True
        trade.result = "loss"
        trade.pnl = -25.0
        trade.trading_mode = "paper"
        db.flush()

        await update_bot_state_with_settlements(db, [trade])

        db.refresh(state)
        assert state.paper_bankroll == pytest.approx(0.0)
        assert state.paper_pnl == pytest.approx(-123.0)

    @pytest.mark.asyncio
    async def test_live_settlement_preserves_wallet_synced_cash_and_reconciles_pnl(
        self, db, monkeypatch
    ):
        from backend.core.settlement.settlement import update_bot_state_with_settlements

        state = _state_for_mode(db, "live")
        db.info["allow_live_financial_update"] = True
        state.bankroll = 160.73
        state.total_pnl = 0.0
        state.live_initial_bankroll = 200.73
        state.total_trades = 0
        state.winning_trades = 0
        state.is_running = True
        db.flush()
        del db.info["allow_live_financial_update"]

        trade = _make_trade(
            db, direction="up", entry_price=0.40, size=40.0, trading_mode="live"
        )
        trade.settled = True
        trade.result = "loss"
        trade.pnl = -40.0
        db.flush()

        async def fake_clob_pusd_balance():
            return 160.73

        monkeypatch.setattr(
            "backend.core.wallet.bankroll_reconciliation._fetch_clob_pusd_balance",
            fake_clob_pusd_balance,
        )

        await update_bot_state_with_settlements(db, [trade])

        db.refresh(state)
        assert state.bankroll == pytest.approx(160.73)
        assert state.total_pnl == pytest.approx(-40.0)
        assert state.total_trades == 1
        assert state.winning_trades == 0


# ---------------------------------------------------------------------------
# process_settled_trade — sets trade fields and creates SettlementEvent
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestProcessSettledTrade:
    async def test_marks_trade_as_settled(self, db):
        trade = _make_trade(db)
        pnl = 6.0
        result = await process_settled_trade(trade, True, 1.0, pnl, db)
        assert result is True
        assert trade.settled is True
        assert trade.settlement_value == pytest.approx(1.0)
        assert trade.pnl == pytest.approx(pnl)
        assert trade.result == "win"

    async def test_marks_trade_as_loss(self, db):
        trade = _make_trade(db)
        pnl = -4.0
        result = await process_settled_trade(trade, True, 0.0, pnl, db)
        assert result is True
        assert trade.result == "loss"
        assert trade.pnl == pytest.approx(pnl)

    async def test_marks_trade_as_push(self, db):
        trade = _make_trade(db)
        result = await process_settled_trade(trade, True, 1.0, 0.0, db)
        assert result is True
        assert trade.result == "push"

    async def test_returns_false_when_not_settled(self, db):
        trade = _make_trade(db)
        result = await process_settled_trade(trade, False, None, None, db)
        assert result is False

    async def test_creates_settlement_event(self, db):
        trade = _make_trade(db)
        await process_settled_trade(trade, True, 1.0, 6.0, db)
        db.flush()
        events = (
            db.query(SettlementEvent)
            .filter(SettlementEvent.market_ticker == trade.market_ticker)
            .all()
        )
        assert len(events) == 1
        assert events[0].resolved_outcome == "up"
        assert events[0].pnl == pytest.approx(6.0)

    async def test_settlement_timestamp_set(self, db):
        trade = _make_trade(db)
        before = datetime.now(timezone.utc)
        await process_settled_trade(trade, True, 1.0, 6.0, db)
        assert trade.settlement_time is not None
        assert trade.settlement_time.replace(tzinfo=timezone.utc) >= before

    async def test_online_learner_failure_rolls_back_and_does_not_abort_settlement(
        self, db
    ):
        trade = _make_trade(db)
        trade_id = trade.id

        with patch(
            "backend.core.online_learner.OnlineLearner.on_trade_settled",
            side_effect=RuntimeError("boom {pk_1}"),
        ):
            result = await process_settled_trade(trade, True, 1.0, 6.0, db)

        assert result is True
        assert trade.settled is True
        assert trade.result == "win"
        db.commit()
        db.flush()
        events = (
            db.query(SettlementEvent).filter(SettlementEvent.trade_id == trade_id).all()
        )
        assert len(events) == 1


# ---------------------------------------------------------------------------
# Deduplication — same market_ticker not settled twice
# ---------------------------------------------------------------------------


class TestDeduplication:
    @pytest.mark.asyncio
    async def test_already_settled_trade_skipped(self, db):
        """Trades with settled=True are excluded from settle_pending_trades."""
        from backend.core.settlement.settlement import settle_pending_trades

        # Create one already-settled trade
        _make_trade(db, market_ticker="SETTLED-MKT", settled=True)
        db.commit()

        # No unresolved trades → settlement should return empty list
        with patch(
            "backend.core.settlement.settlement._resolve_markets",
            AsyncMock(return_value={}),
        ):
            results = await settle_pending_trades(db)

        assert results == []

    @pytest.mark.asyncio
    async def test_same_ticker_resolved_once(self):
        """Each unique market_ticker triggers only one API call (deduplication)."""
        engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(bind=engine)
        Session = sessionmaker(bind=engine)
        session = Session()

        try:
            # Two trades for same market
            for _ in range(2):
                t = Trade(
                    market_ticker="DEDUP-MKT",
                    platform="polymarket",
                    direction="up",
                    entry_price=0.45,
                    size=10.0,
                    settled=False,
                    result="pending",
                    model_probability=0.55,
                    market_price_at_entry=0.45,
                    edge_at_entry=0.10,
                    trading_mode="paper",
                )
                session.add(t)
            session.commit()

            resolve_calls = []

            async def mock_resolve(normal, weather, slugs, platforms):
                resolve_calls.append((set(normal), set(weather)))
                return {"DEDUP-MKT": (False, None)}

            with patch(
                "backend.core.settlement.settlement._resolve_markets",
                side_effect=mock_resolve,
            ):
                from backend.core.settlement.settlement import settle_pending_trades

                await settle_pending_trades(session)

            # _resolve_markets called once, with exactly one unique ticker
            assert len(resolve_calls) == 1
            all_tickers = resolve_calls[0][0] | resolve_calls[0][1]
            assert all_tickers == {"DEDUP-MKT"}
        finally:
            session.close()


@pytest.mark.asyncio
async def test_reconcile_positions_targets_live_open_trades(db):
    from backend.core.settlement.settlement_helpers import reconcile_positions

    live_trade = _make_trade(db, market_ticker="LIVE-MKT", trading_mode="live")
    _make_trade(db, market_ticker="PAPER-MKT", trading_mode="paper")
    db.commit()

    @asynccontextmanager
    async def fake_clob_factory(*args, **kwargs):
        yield SimpleNamespace(get_trader_positions=AsyncMock(return_value=[]))

    with (
        patch(
            "backend.data.polymarket_clob.clob_from_settings",
            side_effect=fake_clob_factory,
        ),
        patch.object(settings, "TRADING_MODE", "live"),
        patch.object(settings, "POLYMARKET_BUILDER_ADDRESS", "0xFAKE_TEST_WALLET"),
    ):
        trades_to_close = await reconcile_positions(db)

    assert live_trade.id in trades_to_close


@pytest.mark.asyncio
async def test_reconcile_positions_does_not_skip_paper(db):
    from backend.core.settlement.settlement_helpers import reconcile_positions

    _make_trade(db, market_ticker="PAPER-MANUAL", trading_mode="paper", settled=False)
    db.commit()

    @asynccontextmanager
    async def fake_clob_factory(*args, **kwargs):
        yield SimpleNamespace(get_trader_positions=AsyncMock(return_value=[]))

    with (
        patch(
            "backend.data.polymarket_clob.clob_from_settings",
            side_effect=fake_clob_factory,
        ),
        patch.object(settings, "TRADING_MODE", "paper"),
        patch.object(settings, "POLYMARKET_BUILDER_ADDRESS", "0xFAKE_TEST_WALLET"),
    ):
        trades_to_close = await reconcile_positions(db)

    assert len(trades_to_close) >= 1


# ---------------------------------------------------------------------------
# resolve_paper_trades — Gamma-outcome resolution updates BotState counters
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_resolve_paper_trades_updates_botstate_counters(db):
    """A paper trade resolved via Gamma outcome prices should update
    BotState.paper_pnl/paper_trades/paper_wins (regression for the
    placeholder `type("BotState", (object,), {})` query that always failed).
    """
    from backend.core.settlement.settlement_helpers import resolve_paper_trades

    state = _state_for_mode(db, "paper")
    state.paper_pnl = 0.0
    state.paper_trades = 0
    state.paper_wins = 0
    db.flush()

    trade = _make_trade(
        db, direction="yes", entry_price=0.40, size=10.0,
        market_ticker="WILL-X-HAPPEN",
    )
    trade.settled = True
    trade.pnl = None
    trade.result = "pending"
    trade.timestamp = datetime.now(timezone.utc) - timedelta(hours=2)
    db.flush()

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json = MagicMock(
        return_value=[{"outcomePrices": ["1.0", "0.0"], "conditionId": "0xabc"}]
    )
    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_response)

    with patch(
        "backend.core.settlement.settlement_helpers.get_shared_client",
        return_value=mock_client,
    ):
        settled = await resolve_paper_trades(db)

    assert len(settled) == 1
    db.refresh(trade)
    assert trade.result == "win"
    assert trade.pnl is not None

    db.refresh(state)
    assert state.paper_trades == 1
    assert state.paper_wins == 1
    assert state.paper_pnl == pytest.approx(trade.pnl)


# ---------------------------------------------------------------------------
# Early-exit P&L calculation — calculate_exit_pnl() (ADR-017)
# ---------------------------------------------------------------------------


class TestCalculateExitPnl:
    def test_profit_exit(self):
        """10 shares bought at 0.50, exited at 0.58.
        entry_fee = 30bps*min(0.50,0.50)*(10*0.50) = 0.0075
        exit_fee  = 30bps*min(0.58,0.42)*(10*0.58) = 0.007308
        pnl = 10*(0.58-0.50) - 0.0075 - 0.007308 = 0.785192 -> 0.79
        """
        trade = MagicMock(spec=Trade)
        trade.direction = "yes"
        trade.entry_price = 0.50
        trade.size = 10.0

        pnl, fee = calculate_exit_pnl(trade, exit_price=0.58)

        assert pnl == pytest.approx(0.79)
        assert fee == pytest.approx(0.01)

    def test_loss_exit(self):
        """10 shares bought at 0.50, exited at 0.42 (stop loss).
        entry_fee = 30bps*min(0.50,0.50)*(10*0.50) = 0.0075
        exit_fee  = 30bps*min(0.42,0.58)*(10*0.42) = 0.005292
        pnl = 10*(0.42-0.50) - 0.0075 - 0.005292 = -0.812792 -> -0.81
        """
        trade = MagicMock(spec=Trade)
        trade.direction = "yes"
        trade.entry_price = 0.50
        trade.size = 10.0

        pnl, fee = calculate_exit_pnl(trade, exit_price=0.42)

        assert pnl == pytest.approx(-0.81)
        assert fee == pytest.approx(0.01)

    def test_direction_independent(self):
        """exit_price is in held-token terms (same convention as entry_price),
        so a 'no' position with the same entry/exit prices produces the same
        pnl as a 'yes' position — calculate_exit_pnl must not branch on
        direction."""
        trade_yes = MagicMock(spec=Trade)
        trade_yes.direction = "yes"
        trade_yes.entry_price = 0.50
        trade_yes.size = 10.0

        trade_no = MagicMock(spec=Trade)
        trade_no.direction = "no"
        trade_no.entry_price = 0.50
        trade_no.size = 10.0

        pnl_yes, _ = calculate_exit_pnl(trade_yes, exit_price=0.58)
        pnl_no, _ = calculate_exit_pnl(trade_no, exit_price=0.58)

        assert pnl_yes == pytest.approx(pnl_no)

    def test_uses_fill_price_and_filled_size(self):
        """When fill_price/filled_size are set, they take precedence over
        entry_price/size (mirrors calculate_pnl).
        8 shares filled at 0.45, exited at 0.50.
        entry_fee = 30bps*min(0.45,0.55)*(8*0.45) = 0.00486
        exit_fee  = 30bps*min(0.50,0.50)*(8*0.50) = 0.006
        pnl = 8*(0.50-0.45) - 0.00486 - 0.006 = 0.38914 -> 0.39
        """
        trade = MagicMock(spec=Trade)
        trade.direction = "yes"
        trade.entry_price = 0.40  # ignored — fill_price takes precedence
        trade.size = 10.0  # ignored — filled_size takes precedence
        trade.fill_price = 0.45
        trade.filled_size = 8.0
        trade.fee = None

        pnl, fee = calculate_exit_pnl(trade, exit_price=0.50)

        assert pnl == pytest.approx(0.39)
        assert fee == pytest.approx(0.01)

    def test_uses_stored_entry_fee(self):
        """When trade.fee is already set (recorded at entry), it is used as
        the entry-side fee instead of recomputing it.
        pnl = 10*(0.58-0.50) - 0.05 - exit_fee(0.007308) = 0.742692 -> 0.74
        """
        trade = MagicMock(spec=Trade)
        trade.direction = "yes"
        trade.entry_price = 0.50
        trade.size = 10.0
        trade.fee = 0.05
        trade.fill_price = None
        trade.filled_size = None

        pnl, fee = calculate_exit_pnl(trade, exit_price=0.58)

        assert pnl == pytest.approx(0.74)
        assert fee == pytest.approx(0.06)
