from datetime import datetime, timezone

from backend.models.signal_log import SignalLog
from backend.models.database import Base
from backend.repositories.signal_log_repository import SignalLogRepository


def test_signal_log_create_row(db):
    Base.metadata.create_all(db.get_bind())
    ts = datetime.now(timezone.utc)
    sig = SignalLog(
        timestamp=ts,
        market_id="PM-123",
        market_mid=0.56,
        btc_spot=63420.2,
        rsi=55.1,
        momentum_5m=0.12,
        vwap_deviation=0.01,
        sma_crossover=None,
        proposed_side="up",
        edge_pp=0.034,
        oracle_implied=0.52,
        filled=True,
        pnl=0.123,
        strategy="test_strategy",
    )
    db.add(sig)
    db.commit()
    db.refresh(sig)

    row = db.query(SignalLog).filter(SignalLog.id == sig.id).first()
    assert row.market_id == "PM-123"
    assert row.strategy == "test_strategy"
    assert row.filled is True
    assert row.pnl == 0.123
    assert row.market_mid == 0.56
    assert row.proposed_side == "up"
    # SQLite strips tzinfo on read; compare wall-clock equality (naive).
    assert row.timestamp.replace(tzinfo=timezone.utc) == ts


def test_signal_log_repr():
    log = SignalLog(
        id=9,
        market_id="PM-42",
        edge_pp=0.05,
        pnl=1.23,
        strategy="s1",
        timestamp=datetime.now(timezone.utc),
        market_mid=0.5,
    )
    s = repr(log)
    assert s.startswith("<SignalLog id=9 strategy=s1")
    assert "market_id=PM-42" in s
    assert "edge_pp=0.05" in s
    assert "pnl=1.23" in s


def test_signal_log_indexes_exist():
    idxs = SignalLog.__table_args__
    names = {i.name for i in idxs if hasattr(i, "name")}
    assert "ix_signal_log_strategy_market_mid" in names
    assert "ix_signal_log_market_id_timestamp" in names
    assert "ix_signal_log_strategy_timestamp" in names
    assert "ix_signal_log_filled_pnl" in names
    assert len(names) == 4


def test_signal_log_default_strategy(db):
    Base.metadata.create_all(db.get_bind())
    log = SignalLog(
        timestamp=datetime.now(timezone.utc),
        market_id="PM-789",
        market_mid=0.77,
    )
    db.add(log)
    db.commit()
    db.refresh(log)
    assert log.strategy == "btc_oracle"


def test_signal_log_crud(db):
    Base.metadata.create_all(db.get_bind())
    s1 = SignalLog(timestamp=datetime.now(timezone.utc), market_id="PM-1", market_mid=0.1, strategy="foo")
    s2 = SignalLog(timestamp=datetime.now(timezone.utc), market_id="PM-2", market_mid=0.2, strategy="bar", filled=True, pnl=1.5)
    s3 = SignalLog(timestamp=datetime.now(timezone.utc), market_id="PM-1", market_mid=0.3, strategy="foo", filled=None)
    db.add_all([s1, s2, s3])
    db.commit()

    foo_logs = db.query(SignalLog).filter_by(strategy="foo").all()
    assert len(foo_logs) == 2

    pm1 = db.query(SignalLog).filter_by(market_id="PM-1").all()
    assert len(pm1) == 2

    filled_pnl = db.query(SignalLog).filter(SignalLog.filled.is_(True), SignalLog.pnl == 1.5).first()
    assert filled_pnl is not None
    assert filled_pnl.strategy == "bar"


def test_signal_log_timezone_timestamp_column_definition():
    # SQLite engine returns naive datetimes regardless of column type,
    # so we assert the column itself is declared timezone-aware. On
    # Postgres this guarantees tzinfo preservation on read.
    col = SignalLog.__table__.c.timestamp
    assert getattr(col.type, "timezone", False) is True


def test_signal_log_repository_market_time_series(db):
    Base.metadata.create_all(db.get_bind())
    now = datetime.now(timezone.utc)
    logs = [
        SignalLog(timestamp=now, market_id="X", market_mid=0.1, strategy="alpha", edge_pp=0.1, filled=True, pnl=1.0),
        SignalLog(timestamp=now, market_id="X", market_mid=0.2, strategy="alpha", edge_pp=0.3, filled=False),
        SignalLog(timestamp=now, market_id="Y", market_mid=0.1, strategy="beta", edge_pp=0.2, filled=True, pnl=2.0),
        SignalLog(timestamp=now, market_id="X", market_mid=0.4, strategy="alpha", edge_pp=0.7, filled=True),
    ]
    db.add_all(logs)
    db.commit()

    repo = SignalLogRepository(db=db)

    (res, elapsed) = repo.market_time_series("X", limit=2)
    assert len(res) == 2
    assert all(r.market_id == "X" for r in res)
    assert elapsed >= 0.0

    (pending, _) = repo.open_signals_needing_settlement()
    assert any(r.filled and r.pnl is None for r in pending)
    # Both Y(filled, pnl=2.0) and bar entries with pnl set must be excluded.
    assert all(r.filled and r.pnl is None for r in pending)
