"""Tests for alert manager and alert detection."""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.models.database import Base, Alert, AlertConfig
from backend.core.alert_manager import AlertManager


@pytest.fixture
def test_db():
    """Create in-memory test database."""
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


class TestAlertManager:
    def test_initialization_creates_default_config(self, test_db):
        _manager = AlertManager(test_db)

        configs = test_db.query(AlertConfig).all()
        assert len(configs) == 9

        types = {c.alert_type for c in configs}
        assert "NEGATIVE_BALANCE" in types
        assert "POSITION_DISCREPANCY" in types
        assert "FAILED_SETTLEMENT" in types
        assert "HIGH_SLIPPAGE" in types
        assert "CIRCUIT_BREAKER" in types
        assert "ERROR_RATE" in types
        assert "MEMORY_USAGE" in types
        assert "DISK_SPACE" in types
        assert "CONNECTION_POOL" in types

    def test_check_negative_balance_triggers_alert(self, test_db):
        manager = AlertManager(test_db)

        alert = manager.check_negative_balance(
            wallet_id="0x123",
            balance=-50.0,
            mode="paper"
        )

        assert alert is not None
        assert alert.alert_type == "NEGATIVE_BALANCE"
        assert alert.severity == "CRITICAL"
        assert alert.entity_type == "WALLET"
        assert alert.entity_id == "0x123"
        assert "-50.00" in alert.message
        assert alert.resolved is False

    def test_check_negative_balance_no_alert_for_positive(self, test_db):
        manager = AlertManager(test_db)

        alert = manager.check_negative_balance(
            wallet_id="0x123",
            balance=100.0,
            mode="paper"
        )

        assert alert is None

    def test_check_position_discrepancy_triggers_alert(self, test_db):
        manager = AlertManager(test_db)

        alert = manager.check_position_discrepancy(
            position_id="btc-5min-123",
            db_value=100.0,
            blockchain_value=120.0,
            mode="live"
        )

        assert alert is not None
        assert alert.alert_type == "POSITION_DISCREPANCY"
        assert alert.severity == "WARNING"
        assert alert.entity_type == "POSITION"
        assert alert.entity_id == "btc-5min-123"
        assert "100.00" in alert.message
        assert "120.00" in alert.message

    def test_check_position_discrepancy_no_alert_within_threshold(self, test_db):
        manager = AlertManager(test_db)

        alert = manager.check_position_discrepancy(
            position_id="btc-5min-123",
            db_value=100.0,
            blockchain_value=102.0,
            mode="live"
        )

        assert alert is None

    def test_check_position_discrepancy_no_alert_for_zero_values(self, test_db):
        manager = AlertManager(test_db)

        alert = manager.check_position_discrepancy(
            position_id="btc-5min-123",
            db_value=0.0,
            blockchain_value=0.0,
            mode="live"
        )

        assert alert is None

    def test_check_failed_settlement_triggers_alert(self, test_db):
        manager = AlertManager(test_db)

        alert = manager.check_failed_settlement(
            trade_id=42,
            reason="Market resolution API timeout",
            mode="live"
        )

        assert alert is not None
        assert alert.alert_type == "FAILED_SETTLEMENT"
        assert alert.severity == "CRITICAL"
        assert alert.entity_type == "TRADE"
        assert alert.entity_id == "42"
        assert "timeout" in alert.message.lower()

    def test_check_high_slippage_triggers_alert(self, test_db):
        manager = AlertManager(test_db)

        alert = manager.check_high_slippage(
            trade_id=99,
            expected_price=0.50,
            actual_price=0.52,
            position_value=100.0,
            mode="testnet"
        )

        assert alert is not None
        assert alert.alert_type == "HIGH_SLIPPAGE"
        assert alert.severity == "WARNING"
        assert alert.entity_type == "TRADE"
        assert alert.entity_id == "99"
        assert "0.5000" in alert.message
        assert "0.5200" in alert.message

    def test_check_high_slippage_no_alert_within_threshold(self, test_db):
        manager = AlertManager(test_db)

        alert = manager.check_high_slippage(
            trade_id=99,
            expected_price=0.50,
            actual_price=0.5005,
            position_value=100.0,
            mode="testnet"
        )

        assert alert is None

    def test_resolve_alert(self, test_db):
        manager = AlertManager(test_db)

        alert = manager.check_negative_balance(
            wallet_id="0x456",
            balance=-10.0,
            mode="paper"
        )

        assert alert.resolved is False
        assert alert.resolved_at is None

        success = manager.resolve_alert(alert.id)

        assert success is True

        test_db.refresh(alert)
        assert alert.resolved is True
        assert alert.resolved_at is not None

    def test_resolve_nonexistent_alert(self, test_db):
        manager = AlertManager(test_db)

        success = manager.resolve_alert(99999)

        assert success is False

    def test_disabled_alert_type_no_trigger(self, test_db):
        manager = AlertManager(test_db)

        config = test_db.query(AlertConfig).filter_by(
            alert_type="NEGATIVE_BALANCE"
        ).first()
        config.enabled = False
        test_db.commit()

        alert = manager.check_negative_balance(
            wallet_id="0x789",
            balance=-100.0,
            mode="paper"
        )

        assert alert is None

    def test_custom_threshold_respected(self, test_db):
        manager = AlertManager(test_db)

        config = test_db.query(AlertConfig).filter_by(
            alert_type="POSITION_DISCREPANCY"
        ).first()
        config.threshold_value = 0.10
        test_db.commit()

        alert = manager.check_position_discrepancy(
            position_id="test-pos",
            db_value=100.0,
            blockchain_value=108.0,
            mode="live"
        )

        assert alert is None

        alert = manager.check_position_discrepancy(
            position_id="test-pos",
            db_value=100.0,
            blockchain_value=112.0,
            mode="live"
        )

        assert alert is not None

    def test_alert_persistence(self, test_db):
        manager = AlertManager(test_db)

        manager.check_negative_balance("0xabc", -25.0, "paper")
        manager.check_failed_settlement(123, "API error", "live")

        alerts = test_db.query(Alert).all()
        assert len(alerts) == 2

        critical_alerts = test_db.query(Alert).filter_by(severity="CRITICAL").all()
        assert len(critical_alerts) == 2

    def test_multiple_alerts_same_entity(self, test_db):
        manager = AlertManager(test_db)

        manager.check_negative_balance("0xdef", -10.0, "paper")
        manager.check_negative_balance("0xdef", -20.0, "paper")

        alerts = test_db.query(Alert).filter_by(entity_id="0xdef").all()
        assert len(alerts) == 2

    def test_circuit_breaker_alert(self, test_db):
        manager = AlertManager(test_db)

        alert = manager.check_circuit_breaker("polymarket_api", "open")

        assert alert is not None
        assert alert.alert_type == "CIRCUIT_BREAKER"
        assert alert.severity == "CRITICAL"
        assert "polymarket_api" in alert.message
        assert alert.resolved is False

    def test_circuit_breaker_no_alert_when_closed(self, test_db):
        manager = AlertManager(test_db)

        alert = manager.check_circuit_breaker("polymarket_api", "closed")

        assert alert is None

    def test_error_rate_alert(self, test_db):
        manager = AlertManager(test_db)

        for _ in range(15):
            manager.record_error()

        alert = manager.check_error_rate()

        assert alert is not None
        assert alert.alert_type == "ERROR_RATE"
        assert "15 errors/minute" in alert.message

    def test_error_rate_no_alert_below_threshold(self, test_db):
        manager = AlertManager(test_db)

        for _ in range(5):
            manager.record_error()

        alert = manager.check_error_rate()

        assert alert is None

    def test_memory_usage_alert(self, test_db):
        manager = AlertManager(test_db)

        alert = manager.check_memory_usage(85.0)

        assert alert is not None
        assert alert.alert_type == "MEMORY_USAGE"
        assert alert.severity == "HIGH"
        assert "85.0%" in alert.message

    def test_memory_usage_no_alert_below_threshold(self, test_db):
        manager = AlertManager(test_db)

        alert = manager.check_memory_usage(75.0)

        assert alert is None

    def test_disk_space_alert(self, test_db):
        manager = AlertManager(test_db)

        alert = manager.check_disk_space(5.0)

        assert alert is not None
        assert alert.alert_type == "DISK_SPACE"
        assert alert.severity == "CRITICAL"
        assert "5.0%" in alert.message

    def test_disk_space_no_alert_above_threshold(self, test_db):
        manager = AlertManager(test_db)

        alert = manager.check_disk_space(15.0)

        assert alert is None

    def test_connection_pool_alert(self, test_db):
        manager = AlertManager(test_db)

        alert = manager.check_connection_pool(pool_size=20, active_connections=20)

        assert alert is not None
        assert alert.alert_type == "CONNECTION_POOL"
        assert "20/20" in alert.message

    def test_connection_pool_no_alert_below_limit(self, test_db):
        manager = AlertManager(test_db)

        alert = manager.check_connection_pool(pool_size=20, active_connections=15)

        assert alert is None

    def test_alert_cooldown_prevents_spam(self, test_db):
        manager = AlertManager(test_db)
        manager.cooldown_seconds = 5

        alert1 = manager.check_memory_usage(85.0)
        alert2 = manager.check_memory_usage(85.0)

        assert alert1 is not None
        assert alert2 is None

    def test_get_recent_alerts_with_filters(self, test_db):
        manager = AlertManager(test_db)

        manager.check_memory_usage(85.0)
        manager.check_disk_space(5.0)
        manager.check_connection_pool(20, 20)

        all_alerts = manager.get_recent_alerts(limit=10)
        assert len(all_alerts) == 3

        critical_alerts = manager.get_recent_alerts(severity="CRITICAL")
        assert len(critical_alerts) == 2

        memory_alerts = manager.get_recent_alerts(alert_type="MEMORY_USAGE")
        assert len(memory_alerts) == 1

    def test_get_alert_stats(self, test_db):
        manager = AlertManager(test_db)

        manager.check_memory_usage(85.0)
        manager.check_disk_space(5.0)
        manager.check_connection_pool(20, 20)

        stats = manager.get_alert_stats()

        assert stats["total_unresolved"] == 3
        assert "MEMORY_USAGE" in stats["by_type"]
        assert "DISK_SPACE" in stats["by_type"]
        assert "CONNECTION_POOL" in stats["by_type"]
        assert "CRITICAL" in stats["by_severity"]
        assert "HIGH" in stats["by_severity"]
