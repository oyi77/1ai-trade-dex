"""Tests for backend.core.position_monitor."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.core.position_monitor import (
    StalePosition,
    detect_stale_positions,
    mark_position_checked,
    run_position_monitor,
)
from backend.models.database import Base, Trade


@pytest.fixture
def db_session():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def _make_trade(
    session,
    *,
    market_ticker="BTC-UP",
    strategy="btc_oracle",
    trading_mode="paper",
    direction="up",
    size=10.0,
    entry_price=0.5,
    timestamp=None,
    last_sync_at=None,
    settled=False,
):
    trade = Trade(
        market_ticker=market_ticker,
        platform="polymarket",
        strategy=strategy,
        trading_mode=trading_mode,
        direction=direction,
        size=size,
        entry_price=entry_price,
        timestamp=timestamp or datetime.now(timezone.utc),
        last_sync_at=last_sync_at,
        settled=settled,
    )
    session.add(trade)
    session.commit()
    session.refresh(trade)
    return trade


def test_detect_stale_positions_empty(db_session):
    result = detect_stale_positions(db_session)
    assert result == []


def test_detect_stale_positions_recent_trade_not_stale(db_session):
    now = datetime.now(timezone.utc)
    _make_trade(
        db_session,
        timestamp=now - timedelta(minutes=5),
        last_sync_at=now - timedelta(minutes=5),
    )
    result = detect_stale_positions(db_session, stale_after_minutes=30, now=now)
    assert result == []


def test_detect_stale_positions_old_trade_flagged(db_session):
    now = datetime.now(timezone.utc)
    trade = _make_trade(
        db_session,
        timestamp=now - timedelta(minutes=120),
        last_sync_at=now - timedelta(minutes=120),
    )
    result = detect_stale_positions(db_session, stale_after_minutes=30, now=now)
    assert len(result) == 1
    assert result[0].trade_id == trade.id
    assert result[0].age_minutes >= 30


def test_detect_stale_positions_settled_trade_not_flagged(db_session):
    now = datetime.now(timezone.utc)
    _make_trade(
        db_session,
        timestamp=now - timedelta(minutes=120),
        last_sync_at=now - timedelta(minutes=120),
        settled=True,
    )
    result = detect_stale_positions(db_session, stale_after_minutes=30, now=now)
    assert result == []


def test_stale_position_to_dict():
    opened = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    synced = datetime(2026, 1, 1, 13, 0, 0, tzinfo=timezone.utc)
    sp = StalePosition(
        trade_id=42,
        market_ticker="BTC-UP",
        strategy="btc_oracle",
        trading_mode="live",
        direction="up",
        size=25.0,
        opened_at=opened,
        last_sync_at=synced,
        age_minutes=45.678,
    )
    d = sp.to_dict()
    assert set(d.keys()) == {
        "trade_id",
        "market_ticker",
        "strategy",
        "trading_mode",
        "direction",
        "size",
        "opened_at",
        "last_sync_at",
        "age_minutes",
    }
    assert d["trade_id"] == 42
    assert d["market_ticker"] == "BTC-UP"
    assert d["opened_at"] == opened.isoformat()
    assert d["last_sync_at"] == synced.isoformat()
    assert d["age_minutes"] == 45.68


def test_mark_position_checked(db_session):
    now = datetime.now(timezone.utc)
    trade = _make_trade(
        db_session,
        timestamp=now - timedelta(minutes=120),
        last_sync_at=now - timedelta(minutes=120),
    )
    old_sync = trade.last_sync_at
    mark_position_checked(db_session, trade.id)
    db_session.commit()
    db_session.refresh(trade)
    assert trade.last_sync_at is not None
    # last_sync_at may be naive coming back from SQLite; compare as naive UTC.
    new_sync = trade.last_sync_at
    if new_sync.tzinfo is None:
        new_sync = new_sync.replace(tzinfo=timezone.utc)
    if old_sync.tzinfo is None:
        old_sync = old_sync.replace(tzinfo=timezone.utc)
    assert new_sync > old_sync


def test_mark_position_checked_missing_trade(db_session):
    # Should not raise on unknown trade id.
    mark_position_checked(db_session, 999999)


def test_run_position_monitor_no_stale(db_session):
    now = datetime.now(timezone.utc)
    _make_trade(
        db_session,
        timestamp=now - timedelta(minutes=1),
        last_sync_at=now - timedelta(minutes=1),
    )
    with patch("backend.core.position_monitor.AlertManager") as mock_alert:
        result = run_position_monitor(db=db_session)
    assert result == []
    mock_alert.assert_not_called()


def test_run_position_monitor_with_stale(db_session):
    now = datetime.now(timezone.utc)
    trade = _make_trade(
        db_session,
        timestamp=now - timedelta(minutes=120),
        last_sync_at=now - timedelta(minutes=120),
    )
    old_sync = trade.last_sync_at

    with patch("backend.core.position_monitor.AlertManager") as mock_alert_cls:
        mock_alert = mock_alert_cls.return_value
        result = run_position_monitor(db=db_session)

    assert len(result) == 1
    assert result[0].trade_id == trade.id
    # AlertManager instantiated once for the batch
    mock_alert_cls.assert_called_once_with(db_session)
    # create_alert called once for the single stale entry
    assert mock_alert.create_alert.call_count == 1
    call_kwargs = mock_alert.create_alert.call_args.kwargs
    assert call_kwargs["kind"] == "stale_position"
    assert call_kwargs["severity"] == "warning"
    assert call_kwargs["meta"]["trade_id"] == trade.id

    # mark_position_checked was applied → last_sync_at advanced
    db_session.commit()
    db_session.refresh(trade)
    new_sync = trade.last_sync_at
    if new_sync.tzinfo is None:
        new_sync = new_sync.replace(tzinfo=timezone.utc)
    if old_sync.tzinfo is None:
        old_sync = old_sync.replace(tzinfo=timezone.utc)
    assert new_sync > old_sync
