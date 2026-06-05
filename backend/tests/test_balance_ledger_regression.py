"""
Regression tests for the persistent balance discrepancy bug.

Root cause: 8 different code paths directly mutate `BotState.bankroll` and
`BotState.total_pnl`. A SQLAlchemy `before_flush` ORM event hook in
`backend.models.database` blocks direct ORM writes to those fields on live
mode unless `db.info["allow_live_financial_update"] = True` is set. Most of
those 8 sites do NOT set the flag, so their writes are silently reverted by
the ORM hook. The `Trade` table is also not consistently used to recompute
the bankroll on every flush, so once a write is reverted, the divergence
between DB and Polymarket grows.

These tests pin down the *correct* behavior:
  1. There is a single, centralized `BotStateLedger` service that all bankroll
     mutations must go through. It sets the permission flag and persists the
     change.
  2. Recording a fill debits the bankroll by `size * price` (actual USDC
     cost), not by `size` (number of shares).
  3. Settling a winning trade credits `pnl` to the bankroll immediately,
     not just at the next reconciliation cycle.
  4. The settlement helper that records the prior balance uses a mode filter,
     never `db.query(BotState).first()`.
"""

import asyncio
import inspect
import re
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.models.database import Base, BotState, Trade


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def ledger_db():
    """Fresh in-memory DB with the same schema as the real one."""
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    db = Session()
    try:
        for mode in ("paper", "testnet", "live"):
            db.add(
                BotState(
                    mode=mode,
                    bankroll=1000.0,
                    total_trades=0,
                    winning_trades=0,
                    total_pnl=0.0,
                    paper_bankroll=1000.0 if mode == "paper" else 0.0,
                    testnet_bankroll=100.0 if mode == "testnet" else 0.0,
                )
            )
        db.commit()
        yield db
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Test 1: Centralized ledger exists
# ---------------------------------------------------------------------------

def test_centralized_ledger_service_exists():
    from backend.core.wallet import botstate_ledger

    assert hasattr(botstate_ledger, "BotStateLedger"), (
        "backend.core.wallet.botstate_ledger must define a BotStateLedger class. "
        "8 different code paths currently mutate state.bankroll directly. "
        "Consolidate them through this single service."
    )


# ---------------------------------------------------------------------------
# Test 2: Ledger correctly credits/debits and survives the ORM hook
# ---------------------------------------------------------------------------

def test_ledger_debit_uses_size_times_price_not_size(ledger_db):
    from backend.core.wallet.botstate_ledger import BotStateLedger

    state = ledger_db.query(BotState).filter_by(mode="paper").first()
    initial = state.paper_bankroll
    ledger_db.commit()

    BotStateLedger.debit_for_fill(
        ledger_db,
        mode="paper",
        size=100.0,
        price=0.5,
    )
    ledger_db.commit()
    ledger_db.refresh(state)
    assert state.paper_bankroll == pytest.approx(initial - 50.0), (
        f"Expected $50 debit (size*price), got ${initial - state.paper_bankroll:.2f}"
    )


def test_ledger_credit_on_win_is_immediate(ledger_db):
    """Settling a win credits (size + pnl) to bankroll — cost basis
    returned plus profit. Without immediate credit, the DB bankroll is
    wrong between settlement and the next reconciliation cycle.
    """
    from backend.core.wallet.botstate_ledger import BotStateLedger

    state = ledger_db.query(BotState).filter_by(mode="paper").first()
    initial = state.paper_bankroll
    ledger_db.commit()

    trade = Trade(
        market_ticker="T1",
        direction="up",
        entry_price=0.5,
        size=10.0,
        settled=True,
        result="win",
        pnl=8.0,
        trading_mode="paper",
        settlement_time=datetime.now(timezone.utc),
    )
    ledger_db.add(trade)
    ledger_db.commit()

    BotStateLedger.credit_on_settlement(ledger_db, mode="paper", trade=trade)
    ledger_db.commit()
    ledger_db.refresh(state)
    assert state.paper_bankroll == pytest.approx(initial + 18.0), (
        f"Expected $18 win credit (size+p&l), got ${state.paper_bankroll - initial:.2f}"
    )
    assert state.paper_wins == 1, f"Expected paper_wins=1, got {state.paper_wins}"


def test_ledger_credit_on_loss_does_not_return_cost_basis(ledger_db):
    """A loss: cost basis is forfeit; pnl is already accounted for at fill time."""
    from backend.core.wallet.botstate_ledger import BotStateLedger

    state = ledger_db.query(BotState).filter_by(mode="paper").first()
    initial = state.paper_bankroll
    ledger_db.commit()

    trade = Trade(
        market_ticker="T2",
        direction="up",
        entry_price=0.5,
        size=10.0,
        settled=True,
        result="loss",
        pnl=-10.0,
        trading_mode="paper",
        settlement_time=datetime.now(timezone.utc),
    )
    ledger_db.add(trade)
    ledger_db.commit()

    BotStateLedger.credit_on_settlement(ledger_db, mode="paper", trade=trade)
    ledger_db.commit()
    ledger_db.refresh(state)
    assert state.paper_bankroll == pytest.approx(initial, abs=0.01), (
        f"Expected $0 net change on loss (cost already debited at fill), "
        f"got ${state.paper_bankroll - initial:.2f}"
    )


def test_ledger_persists_despite_before_flush_hook(ledger_db):
    from backend.core.wallet.botstate_ledger import BotStateLedger

    state = ledger_db.query(BotState).filter_by(mode="live").first()
    initial = state.bankroll
    ledger_db.commit()

    BotStateLedger.debit_for_fill(
        ledger_db,
        mode="live",
        size=100.0,
        price=0.5,
    )
    ledger_db.commit()
    ledger_db.refresh(state)
    assert state.bankroll == pytest.approx(initial - 50.0), (
        "Ledger write was reverted by the before_flush ORM hook. "
        "The BotStateLedger must set db.info['allow_live_financial_update'] "
        "= True for the duration of every write it performs."
    )


# ---------------------------------------------------------------------------
# Test 3: No more bare db.query(BotState).first() in settlement path
# ---------------------------------------------------------------------------

def test_settlement_helpers_uses_mode_filter_not_first():
    from backend.core.settlement import settlement_helpers

    src = inspect.getsource(settlement_helpers)
    bad_pattern = re.compile(
        r"db\.query\(BotState\)\.first\(\)",
        re.MULTILINE,
    )
    matches = bad_pattern.findall(src)
    assert not matches, (
        f"settlement_helpers still uses `db.query(BotState).first()` which "
        f"returns an arbitrary mode's BotState. Found {len(matches)} "
        f"occurrence(s). Replace with `db.query(BotState).filter_by(mode=...)` "
        f"or route through BotStateLedger."
    )


# ---------------------------------------------------------------------------
# Test 4: All bankroll mutation sites go through the ledger
# ---------------------------------------------------------------------------

SITES_TO_CHECK = [
    "backend.core.execution_pipeline.stages.record",
    "backend.core.execution_pipeline.stages.execute",
    "backend.core.activity.event_handler",
    "backend.core.heartbeat",
    "backend.api.system",
]


def test_no_direct_state_bankroll_assignment_outside_ledger():
    import importlib

    from backend.core.wallet import botstate_ledger

    ledger_path = inspect.getfile(botstate_ledger)

    bad_assignments: list[tuple[str, int, str]] = []
    pat = re.compile(
        r"(state|bot)\.(bankroll|paper_bankroll|testnet_bankroll|total_pnl|paper_pnl|testnet_pnl|total_deposits|total_withdrawals|wallet_pnl)\s*([+\-*/]?=)"
    )

    for mod_name in SITES_TO_CHECK:
        try:
            mod = importlib.import_module(mod_name)
        except Exception:
            continue
        path = inspect.getfile(mod)
        if path == ledger_path:
            continue
        try:
            with open(path, "r") as fh:
                for lineno, line in enumerate(fh, start=1):
                    if pat.search(line):
                        bad_assignments.append((mod_name, lineno, line.strip()))
        except OSError:
            continue

    # Zero-resets of counters (e.g. `state.total_pnl = 0.0` on bot reset)
    # are not the kind of mutation that caused the divergence bug; they
    # intentionally clear cached state. Filter them out so only deltas
    # (assignments from variables or expressions) fail this test.
    zero_reset = re.compile(r"\.\w+\s*=\s*(0|0\.0|None)\s*$")
    filtered: list[tuple[str, int, str]] = []
    for (m, ln, l) in bad_assignments:
        if "settlement.py" in m:
            continue
        if zero_reset.search(l):
            continue
        filtered.append((m, ln, l))
    assert not filtered, (
        "Direct assignments to financial fields still exist outside the ledger:\n"
        + "\n".join(f"  {m}:{ln}: {l}" for (m, ln, l) in filtered)
    )


# ---------------------------------------------------------------------------
# Test 5: Continuous reconciliation catches drift
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_continuous_reconciliation_clamps_to_onchain_equity(ledger_db):
    from backend.core.wallet.bankroll_reconciliation import reconcile_bot_state

    state = ledger_db.query(BotState).filter_by(mode="live").first()
    state.bankroll = 99999.0
    ledger_db.commit()

    with patch(
        "backend.core.wallet.bankroll_reconciliation.fetch_pm_total_equity",
        new=AsyncMock(return_value=1234.56),
    ):
        reports = await reconcile_bot_state(
            ledger_db, modes=("live",), apply=True, commit=True
        )
    ledger_db.refresh(state)
    assert state.bankroll == pytest.approx(1234.56, abs=0.01)
