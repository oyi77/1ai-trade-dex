import sys
from datetime import datetime, timedelta
import io
import pytest
from unittest import mock
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# --- App imports ---
from backend.models.database import Base, Trade

# Import the script under test
import scripts.close_stale_positions as close_stale

# --------
# Fixtures
# --------
@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    yield sessionmaker(bind=engine)()

@pytest.fixture
def sample_trades(db):
    def naive(dt):
        return dt.replace(tzinfo=None)
    now = datetime.now()
    stale = Trade(
        market_ticker="STALE_MK",
        settled=False,
        timestamp=naive(now - timedelta(hours=54)),
        direction="up",
        entry_price=0.3,
        size=100.0,
    )
    recent = Trade(
        market_ticker="FRESH_MK",
        settled=False,
        timestamp=naive(now - timedelta(hours=4)),
        direction="down",
        entry_price=0.7,
        size=30.0,
    )
    edge = Trade(
        market_ticker="EDGE_MK",
        settled=False,
        timestamp=naive(now - timedelta(hours=24)),
        direction="up",
        entry_price=0.5,
        size=50.0,
        edge_at_entry=None,
    )
    db.add_all([stale, recent, edge])
    db.commit()
    return [stale, recent, edge]

# ---------------
# Core Unit Tests
# ---------------
def test_get_stale_trades(db, sample_trades):
    naive_now = datetime.now()
    with mock.patch.object(close_stale, "_now", return_value=naive_now):
        res = close_stale._get_stale_trades(db, hours=48)
        assert all(isinstance(t, Trade) for t in res)
        assert {t.market_ticker for t in res} == {"STALE_MK"}, "Only trade >48h should appear"
        # 24h threshold hits both 'STALE_MK' and 'EDGE_MK'
        res_24 = close_stale._get_stale_trades(db, hours=24)
        assert len(res_24) == 2
        mt = {t.market_ticker for t in res_24}
        assert "STALE_MK" in mt and "EDGE_MK" in mt

def test_estimate_pnl_up_down():
    t_up = Trade(direction="up", entry_price=0.3, size=100.0)
    t_down = Trade(direction="down", entry_price=0.7, size=20.0)
    assert close_stale._estimate_pnl(t_up, 0.4) == 10.0  # (0.4-0.3)*100
    assert close_stale._estimate_pnl(t_down, 0.5) == 4.0  # (0.7-0.5)*20
    assert close_stale._estimate_pnl(t_up, None) is None
    assert close_stale._estimate_pnl(Trade(direction=None), 1.0) is None

def test_determine_action_cases():
    trade = Trade(result=None)
    assert close_stale._determine_action(trade, edge_pp=10.0) == "hold"
    trade2 = Trade(result="win")
    assert close_stale._determine_action(trade2, edge_pp=None) == "resolve"
    trade3 = Trade(result=None)
    assert close_stale._determine_action(trade3, edge_pp=None) == "exit"

# ------
# CLI/Integration: monkeypatch/mocking
# ------
def run_script(args, db_patch, price_patch):
    db_cm = mock.MagicMock()
    db_cm.__enter__.return_value = db_patch
    db_cm.__exit__.return_value = None
    naive_now = datetime.now()
    with mock.patch.object(close_stale, "_now", return_value=naive_now):
        with mock.patch.object(close_stale, "get_db_session", return_value=db_cm):
            with mock.patch.object(close_stale, "_fetch_current_price", price_patch):
                with mock.patch.object(sys, "argv", ["close_stale_positions.py"] + args):
                    buf = io.StringIO()
                    with mock.patch("sys.stdout", buf):
                        rc = close_stale.main()
                    out = buf.getvalue()
                    return rc, out

def test_cli_dry_run_no_stale(db):
    rc, out = run_script(["--hours", "4"], db, lambda _: None)
    assert "No stale positions found" in out
    assert rc == 0

def test_cli_dry_run_has_stale(db, sample_trades):
    rc, out = run_script(["--hours", "48"], db, lambda mt: 0.5)
    assert "STALE_MK" in out
    assert "To close 1 positions" in out
    assert rc == 0
    rc2, out2 = run_script(["--hours", "24"], db, lambda mt: 0.5)
    assert "To close 2 positions" in out2

@pytest.mark.parametrize("flag_combo, expect_fail", [
    (["--execute"], True),
    (["--execute", "--force"], False),
])
def test_cli_execute_force_gate(db, sample_trades, flag_combo, expect_fail):
    rc, out = run_script(flag_combo, db, lambda mt: 0.4)
    if expect_fail:
        assert rc == 1
        assert "requires --force" in out
    else:
        assert rc == 0


def test_cli_hours_respects_age(db, sample_trades):
    # --hours=30 only returns the 54h trade
    rc, out = run_script(["--hours", "30"], db, lambda mt: 0.4)
    assert "STALE_MK" in out and "EDGE_MK" not in out
    rc, out = run_script(["--hours", "24"], db, lambda mt: 0.4)
    assert "EDGE_MK" in out


def test_cli_prints_est_pnl(db, sample_trades):
    rc, out = run_script(["--hours", "54"], db, lambda mt: 0.9)
    # Our only trade has: direction up, entry_price 0.3, size 100, price=0.9
    # PnL: (0.9-0.3)*100 = 60.0
    assert "60.0" in out

# Test that no actual network/calls/place_limit_order are made via mocking

