"""Genome Registry ORM models for strategy persistence.

This module provides extended ORM models for genome persistence.
The core GenomeRegistry model is in backend.models.database.
This module adds: GenomePerformance, GenomeShadowTrade
"""

from datetime import datetime

from sqlalchemy import Column, Index, String, Integer, Float, JSON, DateTime, Boolean
from backend.models.database import Base


class GenomePerformance(Base):
    """Detailed trade history per genome - for fitness calculation."""

    __tablename__ = "genome_performance"

    id = Column(Integer, primary_key=True, autoincrement=True)
    genome_id = Column(String(36), nullable=False, index=True)

    trades = Column(JSON, default=list)

    total_trades = Column(Integer, default=0)
    winning_trades = Column(Integer, default=0)
    losing_trades = Column(Integer, default=0)
    total_pnl = Column(Float, default=0.0)
    avg_pnl = Column(Float, default=0.0)
    avg_win = Column(Float, default=0.0)
    avg_loss = Column(Float, default=0.0)

    sharpe_ratio = Column(Float, default=0.0)
    max_drawdown_pct = Column(Float, default=0.0)
    volatility = Column(Float, default=0.0)
    profit_factor = Column(Float, default=0.0)
    last_updated = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self):
        return f"<GenomePerformance(genome_id={self.genome_id}, trades={self.total_trades}, pnl={self.total_pnl:.2f})>"


class GenomeShadowTrade(Base):
    """Shadow trades for sandbox testing - linked to genome."""

    __tablename__ = "genome_shadow_trade"
    __table_args__ = (
        Index("ix_shadow_genome_settled", "genome_id", "settled"),
        Index("ix_shadow_timestamp", "timestamp"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    genome_id = Column(String(36), nullable=False, index=True)
    genome_registry_id = Column(Integer, nullable=True, index=True)

    market_ticker = Column(String(200), nullable=False)
    direction = Column(String(10), nullable=False)
    entry_price = Column(Float, nullable=False)
    size = Column(Float, nullable=False)
    model_probability = Column(Float, nullable=True)

    settled = Column(Boolean, default=False)
    settlement_price = Column(Float, nullable=True)
    exit_price = Column(Float, nullable=True)
    pnl = Column(Float, nullable=True)
    result = Column(String(10), nullable=True)

    predicted_outcome = Column(Float, nullable=True)
    actual_outcome = Column(Float, nullable=True)
    accuracy_score = Column(Float, nullable=True)

    signal_data = Column(JSON, nullable=True, index=True)  # indexed for forensics
    timestamp = Column(DateTime, default=datetime.utcnow, index=True)
    settled_at = Column(DateTime, nullable=True)

    def __repr__(self):
        return f"<GenomeShadowTrade(genome_id={self.genome_id}, settled={self.settled}, pnl={self.pnl})>"
