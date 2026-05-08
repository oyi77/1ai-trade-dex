import pytest
from datetime import timezone
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.models.database import Base, AuditLog
from backend.models.audit_logger import (
    log_audit_event,
    log_trade_created,
    log_settlement_completed,
    log_position_updated,
    log_wallet_reconciled,
)


@pytest.fixture
def test_db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


def test_log_audit_event(test_db):
    entry = log_audit_event(
        db=test_db,
        event_type="TEST_EVENT",
        entity_type="TEST_ENTITY",
        entity_id="test_123",
        old_value={"status": "old"},
        new_value={"status": "new"},
        user_id="test_user",
    )

    assert entry is not None
    assert entry.event_type == "TEST_EVENT"
    assert entry.entity_type == "TEST_ENTITY"
    assert entry.entity_id == "test_123"
    assert entry.old_value == {"status": "old"}
    assert entry.new_value == {"status": "new"}
    assert entry.user_id == "test_user"
    assert entry.timestamp is not None


def test_log_trade_created(test_db):
    entry = log_trade_created(
        db=test_db,
        trade_id=42,
        trade_data={
            "market_ticker": "BTC-UP-5M",
            "direction": "up",
            "size": 5.0,
            "entry_price": 0.65,
            "trading_mode": "paper",
        },
        user_id="strategy:btc_5min",
    )

    assert entry is not None
    assert entry.event_type == "TRADE_CREATED"
    assert entry.entity_type == "TRADE"
    assert entry.entity_id == "42"
    assert entry.new_value["market_ticker"] == "BTC-UP-5M"
    assert entry.new_value["size"] == 5.0
    assert entry.user_id == "strategy:btc_5min"
    assert entry.old_value is None


def test_log_settlement_completed(test_db):
    entry = log_settlement_completed(
        db=test_db,
        trade_id=42,
        old_state={"settled": False, "result": "pending", "pnl": None},
        new_state={"settled": True, "result": "win", "pnl": 35.0},
        user_id="system:settlement",
    )

    assert entry is not None
    assert entry.event_type == "SETTLEMENT_COMPLETED"
    assert entry.entity_type == "TRADE"
    assert entry.entity_id == "42"
    assert entry.old_value["settled"] is False
    assert entry.new_value["settled"] is True
    assert entry.new_value["pnl"] == 35.0
    assert entry.user_id == "system:settlement"


def test_log_position_updated(test_db):
    entry = log_position_updated(
        db=test_db,
        position_id="BTC-UP-5M:42",
        old_state={"size": 5.0},
        new_state={"size": 150.0},
        user_id="system:reconciliation",
    )

    assert entry is not None
    assert entry.event_type == "POSITION_UPDATED"
    assert entry.entity_type == "POSITION"
    assert entry.entity_id == "BTC-UP-5M:42"
    assert entry.old_value["size"] == 5.0
    assert entry.new_value["size"] == 150.0


def test_log_wallet_reconciled(test_db):
    entry = log_wallet_reconciled(
        db=test_db,
        wallet_address="0x1234567890abcdef",
        reconciliation_data={
            "imported_count": 5,
            "updated_count": 3,
            "closed_count": 2,
        },
        user_id="system:reconciliation",
    )

    assert entry is not None
    assert entry.event_type == "WALLET_RECONCILED"
    assert entry.entity_type == "WALLET"
    assert entry.entity_id == "0x1234567890abcdef"
    assert entry.new_value["imported_count"] == 5
    assert entry.new_value["updated_count"] == 3
    assert entry.new_value["closed_count"] == 2


def test_audit_log_query_by_event_type(test_db):
    log_trade_created(test_db, 1, {"market": "A"}, "user1")
    log_trade_created(test_db, 2, {"market": "B"}, "user2")
    log_settlement_completed(test_db, 1, {}, {"pnl": 10.0}, "system")

    test_db.commit()

    trade_events = test_db.query(AuditLog).filter(
        AuditLog.event_type == "TRADE_CREATED"
    ).all()

    assert len(trade_events) == 2
    assert all(e.event_type == "TRADE_CREATED" for e in trade_events)


def test_audit_log_query_by_entity_id(test_db):
    log_trade_created(test_db, 42, {"market": "A"}, "user1")
    log_settlement_completed(test_db, 42, {}, {"pnl": 10.0}, "system")
    log_trade_created(test_db, 99, {"market": "B"}, "user2")

    test_db.commit()

    trade_42_events = test_db.query(AuditLog).filter(
        AuditLog.entity_id == "42"
    ).all()

    assert len(trade_42_events) == 2
    assert all(e.entity_id == "42" for e in trade_42_events)


def test_audit_log_preserves_legacy_fields(test_db):
    entry = log_audit_event(
        db=test_db,
        event_type="TEST_EVENT",
        entity_type="TEST",
        entity_id="123",
        user_id="test_user",
    )

    assert entry.actor == "test_user"
    assert entry.action == "TEST_EVENT"
    assert entry.details is not None
    assert entry.details["entity_type"] == "TEST"


def test_audit_log_handles_null_values(test_db):
    entry = log_audit_event(
        db=test_db,
        event_type="TEST_EVENT",
        entity_type="TEST",
        entity_id="123",
        old_value=None,
        new_value=None,
        user_id="system",
    )

    assert entry is not None
    assert entry.old_value is None
    assert entry.new_value is None


def test_audit_log_timezone_aware(test_db):
    entry = log_trade_created(
        db=test_db,
        trade_id=1,
        trade_data={"market": "TEST"},
    )

    assert entry.timestamp.tzinfo is not None
    assert entry.timestamp.tzinfo == timezone.utc
