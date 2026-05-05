from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.core.bankroll_reconciliation import reconcile_bot_state
from backend.models.database import Base, BotState, Trade


@pytest.fixture()
def db_session():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    Session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    db = Session()
    try:
        yield db
    finally:
        db.close()


@pytest.mark.asyncio
async def test_reconciles_paper_mode_specific_bankroll_without_touching_trades(db_session):
    state = BotState(mode="paper", bankroll=-999.0, paper_bankroll=29.74, paper_pnl=0.0)
    win = Trade(
        market_ticker="paper-win",
        direction="up",
        entry_price=0.5,
        size=10.0,
        settled=True,
        result="win",
        pnl=10.0,
        trading_mode="paper",
        settlement_time=datetime.now(timezone.utc),
    )
    loss = Trade(
        market_ticker="paper-loss",
        direction="down",
        entry_price=0.5,
        size=5.0,
        settled=True,
        result="loss",
        pnl=-5.0,
        trading_mode="paper",
        settlement_time=datetime.now(timezone.utc),
    )
    open_trade = Trade(
        market_ticker="paper-open",
        direction="up",
        entry_price=0.5,
        size=12.0,
        settled=False,
        result="pending",
        pnl=None,
        trading_mode="paper",
    )
    db_session.add_all([state, win, loss, open_trade])
    db_session.commit()

    reports = await reconcile_bot_state(db_session, modes=("paper",), apply=True, commit=True, source="test")

    db_session.refresh(state)
    assert reports[0].new_bankroll == pytest.approx(93.0)
    assert state.paper_bankroll == pytest.approx(93.0)
    assert state.bankroll == pytest.approx(93.0)
    assert state.paper_pnl == pytest.approx(5.0)
    assert state.paper_trades == 2
    assert state.paper_wins == 1
    assert db_session.query(Trade).count() == 3


@pytest.mark.asyncio
async def test_dry_run_does_not_mutate_testnet_state(db_session):
    state = BotState(mode="testnet", bankroll=-74.49, testnet_bankroll=-74.49, testnet_pnl=0.0)
    db_session.add(state)
    db_session.commit()

    reports = await reconcile_bot_state(db_session, modes=("testnet",), apply=False, commit=False, source="test")

    db_session.refresh(state)
    assert reports[0].new_bankroll == pytest.approx(100.0)
    assert state.testnet_bankroll == pytest.approx(-74.49)
    assert state.bankroll == pytest.approx(-74.49)


@pytest.mark.asyncio
async def test_reconciliation_clamps_depleted_simulated_available_bankroll(db_session):
    state = BotState(mode="testnet", bankroll=-74.49, testnet_bankroll=-74.49, testnet_pnl=0.0)
    loss = Trade(
        market_ticker="testnet-loss",
        direction="up",
        entry_price=0.5,
        size=25.0,
        settled=True,
        result="loss",
        pnl=-174.49,
        trading_mode="testnet",
        settlement_time=datetime.now(timezone.utc),
    )
    db_session.add_all([state, loss])
    db_session.commit()

    reports = await reconcile_bot_state(
        db_session,
        modes=("testnet",),
        apply=True,
        commit=True,
        source="test",
    )

    db_session.refresh(state)
    assert reports[0].new_bankroll == pytest.approx(0.0)
    assert reports[0].new_total_pnl == pytest.approx(-174.49)
    assert "clamped to $0.00" in reports[0].warnings[0]
    assert state.testnet_bankroll == pytest.approx(0.0)
    assert state.bankroll == pytest.approx(0.0)
    assert state.testnet_pnl == pytest.approx(-174.49)


@pytest.mark.asyncio
async def test_live_reconciliation_uses_total_equity_not_position_value_only(
    db_session, monkeypatch
):
    state = BotState(mode="live", bankroll=4.23, total_pnl=-95.77)
    db_session.add(state)
    db_session.commit()

    async def fake_total_equity():
        return 163.56

    monkeypatch.setattr(
        "backend.core.bankroll_reconciliation.fetch_pm_total_equity",
        fake_total_equity,
    )

    reports = await reconcile_bot_state(
        db_session,
        modes=("live",),
        apply=True,
        commit=True,
        source="test",
    )

    db_session.refresh(state)
    assert reports[0].new_bankroll == pytest.approx(163.56)
    assert state.bankroll == pytest.approx(163.56)
    # PnL = realized trade ledger (no settled trades in this test → 0.0).
    # We do NOT use bankroll-delta (new_bankroll - initial_deposit) because
    # that would count deposits as profit. See ADR-002.
    assert state.total_pnl == pytest.approx(0.0)


@pytest.mark.asyncio
async def test_live_reconciliation_keeps_realized_ledger_pnl_even_if_profile_pnl_differs(
    db_session, monkeypatch
):
    state = BotState(mode="live", bankroll=125.0, total_pnl=11.0)
    settled_win = Trade(
        market_ticker="live-win",
        direction="up",
        entry_price=0.5,
        size=10.0,
        settled=True,
        result="win",
        pnl=5.0,
        trading_mode="live",
        settlement_time=datetime.now(timezone.utc),
    )
    db_session.add_all([state, settled_win])
    db_session.commit()

    async def fake_total_equity():
        return 163.56

    monkeypatch.setattr(
        "backend.core.bankroll_reconciliation.fetch_pm_total_equity",
        fake_total_equity,
    )

    reports = await reconcile_bot_state(
        db_session,
        modes=("live",),
        apply=True,
        commit=True,
        source="test",
    )

    db_session.refresh(state)
    assert reports[0].realized_pnl == pytest.approx(5.0)
    assert state.total_pnl == pytest.approx(5.0)


@pytest.mark.asyncio
async def test_live_reconciliation_preserves_financial_cache_when_equity_unavailable(
    db_session, monkeypatch
):
    state = BotState(mode="live", bankroll=168.72, total_pnl=68.72)
    db_session.add(state)
    db_session.commit()

    settled_loss = Trade(
        market_ticker="historical-live-loss",
        direction="up",
        entry_price=0.5,
        size=2500.0,
        settled=True,
        result="loss",
        pnl=-2500.0,
        trading_mode="live",
        settlement_time=datetime.now(timezone.utc),
    )
    db_session.add(settled_loss)
    db_session.commit()

    async def unavailable_total_equity():
        return None

    monkeypatch.setattr(
        "backend.core.bankroll_reconciliation.fetch_pm_total_equity",
        unavailable_total_equity,
    )

    reports = await reconcile_bot_state(
        db_session,
        modes=("live",),
        apply=True,
        commit=True,
        source="test",
    )

    db_session.refresh(state)
    assert reports[0].new_bankroll == pytest.approx(168.72)
    assert reports[0].new_total_pnl == pytest.approx(68.72)
    assert state.bankroll == pytest.approx(168.72)
    assert state.total_pnl == pytest.approx(68.72)


def test_live_bot_state_financial_fields_are_write_protected(db_session):
    state = BotState(mode="live", bankroll=182.40, total_pnl=82.40)
    db_session.add(state)
    db_session.commit()

    state.bankroll = -2620.79
    state.total_pnl = -2704.70
    db_session.commit()

    db_session.refresh(state)
    assert state.bankroll == pytest.approx(182.40)
    assert state.total_pnl == pytest.approx(82.40)


def test_live_bot_state_financial_fields_can_be_updated_by_reconciliation(db_session):
    state = BotState(mode="live", bankroll=-2620.79, total_pnl=-2704.70)
    db_session.add(state)
    db_session.commit()

    db_session.info["allow_live_financial_update"] = True
    try:
        state.bankroll = 182.40
        state.total_pnl = 82.40
        db_session.commit()
    finally:
        db_session.info.pop("allow_live_financial_update", None)

    db_session.refresh(state)
    assert state.bankroll == pytest.approx(182.40)
    assert state.total_pnl == pytest.approx(82.40)
