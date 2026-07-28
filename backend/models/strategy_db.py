"""Domain model: strategy — split from database.py.
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
    ForeignKey,
    Index,
)
from sqlalchemy.orm import relationship
from sqlalchemy.ext.hybrid import hybrid_property

from backend.models.base_db import Base

class GenomeRegistry(Base):
    """Registry of genetic algorithms and their configurations."""

    __tablename__ = "genome_registry"

    genome_id = Column(String, primary_key=True, index=True)  # UUID or identifier
    strategy_name = Column(String, nullable=False, index=True)
    archetype = Column(String, nullable=False)
    version = Column(String, nullable=False)
    stage = Column(
        String, nullable=False, index=True
    )  # DRAFT, SHADOW, PAPER, LIVE, GRAVEYARD
    lineage_json = Column(Text, nullable=False)
    chromosomes_json = Column(Text, nullable=False)
    fitness_json = Column(Text, nullable=False)
    chromosome_perf_json = Column(Text, nullable=True)
    death_certificate_json = Column(Text, nullable=True)

    # Native columns derived from fitness_json for efficient querying
    fitness_score = Column(Float, nullable=True, index=True)  # 0.0–1.0 composite score
    fitness_updated_at = Column(
        DateTime, nullable=True
    )  # when fitness was last recalculated
    total_pnl = Column(Float, nullable=True, default=0.0)
    win_rate = Column(Float, nullable=True, default=0.0)
    sharpe_ratio = Column(Float, nullable=True, default=0.0)
    max_drawdown_pct = Column(Float, nullable=True, default=0.0)
    trade_count = Column(Integer, nullable=True, default=0)
    last_evaluated_at = Column(DateTime, nullable=True)
    stage_entered_at = Column(DateTime, nullable=True)

    created_at = Column(DateTime, nullable=True)
    updated_at = Column(DateTime, nullable=True)

    # Relationships
    evolution_logs = relationship(
        "EvolutionLog", back_populates="genome", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("idx_genome_stage_score", "stage", "fitness_score"),
        Index("idx_genome_stage_winrate", "stage", "win_rate"),
        Index("idx_genome_archetype_stage", "archetype", "stage"),
    )

    @hybrid_property
    def fitness_metrics(self) -> dict:
        """Deserialize fitness_json into a dict on read."""
        if self.fitness_json:
            try:
                return json.loads(self.fitness_json)
            except (json.JSONDecodeError, TypeError):
                logger.warning("Corrupted fitness_json for genome %s", self.id)
        return {}

    @fitness_metrics.setter
    def fitness_metrics(self, value: dict):
        """Serialize fitness_metrics dict into fitness_json on write."""
        self.fitness_json = json.dumps(value) if value else "{}"

    @hybrid_property
    def lineage(self) -> dict:
        if self.lineage_json:
            try:
                return json.loads(self.lineage_json)
            except (json.JSONDecodeError, TypeError):
                logger.warning("Corrupted lineage_json for genome %s", self.id)
        return {}

    @lineage.setter
    def lineage(self, value: dict):
        self.lineage_json = json.dumps(value) if value else "{}"

    @hybrid_property
    def chromosomes(self) -> dict:
        if self.chromosomes_json:
            try:
                return json.loads(self.chromosomes_json)
            except (json.JSONDecodeError, TypeError):
                logger.warning("Corrupted chromosomes_json for genome %s", self.id)
        return {}

    @chromosomes.setter
    def chromosomes(self, value: dict):
        self.chromosomes_json = json.dumps(value) if value else "{}"

    @hybrid_property
    def chromosome_performance(self) -> dict:
        if self.chromosome_perf_json:
            try:
                return json.loads(self.chromosome_perf_json)
            except (json.JSONDecodeError, TypeError):
                logger.warning("Corrupted chromosome_perf_json for genome %s", self.id)
        return {}

    @chromosome_performance.setter
    def chromosome_performance(self, value: dict):
        self.chromosome_perf_json = json.dumps(value) if value else "{}"


class ShadowTrade(Base):
    """Shadow trades for strategy validation without real capital."""

    __tablename__ = "shadow_trade"

    id = Column(Integer, primary_key=True, index=True)
    genome_id = Column(
        String,
        ForeignKey("genome_registry.genome_id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    strategy_name = Column(String, index=True)
    market_id = Column(String, index=True)
    _market_ticker = Column("market_ticker", String, index=True)
    entry_price = Column(Float)
    target_price = Column(Float, nullable=True)
    direction = Column(String)  # 'up' or 'down'
    size_usd = Column(Float)
    leverage = Column(Float, nullable=True, default=1.0)
    entry_signal = Column(String, nullable=True)
    exit_signal = Column(String, nullable=True)
    stage = Column(String, default="ACTIVE")  # ACTIVE, SETTLED, CANCELLED
    outcome = Column(String, nullable=True)  # 'win', 'loss', null until settled
    pnl_usd = Column(Float, nullable=True)
    created_at = Column(
        DateTime, default=lambda: datetime.now(timezone.utc), index=True
    )
    updated_at = Column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
    metadata_json = Column(Text, nullable=True)

    # Backward-compat aliases for legacy test code

    # Helper to update key-value in metadata_json
    def _update_metadata(self, key: str, value):
        try:
            meta = json.loads(self.metadata_json) if self.metadata_json else {}
        except ImportError:
            meta = {}
        meta[key] = value
        self.metadata_json = json.dumps(meta)

    @hybrid_property
    def size(self) -> float:
        return self.size_usd

    @size.setter
    def size(self, value: float):
        self.size_usd = value

    @size.expression
    def size(cls):
        return cls.size_usd

    @hybrid_property
    def settled(self) -> bool:
        return self.stage == "SETTLED"

    @settled.setter
    def settled(self, value: bool):
        self.stage = "SETTLED" if value else "ACTIVE"

    @settled.expression
    def settled(cls):
        return cls.stage == "SETTLED"

    @hybrid_property
    def settlement_value(self) -> Optional[float]:
        return (
            1.0 if self.outcome == "win" else (0.0 if self.outcome == "loss" else None)
        )

    @settlement_value.setter
    def settlement_value(self, value: Optional[float]):
        if value == 1.0:
            self.outcome = "win"
        elif value == 0.0:
            self.outcome = "loss"
        else:
            self.outcome = None

    @settlement_value.expression
    def settlement_value(cls):
        from sqlalchemy import case

        return case(
            (cls.outcome == "win", 1.0), (cls.outcome == "loss", 0.0), else_=None
        )

    @hybrid_property
    def pnl(self) -> Optional[float]:
        return self.pnl_usd

    @pnl.setter
    def pnl(self, value: Optional[float]):
        self.pnl_usd = value

    @pnl.expression
    def pnl(cls):
        return cls.pnl_usd

    @hybrid_property
    def strategy(self) -> str:
        return self.strategy_name

    @strategy.setter
    def strategy(self, value: str):
        self.strategy_name = value

    @strategy.expression
    def strategy(cls):
        return cls.strategy_name

    @hybrid_property
    def timestamp(self) -> datetime:
        return self.created_at

    @timestamp.setter
    def timestamp(self, value: datetime):
        self.created_at = value

    @timestamp.expression
    def timestamp(cls):
        return cls.created_at

    @hybrid_property
    def market_ticker(self) -> str:
        """Legacy market_ticker — falls back to market_id when column is NULL."""
        return self._market_ticker or self.market_id

    @market_ticker.setter
    def market_ticker(self, value: str):
        self._market_ticker = value

    @market_ticker.expression
    def market_ticker(cls):
        from sqlalchemy import case

        return case(
            (cls._market_ticker.is_(None), cls.market_id), else_=cls._market_ticker
        )

    @property
    def model_probability(self) -> Optional[float]:
        if self.metadata_json:
            try:
                meta = json.loads(self.metadata_json)
                return meta.get("model_probability")
            except (json.JSONDecodeError, TypeError):
                logger.warning(
                    "database: failed to parse metadata_json for model_probability"
                )
        return None

    @model_probability.setter
    def model_probability(self, value: Optional[float]):
        self._update_metadata("model_probability", value)

    @property
    def predicted_outcome(self) -> Optional[float]:
        if self.metadata_json:
            try:
                meta = json.loads(self.metadata_json)
                return meta.get("predicted_outcome")
            except (json.JSONDecodeError, TypeError):
                logger.warning(
                    "database: failed to parse metadata_json for model_probability"
                )
        return None

    @predicted_outcome.setter
    def predicted_outcome(self, value: Optional[float]):
        self._update_metadata("predicted_outcome", value)

    @property
    def actual_outcome(self) -> Optional[float]:
        if self.metadata_json:
            try:
                meta = json.loads(self.metadata_json)
                return meta.get("actual_outcome")
            except (json.JSONDecodeError, TypeError):
                logger.warning(
                    "database: failed to parse metadata_json for model_probability"
                )
        return None

    @actual_outcome.setter
    def actual_outcome(self, value: Optional[float]):
        self._update_metadata("actual_outcome", value)

    @property
    def accuracy_score(self) -> Optional[float]:
        if self.metadata_json:
            try:
                meta = json.loads(self.metadata_json)
                val = meta.get("accuracy_score")
                if val is not None:
                    return val
            except (json.JSONDecodeError, TypeError):
                logger.warning(
                    "database: failed to parse metadata_json for model_probability"
                )
        # Fallback: compute from predicted and actual outcome
        pred = self.predicted_outcome
        actual = self.actual_outcome
        if pred is not None and actual is not None:
            return abs(pred - actual)
        return None

    @accuracy_score.setter
    def accuracy_score(self, value: Optional[float]):
        self._update_metadata("accuracy_score", value)



class StrategyConfig(Base):
    __tablename__ = "strategy_config"
    id = Column(Integer, primary_key=True, index=True)
    strategy_name = Column(String, nullable=False, unique=True, index=True)
    enabled = Column(Boolean, default=False)
    params = Column(Text, nullable=True)  # JSON string
    interval_seconds = Column(Integer, default=60)
    trading_mode = Column(
        String, nullable=True
    )  # "paper", "testnet", "live" - overrides global TRADING_MODE
    mode = Column(
        String, nullable=True, default=None
    )  # "paper", "testnet", "live" - NULL = applies to all modes
    time_horizon = Column(
        String, nullable=True, default="mid"
    )  # "short", "mid", "long"
    risk_tier = Column(
        String, nullable=True, default="moderate"
    )  # "safe", "conservative", "moderate", "aggressive", "extreme", "crazy"
    protected = Column(
        Boolean, default=False
    )  # if True, strategy is exempt from auto-disable and scheduled for all modes
    disabled_at = Column(DateTime, nullable=True, default=None)
    rehab_allocation_pct = Column(
        Float, nullable=True, default=None
    )  # graduated rehab: 25→50→75→100
    updated_at = Column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )



class StrategyProposal(Base):
    """Proposed strategy changes awaiting admin approval."""

    __tablename__ = "strategy_proposal"

    id = Column(Integer, primary_key=True, index=True)
    strategy_name = Column(String(100), nullable=False, index=True)
    change_details = Column(JSON, nullable=False)
    expected_impact = Column(String(1000), nullable=False)
    admin_decision = Column(String(20), default="pending")
    status = Column(String(20), default="pending")
    auto_promotable = Column(Boolean, default=False)
    proposed_params = Column(JSON, nullable=True)
    backtest_passed = Column(Boolean, default=False)
    backtest_sharpe = Column(Float, nullable=True)
    backtest_win_rate = Column(Float, nullable=True)
    executed_at = Column(DateTime, nullable=True)
    impact_measured = Column(JSON, nullable=True)
    created_at = Column(
        DateTime, default=lambda: datetime.now(timezone.utc), index=True
    )
    admin_user_id = Column(String(100), nullable=True)
    admin_decision_reason = Column(Text, nullable=True)


class MiroFishSignal(Base):
    """AI-generated signals from Miro Fish debate engine for prediction markets."""

    __tablename__ = "mirofish_signal"

    id = Column(Integer, primary_key=True, index=True)
    market_id = Column(String(256), nullable=False, index=True, unique=True)
    prediction = Column(Float, nullable=False)  # 0.0-1.0
    confidence = Column(Float, nullable=False)  # 0.0-1.0
    reasoning = Column(Text, nullable=False)
    source = Column(String(50), default="mirofish", nullable=False)
    weight = Column(Float, default=1.0, nullable=False)  # Weight in debate engine
    created_at = Column(
        DateTime, default=lambda: datetime.now(timezone.utc), index=True
    )
    updated_at = Column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


class PerformanceMetric(Base):
    """Performance metrics for request timing, database queries, WebSocket latency, and system resources."""

    __tablename__ = "performance_metrics"

    id = Column(Integer, primary_key=True, index=True)
    timestamp = Column(
        DateTime, default=lambda: datetime.now(timezone.utc), index=True, nullable=False
    )
    metric_type = Column(String, nullable=False, index=True)
    endpoint = Column(String, nullable=True, index=True)
    method = Column(String, nullable=True)
    status_code = Column(Integer, nullable=True)
    duration_ms = Column(Float, nullable=True)
    query_type = Column(String, nullable=True)
    query_duration_ms = Column(Float, nullable=True)
    ws_message_type = Column(String, nullable=True)
    ws_latency_ms = Column(Float, nullable=True)
    memory_usage_mb = Column(Float, nullable=True)
    memory_percent = Column(Float, nullable=True)
    cpu_percent = Column(Float, nullable=True)
    user_agent = Column(String, nullable=True)
    error_message = Column(String, nullable=True)

    __table_args__ = (
        Index("idx_metrics_type_timestamp", "metric_type", "timestamp"),
        Index("idx_metrics_endpoint_timestamp", "endpoint", "timestamp"),
    )


class EvolutionLog(Base):
    """Log of genome evolution events and stage transitions."""

    __tablename__ = "evolution_log"

    id = Column(Integer, primary_key=True, index=True)
    genome_id = Column(String, ForeignKey("genome_registry.genome_id"), index=True)
    event_type = Column(
        String, index=True
    )  # promotion, mutation, crossover, auto_killed, etc.
    from_stage = Column(String, nullable=True)  # Source stage
    to_stage = Column(String, nullable=True)  # Target stage
    data = Column(JSON, default=lambda: {})  # Additional event data
    timestamp = Column(DateTime, default=lambda: datetime.now(timezone.utc), index=True)

    # Relationships
    genome = relationship("GenomeRegistry", back_populates="evolution_logs")



class Experiment(Base):
    """Track parameter experiments for each strategy."""

    __tablename__ = "experiments"
    id = Column(Integer, primary_key=True, index=True)
    strategy_name = Column(
        String,
        ForeignKey("strategy_config.strategy_name", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    params_json = Column(JSON, nullable=False)
    metrics_json = Column(JSON, nullable=True)
    status = Column(String, default="candidate")  # candidate|active|retired
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    promoted_at = Column(DateTime, nullable=True)
    notes = Column(String, nullable=True)

