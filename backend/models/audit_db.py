"""Domain model: audit — split from database.py.
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
    JSON,
    Text,
    ForeignKey,
    Index,
)
from sqlalchemy.orm import relationship

from backend.models.base_db import Base

class ActivityLog(Base):
    """Log of all strategy decisions and trading activity."""

    __tablename__ = "activity_log"

    id = Column(Integer, primary_key=True, index=True)
    timestamp = Column(DateTime, default=lambda: datetime.now(timezone.utc), index=True)
    strategy_name = Column(String(100), nullable=False, index=True)
    decision_type = Column(
        String(50), nullable=False
    )  # 'entry', 'exit', 'hold', 'adjustment'
    data = Column(JSON, nullable=False)  # Full decision context
    confidence_score = Column(Float, nullable=False)  # 0.0-1.0
    mode = Column(String(20), nullable=False)  # 'paper' or 'live'



class AuditLog(Base):
    """Comprehensive audit log for all money-related operations."""

    __tablename__ = "audit_log"

    id = Column(Integer, primary_key=True, index=True)
    timestamp = Column(DateTime, default=lambda: datetime.now(timezone.utc), index=True)
    event_type = Column(
        String, nullable=False, index=True
    )  # TRADE_CREATED, SETTLEMENT_COMPLETED, POSITION_UPDATED, WALLET_RECONCILED
    entity_type = Column(String, nullable=False)  # TRADE, POSITION, WALLET, CONFIG
    entity_id = Column(
        String, nullable=False, index=True
    )  # trade_id, position_id, wallet_address
    old_value = Column(JSON, nullable=True)  # Previous state snapshot
    new_value = Column(JSON, nullable=True)  # New state snapshot
    user_id = Column(String, default="system")  # "system", "admin", "strategy:btc_5min"

    # Legacy fields for backward compatibility
    actor = Column(String, default="system")
    action = Column(String, nullable=True)
    details = Column(JSON, nullable=True)



class ActivityEventRecord(Base):
    """Persistent record of activity events from all platforms.

    Mirror of backend.core.activity.models.ActivityEvent for DB storage.
    Enables historical queries, reconciliation, and audit trails.
    """

    __tablename__ = "activity_events"

    id = Column(String, primary_key=True)
    source = Column(
        String, nullable=False, index=True
    )  # aster, hyperliquid, lighter, polymarket, azuro, limitless
    event_type = Column(
        String, nullable=False, index=True
    )  # deposit, withdrawal, trade_open, trade_closed, buy, sell, redeem
    wallet_address = Column(String, nullable=False, index=True)
    platform = Column(String, nullable=False, index=True)
    amount = Column(Float, nullable=False)
    token = Column(String, nullable=True, default="USDC")
    tx_hash = Column(String, nullable=True, index=True)
    timestamp = Column(
        DateTime, default=lambda: datetime.now(timezone.utc), index=True, nullable=False
    )
    trade_id = Column(String, nullable=True, index=True)  # FK to Trade if matched
    order_id = Column(String, nullable=True)
    side = Column(String, nullable=True)  # buy, sell
    price = Column(Float, nullable=True)
    fee = Column(Float, nullable=True)
    pnl = Column(Float, nullable=True)
    market_ticker = Column(String, nullable=True)
    raw_data = Column(JSON, nullable=True)



class Setting(Base):
    """Application settings persisted in database."""

    __tablename__ = "settings"

    id = Column(Integer, primary_key=True, index=True)
    key = Column(String, unique=True, nullable=False, index=True)
    value = Column(Text, nullable=False)
    description = Column(String, nullable=True)
    type = Column(String, default="string")  # string, int, bool, float
    created_at = Column(
        DateTime, default=lambda: datetime.now(timezone.utc), index=True
    )
    updated_at = Column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        index=True,
    )
    updated_by_user_id = Column(String, nullable=True, default="system")

    def __repr__(self):
        return (
            f"<Setting(key={self.key}, type={self.type}, value={self.value[:50]}...)>"
        )


class SystemSettings(Base):
    """System settings for runtime configuration (MiroFish, strategies, risk params)."""

    __tablename__ = "system_settings"

    id = Column(Integer, primary_key=True, index=True)
    key = Column(String(100), unique=True, nullable=False, index=True)
    value = Column(JSON, nullable=False)
    updated_at = Column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    def __repr__(self):
        return f"<SystemSettings(key={self.key}, value={self.value})>"



class ErrorLog(Base):
    """Centralized error logging with structured context."""

    __tablename__ = "error_logs"

    id = Column(Integer, primary_key=True, index=True)
    timestamp = Column(
        DateTime, default=lambda: datetime.now(timezone.utc), index=True, nullable=False
    )
    error_type = Column(String(255), nullable=False, index=True)
    message = Column(Text, nullable=False)
    endpoint = Column(String(255), nullable=True, index=True)
    method = Column(String(10), nullable=True)
    user_id = Column(String(255), nullable=True, index=True)
    stack_trace = Column(Text, nullable=True)
    status_code = Column(Integer, nullable=True)
    request_id = Column(String(255), nullable=True, index=True)
    details = Column(Text, nullable=True)

    __table_args__ = (
        Index("idx_error_logs_type_timestamp", "error_type", "timestamp"),
        Index("idx_error_logs_endpoint_timestamp", "endpoint", "timestamp"),
    )



# Knowledge Graph models for Wave 10
class KgNode(Base):
    """Knowledge Graph Node - represents entities in the graph."""

    __tablename__ = "kg_node"

    node_id = Column(String, primary_key=True, index=True)
    node_type = Column(
        String, nullable=False, index=True
    )  # 'strategy', 'gene', 'market', 'trade', 'regime', 'event'
    label = Column(String, nullable=False)
    properties_json = Column(Text, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class KgEdge(Base):
    """Knowledge Graph Edge - represents relationships between nodes."""

    __tablename__ = "kg_edge"

    edge_id = Column(String, primary_key=True, index=True)
    from_node_id = Column(
        String, ForeignKey("kg_node.node_id"), nullable=False, index=True
    )
    to_node_id = Column(
        String, ForeignKey("kg_node.node_id"), nullable=False, index=True
    )
    relationship = Column(
        String, nullable=False
    )  # 'HAS_GENE', 'TRADED_ON', 'MUTATED_FROM', 'KILLED_BY', etc.
    weight = Column(Float, default=1.0)
    properties_json = Column(Text, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


# Indexes for Knowledge Graph
Index("idx_kg_from", KgEdge.from_node_id, KgEdge.relationship)
Index("idx_kg_to", KgEdge.to_node_id, KgEdge.relationship)
Index("idx_kg_type", KgNode.node_type)

