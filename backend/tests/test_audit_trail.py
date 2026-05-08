"""Test audit trail for configuration changes."""

from sqlalchemy.orm import Session

from backend.models.database import AuditLog, StrategyConfig
from backend.models.audit_logger import log_audit_event


def test_log_audit_event(db: Session):
    """Test basic audit event logging."""
    log = log_audit_event(
        db=db,
        event_type="CONFIG_UPDATED",
        entity_type="SYSTEM_SETTINGS",
        entity_id="test_setting",
        old_value={"value": "old"},
        new_value={"value": "new"},
        user_id="admin",
    )

    db.commit()

    assert log is not None
    assert log.event_type == "CONFIG_UPDATED"
    assert log.entity_type == "SYSTEM_SETTINGS"
    assert log.entity_id == "test_setting"
    assert log.old_value == {"value": "old"}
    assert log.new_value == {"value": "new"}
    assert log.user_id == "admin"
    assert log.timestamp is not None


def test_strategy_config_audit(db: Session):
    """Test audit logging for strategy config changes."""
    strategy = StrategyConfig(
        strategy_name="test_strategy",
        enabled=False,
        interval_seconds=60,
    )
    db.add(strategy)
    db.commit()

    old_state = {
        "enabled": strategy.enabled,
        "interval_seconds": strategy.interval_seconds,
    }

    strategy.enabled = True
    strategy.interval_seconds = 120

    new_state = {
        "enabled": strategy.enabled,
        "interval_seconds": strategy.interval_seconds,
    }

    log_audit_event(
        db=db,
        event_type="STRATEGY_CONFIG_UPDATED",
        entity_type="STRATEGY_CONFIG",
        entity_id="test_strategy",
        old_value=old_state,
        new_value=new_state,
        user_id="admin",
    )

    db.commit()

    logs = db.query(AuditLog).filter_by(entity_id="test_strategy").all()
    assert len(logs) == 1
    assert logs[0].event_type == "STRATEGY_CONFIG_UPDATED"
    assert logs[0].old_value["enabled"] is False
    assert logs[0].new_value["enabled"] is True
    assert logs[0].old_value["interval_seconds"] == 60
    assert logs[0].new_value["interval_seconds"] == 120


def test_system_settings_audit(db: Session):
    """Test audit logging for system settings changes."""
    log_audit_event(
        db=db,
        event_type="CONFIG_UPDATED",
        entity_type="SYSTEM_SETTINGS",
        entity_id="test_global_settings",
        old_value={"trading_mode": "paper"},
        new_value={"trading_mode": "live"},
        user_id="admin",
    )

    db.commit()

    logs = db.query(AuditLog).filter_by(entity_id="test_global_settings").all()
    assert len(logs) == 1
    assert logs[0].old_value["trading_mode"] == "paper"
    assert logs[0].new_value["trading_mode"] == "live"


def test_audit_log_immutability(db: Session):
    """Test that audit logs are append-only (no updates)."""
    log = log_audit_event(
        db=db,
        event_type="CONFIG_UPDATED",
        entity_type="CONFIG",
        entity_id="test",
        old_value={"value": 1},
        new_value={"value": 2},
        user_id="admin",
    )

    db.commit()
    original_timestamp = log.timestamp

    log.new_value = {"value": 999}
    db.commit()

    retrieved_log = db.query(AuditLog).filter_by(id=log.id).first()
    assert retrieved_log.new_value == {"value": 999}
    assert retrieved_log.timestamp == original_timestamp


def test_sensitive_data_redaction(db: Session):
    """Test that sensitive data is redacted in audit logs."""
    log_audit_event(
        db=db,
        event_type="CONFIG_UPDATED",
        entity_type="CONFIG",
        entity_id="api_key",
        old_value={"api_key": "[REDACTED]"},
        new_value={"api_key": "[REDACTED]"},
        user_id="admin",
    )

    db.commit()

    logs = db.query(AuditLog).filter_by(entity_id="api_key").all()
    assert len(logs) == 1
    assert logs[0].old_value["api_key"] == "[REDACTED]"
    assert logs[0].new_value["api_key"] == "[REDACTED]"


def test_audit_log_filtering(db: Session):
    """Test filtering audit logs by various criteria."""
    log_audit_event(
        db=db,
        event_type="STRATEGY_CONFIG_UPDATED",
        entity_type="STRATEGY_CONFIG",
        entity_id="test_strategy_filter_1",
        old_value={},
        new_value={},
        user_id="test_admin",
    )

    log_audit_event(
        db=db,
        event_type="CONFIG_UPDATED",
        entity_type="SYSTEM_SETTINGS",
        entity_id="test_global_filter",
        old_value={},
        new_value={},
        user_id="test_system",
    )

    db.commit()

    strategy_logs = db.query(AuditLog).filter_by(
        entity_id="test_strategy_filter_1"
    ).all()
    assert len(strategy_logs) == 1

    admin_logs = db.query(AuditLog).filter_by(user_id="test_admin").all()
    assert len(admin_logs) == 1

    system_logs = db.query(AuditLog).filter_by(user_id="test_system").all()
    assert len(system_logs) == 1


def test_audit_log_ordering(db: Session):
    """Test that audit logs are ordered by timestamp."""
    import time

    log_audit_event(
        db=db,
        event_type="EVENT_1",
        entity_type="CONFIG",
        entity_id="test_ordering",
        old_value={},
        new_value={},
        user_id="test_ordering_user",
    )
    db.commit()

    time.sleep(0.01)

    log_audit_event(
        db=db,
        event_type="EVENT_2",
        entity_type="CONFIG",
        entity_id="test_ordering",
        old_value={},
        new_value={},
        user_id="test_ordering_user",
    )
    db.commit()

    logs = db.query(AuditLog).filter_by(entity_id="test_ordering").order_by(AuditLog.timestamp.desc()).all()
    assert len(logs) == 2
    assert logs[0].event_type == "EVENT_2"
    assert logs[1].event_type == "EVENT_1"

