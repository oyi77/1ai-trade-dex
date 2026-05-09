"""Genome Registry ORM models for strategy persistence."""

from datetime import datetime
from uuid import uuid4

from sqlalchemy import Column, String, Integer, Float, JSON, DateTime, Boolean
from sqlalchemy.ext.declarative import declarative_base

Base = declarative_base()


class GenomeRegistry(Base):
    """Persisted StrategyGenome - stores genome DNA for evolution."""
    
    __tablename__ = "genome_registry"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    genome_id = Column(String(36), unique=True, default=lambda: str(uuid4()), index=True)
    strategy_name = Column(String(100), nullable=False, index=True)
    archetype = Column(String(50), nullable=False)
    stage = Column(String(20), nullable=False, default="DRAFT", index=True)
    
    chromosomes = Column(JSON, nullable=False, default=dict)
    lineage = Column(JSON, nullable=False, default=dict)
    fitness_metrics = Column(JSON, nullable=False, default=dict)
    
    # Performance tracking
    trade_count = Column(Integer, default=0)
    total_pnl = Column(Float, default=0.0)
    win_rate = Column(Float, default=0.0)
    sharpe_ratio = Column(Float, default=0.0)
    max_drawdown_pct = Column(Float, default=0.0)
    
    # Metadata
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    last_evaluated_at = Column(DateTime, nullable=True)
    
    death_certificate = Column(JSON, nullable=True)
    
    def __repr__(self):
        return f"<GenomeRegistry(genome_id={self.genome_id}, stage={self.stage}, archetype={self.archetype})>"


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
    
    signal_data = Column(JSON, nullable=True)
    timestamp = Column(DateTime, default=datetime.utcnow)
    settled_at = Column(DateTime, nullable=True)
    
    def __repr__(self):
        return f"<GenomeShadowTrade(genome_id={self.genome_id}, settled={self.settled}, pnl={self.pnl})>"