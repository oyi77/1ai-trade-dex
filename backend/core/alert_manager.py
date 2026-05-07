"""Alert manager for detecting and reporting critical conditions."""

import logging
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any
from collections import deque
from sqlalchemy.orm import Session

from backend.models.database import Alert, AlertConfig

logger = logging.getLogger("alert_manager")


class AlertManager:
    """Manages alert detection and logging for critical conditions."""

    def __init__(self, db: Session):
        self.db = db
        self._error_window: deque = deque(maxlen=100)  # Track errors in last 60 seconds
        self._alert_cooldown: Dict[str, datetime] = {}  # Prevent alert spam
        self.cooldown_seconds = 300  # 5 minutes between duplicate alerts
        self._ensure_default_config()

    def _ensure_default_config(self):
        """Initialize default alert configurations if not present."""
        defaults = [
            ("NEGATIVE_BALANCE", True, 0.0, "absolute", "CRITICAL"),
            ("POSITION_DISCREPANCY", True, 0.05, "percent", "WARNING"),
            ("FAILED_SETTLEMENT", True, None, None, "CRITICAL"),
            ("HIGH_SLIPPAGE", True, 0.01, "percent", "WARNING"),
            ("CIRCUIT_BREAKER", True, None, None, "CRITICAL"),
            ("ERROR_RATE", True, 10.0, "per_minute", "HIGH"),
            ("MEMORY_USAGE", True, 80.0, "percent", "HIGH"),
            ("DISK_SPACE", True, 10.0, "percent", "CRITICAL"),
            ("CONNECTION_POOL", True, None, None, "CRITICAL"),
        ]

        for alert_type, enabled, threshold, unit, severity in defaults:
            existing = self.db.query(AlertConfig).filter_by(alert_type=alert_type).first()
            if not existing:
                config = AlertConfig(
                    alert_type=alert_type,
                    enabled=enabled,
                    threshold_value=threshold,
                    threshold_unit=unit,
                    severity=severity,
                )
                self.db.add(config)

        try:
            self.db.commit()
        except Exception as e:
            logger.warning(f"Failed to initialize alert config: {e}")
            self.db.rollback()

    def check_negative_balance(self, wallet_id: str, balance: float, mode: str) -> Optional[Alert]:
        """Check for negative balance condition."""
        config = self.db.query(AlertConfig).filter_by(alert_type="NEGATIVE_BALANCE").first()
        if not config or not config.enabled:
            return None

        if balance < 0:
            message = f"Negative balance detected: {mode} wallet {wallet_id} has balance ${balance:.2f}"
            alert = self._create_alert(
                alert_type="NEGATIVE_BALANCE",
                severity=config.severity,
                entity_type="WALLET",
                entity_id=wallet_id,
                message=message,
            )
            logger.critical(message)
            return alert

        return None

    def check_position_discrepancy(
        self,
        position_id: str,
        db_value: float,
        blockchain_value: float,
        mode: str
    ) -> Optional[Alert]:
        """Check for position discrepancy between DB and blockchain."""
        config = self.db.query(AlertConfig).filter_by(alert_type="POSITION_DISCREPANCY").first()
        if not config or not config.enabled:
            return None

        if db_value == 0 and blockchain_value == 0:
            return None

        threshold = config.threshold_value or 0.05
        discrepancy = abs(db_value - blockchain_value) / max(db_value, blockchain_value, 1.0)

        if discrepancy > threshold:
            message = (
                f"Position discrepancy detected: {mode} position {position_id} "
                f"DB=${db_value:.2f} vs Blockchain=${blockchain_value:.2f} "
                f"({discrepancy:.1%} > {threshold:.1%} threshold)"
            )
            alert = self._create_alert(
                alert_type="POSITION_DISCREPANCY",
                severity=config.severity,
                entity_type="POSITION",
                entity_id=position_id,
                message=message,
            )
            logger.warning(message)
            return alert

        return None

    def check_failed_settlement(self, trade_id: int, reason: str, mode: str) -> Optional[Alert]:
        """Check for failed settlement."""
        config = self.db.query(AlertConfig).filter_by(alert_type="FAILED_SETTLEMENT").first()
        if not config or not config.enabled:
            return None

        message = f"Settlement failed: {mode} trade {trade_id} - {reason}"
        alert = self._create_alert(
            alert_type="FAILED_SETTLEMENT",
            severity=config.severity,
            entity_type="TRADE",
            entity_id=str(trade_id),
            message=message,
        )
        logger.critical(message)
        return alert

    def check_high_slippage(
        self,
        trade_id: int,
        expected_price: float,
        actual_price: float,
        position_value: float,
        mode: str
    ) -> Optional[Alert]:
        """Check for high slippage on order execution."""
        config = self.db.query(AlertConfig).filter_by(alert_type="HIGH_SLIPPAGE").first()
        if not config or not config.enabled:
            return None

        threshold = config.threshold_value or 0.01
        slippage = abs(expected_price - actual_price) / expected_price if expected_price > 0 else 0
        slippage_value = slippage * position_value

        if slippage > threshold:
            message = (
                f"High slippage detected: {mode} trade {trade_id} "
                f"expected ${expected_price:.4f} got ${actual_price:.4f} "
                f"({slippage:.2%} > {threshold:.2%} threshold, ${slippage_value:.2f} impact)"
            )
            alert = self._create_alert(
                alert_type="HIGH_SLIPPAGE",
                severity=config.severity,
                entity_type="TRADE",
                entity_id=str(trade_id),
                message=message,
            )
            logger.warning(message)
            return alert

        return None

    def _create_alert(
        self,
        alert_type: str,
        severity: str,
        entity_type: str,
        entity_id: str,
        message: str,
    ) -> Alert:
        """Create and persist an alert record."""
        alert = Alert(
            timestamp=datetime.now(timezone.utc),
            alert_type=alert_type,
            severity=severity,
            entity_type=entity_type,
            entity_id=entity_id,
            message=message,
            resolved=False,
        )

        self.db.add(alert)
        try:
            self.db.commit()
            self.db.refresh(alert)
        except Exception as e:
            logger.error(f"Failed to persist alert: {e}")
            self.db.rollback()

        return alert

    def resolve_alert(self, alert_id: int) -> bool:
        """Mark an alert as resolved."""
        alert = self.db.query(Alert).filter_by(id=alert_id).first()
        if not alert:
            return False

        alert.resolved = True
        alert.resolved_at = datetime.now(timezone.utc)

        try:
            self.db.commit()
            logger.info(f"Alert {alert_id} resolved")
            return True
        except Exception as e:
            logger.error(f"Failed to resolve alert {alert_id}: {e}")
            self.db.rollback()
            return False

    def check_circuit_breaker(self, breaker_name: str, state: str) -> Optional[Alert]:
        """Check if circuit breaker has opened."""
        config = self.db.query(AlertConfig).filter_by(alert_type="CIRCUIT_BREAKER").first()
        if not config or not config.enabled:
            return None

        if state == "open":
            alert_key = f"circuit_breaker_{breaker_name}"
            if self._should_alert(alert_key):
                message = f"Circuit breaker '{breaker_name}' has OPENED"
                alert = self._create_alert(
                    alert_type="CIRCUIT_BREAKER",
                    severity=config.severity,
                    entity_type="SYSTEM",
                    entity_id=breaker_name,
                    message=message,
                )
                logger.critical(message)
                return alert

        return None

    def record_error(self):
        """Record an error occurrence for rate tracking."""
        self._error_window.append(datetime.now(timezone.utc))

    def check_error_rate(self) -> Optional[Alert]:
        """Check if error rate exceeds 10 errors per minute."""
        config = self.db.query(AlertConfig).filter_by(alert_type="ERROR_RATE").first()
        if not config or not config.enabled:
            return None

        now = datetime.now(timezone.utc)
        threshold = config.threshold_value or 10.0

        recent_errors = [
            ts for ts in self._error_window
            if (now - ts).total_seconds() < 60
        ]
        error_count = len(recent_errors)

        if error_count > threshold:
            alert_key = "error_rate_high"
            if self._should_alert(alert_key):
                message = f"Error rate exceeded threshold: {error_count} errors/minute (threshold: {threshold})"
                alert = self._create_alert(
                    alert_type="ERROR_RATE",
                    severity=config.severity,
                    entity_type="SYSTEM",
                    entity_id="error_rate",
                    message=message,
                )
                logger.error(message)
                return alert

        return None

    def check_memory_usage(self, memory_percent: float) -> Optional[Alert]:
        """Check if memory usage exceeds 80%."""
        config = self.db.query(AlertConfig).filter_by(alert_type="MEMORY_USAGE").first()
        if not config or not config.enabled:
            return None

        threshold = config.threshold_value or 80.0

        if memory_percent > threshold:
            alert_key = "memory_high"
            if self._should_alert(alert_key):
                message = f"Memory usage critical: {memory_percent:.1f}% (threshold: {threshold}%)"
                alert = self._create_alert(
                    alert_type="MEMORY_USAGE",
                    severity=config.severity,
                    entity_type="SYSTEM",
                    entity_id="memory",
                    message=message,
                )
                logger.error(message)
                return alert

        return None

    def check_disk_space(self, disk_percent_free: float) -> Optional[Alert]:
        """Check if disk space is below 10% free."""
        config = self.db.query(AlertConfig).filter_by(alert_type="DISK_SPACE").first()
        if not config or not config.enabled:
            return None

        threshold = config.threshold_value or 10.0

        if disk_percent_free < threshold:
            alert_key = "disk_low"
            if self._should_alert(alert_key):
                message = f"Disk space critically low: {disk_percent_free:.1f}% free (threshold: {threshold}%)"
                alert = self._create_alert(
                    alert_type="DISK_SPACE",
                    severity=config.severity,
                    entity_type="SYSTEM",
                    entity_id="disk",
                    message=message,
                )
                logger.critical(message)
                return alert

        return None

    def check_connection_pool(self, pool_size: int, active_connections: int) -> Optional[Alert]:
        """Check if database connection pool is exhausted."""
        config = self.db.query(AlertConfig).filter_by(alert_type="CONNECTION_POOL").first()
        if not config or not config.enabled:
            return None

        if active_connections >= pool_size:
            alert_key = "connection_pool_exhausted"
            if self._should_alert(alert_key):
                message = f"Database connection pool exhausted: {active_connections}/{pool_size}"
                alert = self._create_alert(
                    alert_type="CONNECTION_POOL",
                    severity=config.severity,
                    entity_type="SYSTEM",
                    entity_id="db_pool",
                    message=message,
                )
                logger.critical(message)
                return alert

        return None

    def _should_alert(self, alert_key: str) -> bool:
        """Check if enough time has passed since last alert of this type."""
        now = datetime.now(timezone.utc)
        last_alert = self._alert_cooldown.get(alert_key)

        if last_alert is None:
            self._alert_cooldown[alert_key] = now
            return True

        elapsed = (now - last_alert).total_seconds()
        if elapsed >= self.cooldown_seconds:
            self._alert_cooldown[alert_key] = now
            return True

        return False

    def get_recent_alerts(
        self,
        limit: int = 100,
        alert_type: Optional[str] = None,
        severity: Optional[str] = None,
        resolved: Optional[bool] = None
    ) -> List[Dict[str, Any]]:
        """Get recent alerts from database."""
        query = self.db.query(Alert)

        if alert_type:
            query = query.filter(Alert.alert_type == alert_type)
        if severity:
            query = query.filter(Alert.severity == severity)
        if resolved is not None:
            query = query.filter(Alert.resolved == resolved)

        alerts = query.order_by(Alert.timestamp.desc()).limit(limit).all()

        return [
            {
                "id": alert.id,
                "timestamp": alert.timestamp.isoformat(),
                "alert_type": alert.alert_type,
                "severity": alert.severity,
                "entity_type": alert.entity_type,
                "entity_id": alert.entity_id,
                "message": alert.message,
                "resolved": alert.resolved,
                "resolved_at": alert.resolved_at.isoformat() if alert.resolved_at else None
            }
            for alert in alerts
        ]

    def get_alert_stats(self) -> Dict[str, Any]:
        """Get alert statistics."""
        from sqlalchemy import func

        type_counts = (
            self.db.query(
                Alert.alert_type,
                func.count(Alert.id).label("count")
            )
            .filter(Alert.resolved == False)
            .group_by(Alert.alert_type)
            .all()
        )

        severity_counts = (
            self.db.query(
                Alert.severity,
                func.count(Alert.id).label("count")
            )
            .filter(Alert.resolved == False)
            .group_by(Alert.severity)
            .all()
        )

        return {
            "by_type": {row.alert_type: row.count for row in type_counts},
            "by_severity": {row.severity: row.count for row in severity_counts},
            "total_unresolved": sum(row.count for row in severity_counts)
        }


def get_system_metrics() -> Dict[str, Any]:
    """Get current system metrics for monitoring."""
    try:
        import psutil

        memory = psutil.virtual_memory()
        memory_percent = memory.percent

        disk = psutil.disk_usage('/')
        disk_percent_free = (disk.free / disk.total) * 100

        from backend.models.database import engine
        pool = engine.pool
        pool_size = pool.size()
        active_connections = pool.checkedout()

        return {
            "memory_percent": memory_percent,
            "disk_percent_free": disk_percent_free,
            "pool_size": pool_size,
            "active_connections": active_connections
        }
    except Exception as e:
        logger.error(f"Failed to get system metrics: {e}")
        return {
            "memory_percent": 0.0,
            "disk_percent_free": 100.0,
            "pool_size": 20,
            "active_connections": 0
        }
