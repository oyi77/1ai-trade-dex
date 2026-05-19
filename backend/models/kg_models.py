from datetime import datetime, timezone

from sqlalchemy import Column, String, Float, Integer, DateTime, JSON, Text, ForeignKey, UniqueConstraint, Index

from backend.models.database import Base


class KGEntity(Base):
    __tablename__ = "kg_entities"
    __table_args__ = (
        UniqueConstraint("entity_id", name="uq_kg_entity_id"),
        Index("ix_kg_entity_type", "entity_type"),
    )

    id = Column(Integer, primary_key=True)
    entity_type = Column(String, nullable=False)
    entity_id = Column(String, nullable=False)
    properties = Column(JSON, default=dict)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))


class KGRelation(Base):
    __tablename__ = "kg_relations"
    __table_args__ = (
        Index("ix_kg_relation_from", "from_entity_id"),
        Index("ix_kg_relation_to", "to_entity_id"),
        Index("ix_kg_relation_type", "relation_type"),
    )

    id = Column(Integer, primary_key=True)
    from_entity_id = Column(Integer, ForeignKey("kg_entities.id"), nullable=False)
    to_entity_id = Column(Integer, ForeignKey("kg_entities.id"), nullable=False)
    relation_type = Column(String, nullable=False)
    weight = Column(Float, nullable=False)
    confidence = Column(Float, nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class MarketRegimeSnapshot(Base):
    __tablename__ = "market_regime_snapshots"
    __table_args__ = (
        Index("ix_regime_detected_at", "detected_at"),
    )

    id = Column(Integer, primary_key=True)
    regime = Column(String, nullable=False)
    confidence = Column(Float, nullable=False)
    indicators = Column(JSON)
    detected_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    regime_metadata = Column(JSON)


class ExperimentRecord(Base):
    __tablename__ = "experiment_records"
    __table_args__ = (
        UniqueConstraint("name", name="uq_experiment_name"),
        Index("ix_experiment_status", "status"),
    )

    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    strategy_name = Column(String, ForeignKey("strategy_config.strategy_name", ondelete="SET NULL"), nullable=True, index=True)
    strategy_composition = Column(JSON)
    status = Column(String, nullable=False, default="draft")
    shadow_pnl = Column(Float, default=0.0)
    shadow_trades = Column(Integer, default=0)
    shadow_win_rate = Column(Float, default=0.0)
    backtest_passed = Column(Integer, default=0)
    backtest_sharpe = Column(Float, nullable=True)
    backtest_win_rate = Column(Float, nullable=True)
    degradation_count = Column(Integer, default=0)
    last_degradation_at = Column(DateTime, nullable=True)
    review_reason = Column(Text, nullable=True)
    misc_data = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    promoted_at = Column(DateTime, nullable=True)
    retired_at = Column(DateTime, nullable=True)


class DecisionAuditLog(Base):
    __tablename__ = "decision_audit_logs"
    __table_args__ = (
        Index("ix_decision_timestamp", "timestamp"),
    )

    id = Column(Integer, primary_key=True)
    timestamp = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    agent_name = Column(String)
    decision_type = Column(String, nullable=False)
    input_data = Column(JSON)
    output_data = Column(JSON)
    confidence = Column(Float, default=1.0)
    reasoning = Column(Text)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class LLMCostRecord(Base):
    __tablename__ = "llm_cost_records"
    __table_args__ = (
        Index("ix_llm_cost_timestamp", "timestamp"),
        Index("ix_llm_cost_date_key", "date_key"),
    )

    id = Column(Integer, primary_key=True)
    timestamp = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    model = Column(String, nullable=False)
    token_count = Column(Integer, nullable=False)
    cost_usd = Column(Float, nullable=False)
    purpose = Column(String, nullable=False)
    budget_remaining = Column(Float, nullable=False)
    date_key = Column(String, nullable=False, default=lambda: datetime.now(timezone.utc).strftime("%Y-%m-%d"))
