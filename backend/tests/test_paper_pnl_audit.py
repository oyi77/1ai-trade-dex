from datetime import datetime, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.scripts import audit_paper_pnl as audit_script
from backend.core.paper_pnl_audit import (
    apply_paper_pnl_recalculation,
    audit_paper_pnl,
    audit_trades,
)
from backend.models.database import Base, BotState, Trade


def make_trade(**kwargs):
    defaults = {
        "market_ticker": "audit-market",
        "platform": "polymarket",
        "strategy": "audit_strategy",
        "trading_mode": "paper",
        "direction": "up",
        "entry_price": 0.5,
        "size": 10.0,
        "timestamp": datetime.now(timezone.utc),
        "settled": True,
        "result": "win",
        "settlement_value": 1.0,
        "pnl": 10.0,
    }
    defaults.update(kwargs)
    return Trade(**defaults)


def test_audit_trades_reports_recomputed_pnl_mismatches():
    stale = make_trade(id=1, entry_price=0.5, size=10.0, pnl=999.0)
    current = make_trade(id=2, entry_price=0.5, size=10.0, pnl=9.98)

    report = audit_trades([stale, current], mismatch_tolerance=0.01)

    assert report.trade_count == 2
    assert report.mismatch_count == 1
    assert report.top_mismatches[0].trade_id == 1
    assert report.top_mismatches[0].recomputed_pnl == 9.98
    assert report.delta_total_pnl < 0


def test_audit_paper_pnl_is_read_only_for_trade_rows():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    db = Session()
    trade = make_trade(entry_price=0.4, size=20.0, pnl=123.0)
    db.add(trade)
    db.commit()

    report = audit_paper_pnl(db)

    db.refresh(trade)
    assert report.mismatch_count == 1
    assert trade.pnl == 123.0
    db.close()


def test_audit_paper_pnl_respects_top_n():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    db = Session()
    db.add(make_trade(id=1, market_ticker="large", pnl=100.0))
    db.add(make_trade(id=2, market_ticker="small", pnl=50.0))
    db.commit()

    report = audit_paper_pnl(db, top_n=1)

    assert report.mismatch_count == 2
    assert len(report.top_mismatches) == 1
    db.close()


def test_apply_paper_pnl_recalculation_updates_trade_and_bot_state():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    db = Session()
    state = BotState(mode="paper", bankroll=1000.0, paper_bankroll=1000.0)
    stale = make_trade(entry_price=0.5, size=10.0, pnl=999.0)
    db.add_all([state, stale])
    db.commit()

    result = apply_paper_pnl_recalculation(db)
    db.commit()

    db.refresh(stale)
    db.refresh(state)
    assert result.updated_trade_count == 1
    assert result.recalculated_bot_state is True
    assert stale.pnl == 9.98
    assert state.paper_pnl == 9.98
    assert state.paper_trades == 1
    db.close()


def test_cli_refuses_non_sqlite_apply_without_external_backup(monkeypatch, capsys):
    monkeypatch.setattr(audit_script, "_sqlite_db_path", lambda: None)

    class FailIfOpened:
        def __call__(self):
            raise AssertionError("SessionLocal should not be opened")

    monkeypatch.setattr(audit_script, "SessionLocal", FailIfOpened())
    monkeypatch.setattr(
        "sys.argv",
        ["audit_paper_pnl", "--apply", "--confirm-apply", "--limit", "0"],
    )

    exit_code = audit_script._main()

    captured = capsys.readouterr()
    assert exit_code == 2
    assert "non-SQLite database detected" in captured.out
