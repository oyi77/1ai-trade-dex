"""Domain model: misc — split from database.py.
Keeps backward compatibility via database.py re-exports.
"""
import json
from datetime import datetime, timezone
from typing import Optional
from loguru import logger

from sqlalchemy import (
    Column,
    Integer,
    String,
    Float,
    DateTime,
    Boolean,
    JSON,
    Text,
    UniqueConstraint,
    Index,
)

from backend.models.engine import Base

class ScheduledJob(Base):
    """Persistent APScheduler job state for crash recovery.

    Stores the registration metadata of every scheduled job so the scheduler
    can rebuild its in-memory job table after a restart. The `job_state_json`
    column captures trigger kwargs (interval, cron, etc.), function id, and
    execution kwargs needed to re-add the job via APScheduler.
    """

    __tablename__ = "scheduled_jobs"

    id = Column(Integer, primary_key=True, index=True)
    job_name = Column(String(255), unique=True, nullable=False, index=True)
    job_state_json = Column(JSON, nullable=False)
    last_run = Column(DateTime, nullable=True)
    next_run = Column(DateTime, nullable=True)
    enabled = Column(Boolean, default=True, nullable=False)
    created_at = Column(
        DateTime, default=lambda: datetime.now(timezone.utc), nullable=False
    )
    updated_at = Column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


class JobQueue(Base):
    """Persistent job queue for crash recovery."""

    __tablename__ = "job_queue"

    id = Column(Integer, primary_key=True, index=True)
    job_type = Column(String(50), nullable=False)
    idempotency_key = Column(String(255), nullable=True)
    priority = Column(String(20), default="medium")  # critical, high, medium, low
    status = Column(
        String(20), default="pending"
    )  # pending, processing, completed, failed
    payload = Column(JSON, nullable=False)
    retry_count = Column(Integer, default=0)
    max_retries = Column(Integer, default=3)
    scheduled_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    __table_args__ = (
        Index("idx_job_queue_status_priority", "status", "priority"),
        UniqueConstraint("job_type", "idempotency_key", name="uq_job_idempotency"),
    )



class PendingApproval(Base):
    __tablename__ = "pending_approvals"
    id = Column(Integer, primary_key=True)
    market_id = Column(String, index=True, nullable=False)
    direction = Column(String, nullable=False)
    size = Column(Float, nullable=False)
    confidence = Column(Float, nullable=False)
    signal_data = Column(JSON, nullable=True)
    status = Column(String, default="pending")  # pending|approved|rejected
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    decided_at = Column(DateTime, nullable=True)



class EquitySnapshot(Base):
    """Daily equity curve snapshots for performance tracking."""

    __tablename__ = "equity_snapshots"
    id = Column(Integer, primary_key=True, index=True)
    timestamp = Column(DateTime, default=lambda: datetime.now(timezone.utc), index=True)
    bankroll = Column(Float, nullable=False)
    total_pnl = Column(Float, default=0.0)
    open_exposure = Column(Float, default=0.0)
    strategy_allocations = Column(JSON, nullable=True)
    trade_count = Column(Integer, default=0)
    win_count = Column(Integer, default=0)



class CalibrationRecord(Base):
    """Track predicted probability vs actual outcome for model calibration."""

    __tablename__ = "calibration_records"
    id = Column(Integer, primary_key=True, index=True)
    strategy = Column(String, nullable=False, index=True)
    market_ticker = Column(String, nullable=False)
    predicted_prob = Column(Float, nullable=False)
    direction = Column(String, nullable=False)
    actual_outcome = Column(String, nullable=True)  # "win"|"loss"|None (pending)
    settlement_value = Column(Float, nullable=True)
    price_bucket = Column(String, nullable=True, index=True)  # e.g. "5-10c", "40-50c"
    timestamp = Column(DateTime, default=lambda: datetime.now(timezone.utc))



class ResearchItemDB(Base):
    __tablename__ = "research_items"
    id = Column(Integer, primary_key=True)
    title = Column(String, nullable=False)
    source = Column(String, nullable=False)
    url = Column(String, nullable=False)
    content_summary = Column(String)
    relevance_score = Column(Float, nullable=False)
    fingerprint = Column(String, unique=True, nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    used_in_decision = Column(Boolean, default=False)



class Alert(Base):
    __tablename__ = "alerts"

    id = Column(Integer, primary_key=True, index=True)
    timestamp = Column(DateTime, default=lambda: datetime.now(timezone.utc), index=True)
    alert_type = Column(String, nullable=False, index=True)
    severity = Column(String, nullable=False)
    entity_type = Column(String, nullable=False)
    entity_id = Column(String, nullable=False)
    message = Column(String, nullable=False)
    resolved = Column(Boolean, default=False, index=True)
    resolved_at = Column(DateTime, nullable=True)

    __table_args__ = (
        Index("idx_alerts_type_severity", "alert_type", "severity"),
        Index("idx_alerts_resolved", "resolved"),
    )

    def __repr__(self):
        return (
            f"<Alert(id={self.id}, type={self.alert_type}, severity={self.severity}, "
            f"entity={self.entity_type}:{self.entity_id}, resolved={self.resolved})>"
        )


class AlertConfig(Base):
    __tablename__ = "alert_config"

    id = Column(Integer, primary_key=True)
    alert_type = Column(String, unique=True, nullable=False)
    enabled = Column(Boolean, default=True)
    threshold_value = Column(Float, nullable=True)
    threshold_unit = Column(String, nullable=True)
    severity = Column(String, default="WARNING")

    def __repr__(self):
        return (
            f"<AlertConfig(type={self.alert_type}, enabled={self.enabled}, "
            f"threshold={self.threshold_value} {self.threshold_unit})>"
        )

