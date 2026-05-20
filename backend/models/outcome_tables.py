from datetime import datetime, timezone
from sqlalchemy import (
    Column,
    String,
    Float,
    Boolean,
    Integer,
    DateTime,
    Text,
    ForeignKey,
    JSON,
    Index,
)
from backend.models.database import Base


class StrategyOutcome(Base):
    __tablename__ = "strategy_outcomes"

    id = Column(Integer, primary_key=True)
    strategy = Column(String, nullable=False)
    market_ticker = Column(String, nullable=False)
    market_type = Column(String, nullable=False)
    trading_mode = Column(String, nullable=False)
    direction = Column(String, nullable=False)
    model_probability = Column(Float, nullable=True)
    market_price = Column(Float, nullable=True)
    edge_at_entry = Column(Float, nullable=True)
    confidence = Column(Float, nullable=True)
    result = Column(String, nullable=True)
    pnl = Column(Float, nullable=True)
    reward = Column(Float, nullable=True)
    settled_at = Column(DateTime, nullable=True)
    trade_id = Column(Integer, ForeignKey("trades.id"), nullable=False)


class ParamChange(Base):
    __tablename__ = "param_changes"

    id = Column(Integer, primary_key=True)
    strategy = Column(String, nullable=False)
    param_name = Column(String, nullable=False)
    old_value = Column(Float, nullable=True)
    new_value = Column(Float, nullable=True)
    change_pct = Column(Float, nullable=True)
    confidence = Column(Float, nullable=True)
    reasoning = Column(Text, nullable=True)
    applied_at = Column(
        DateTime, nullable=False, default=lambda: datetime.now(timezone.utc)
    )
    reverted_at = Column(DateTime, nullable=True)
    pre_change_sharpe = Column(Float, nullable=True)
    post_change_sharpe = Column(Float, nullable=True)
    auto_applied = Column(Boolean, nullable=False, default=False)


class StrategyHealthRecord(Base):
    __tablename__ = "strategy_health"

    id = Column(Integer, primary_key=True)
    strategy = Column(String, nullable=False)
    total_trades = Column(Integer, nullable=False, default=0)
    wins = Column(Integer, nullable=False, default=0)
    losses = Column(Integer, nullable=False, default=0)
    win_rate = Column(Float, nullable=False, default=0.0)
    sharpe = Column(Float, nullable=False, default=0.0)
    max_drawdown = Column(Float, nullable=True)
    brier_score = Column(Float, nullable=True)
    psi_score = Column(Float, nullable=True)
    status = Column(String, nullable=False, default="active")
    last_updated = Column(
        DateTime, nullable=False, default=lambda: datetime.now(timezone.utc)
    )


class TradingCalibrationRecord(Base):
    __tablename__ = "trading_calibration_records"

    id = Column(Integer, primary_key=True)
    strategy = Column(String, nullable=False)
    predicted_prob = Column(Float, nullable=False)
    actual_outcome = Column(Integer, nullable=False)
    brier_score = Column(Float, nullable=True)
    market_type = Column(String, nullable=False, default="unknown")
    timestamp = Column(
        DateTime, nullable=False, default=lambda: datetime.now(timezone.utc)
    )


class ProposalFeedback(Base):
    """Tracks whether applied proposals actually improved performance."""

    __tablename__ = "proposal_feedback"
    __table_args__ = (
        Index("ix_feedback_strategy", "strategy"),
        Index("ix_feedback_proposal", "proposal_id"),
    )

    id = Column(Integer, primary_key=True)
    proposal_id = Column(Integer, ForeignKey("strategy_proposal.id"), nullable=False)
    strategy = Column(String, nullable=False)
    change_type = Column(String, nullable=False, default="parameter_adjustment")
    params_changed = Column(JSON, nullable=True)
    pre_wr = Column(Float, nullable=True)
    pre_sharpe = Column(Float, nullable=True)
    pre_pnl = Column(Float, nullable=True)
    post_wr = Column(Float, nullable=True)
    post_sharpe = Column(Float, nullable=True)
    post_pnl = Column(Float, nullable=True)
    improved = Column(Boolean, nullable=True)
    reverted = Column(Boolean, default=False)
    applied_at = Column(
        DateTime, nullable=False, default=lambda: datetime.now(timezone.utc)
    )
    measured_at = Column(DateTime, nullable=True)
    measurement_trades = Column(Integer, default=0)


class EvolutionLineage(Base):
    """Tracks parent→child relationships between strategy variants."""

    __tablename__ = "evolution_lineage"
    __table_args__ = (
        Index("ix_lineage_child", "child_experiment_id"),
        Index("ix_lineage_parent", "parent_experiment_id"),
    )

    id = Column(Integer, primary_key=True)
    parent_experiment_id = Column(
        Integer, ForeignKey("experiment_records.id"), nullable=True
    )
    child_experiment_id = Column(
        Integer, ForeignKey("experiment_records.id"), nullable=False
    )
    strategy_name = Column(String, nullable=False)
    generation = Column(Integer, default=1)
    mutation_type = Column(String, nullable=False, default="perturbation")
    parent_fitness = Column(Float, nullable=True)
    child_fitness = Column(Float, nullable=True)
    params_diff = Column(JSON, nullable=True)
    created_at = Column(
        DateTime, nullable=False, default=lambda: datetime.now(timezone.utc)
    )


class MetaLearningRecord(Base):
    """Aggregated learnings about what types of changes improve which strategies."""

    __tablename__ = "meta_learning"
    __table_args__ = (
        Index("ix_meta_param", "param_name"),
        Index("ix_meta_strategy", "strategy"),
    )

    id = Column(Integer, primary_key=True)
    strategy = Column(String, nullable=False)
    param_name = Column(String, nullable=False)
    change_direction = Column(String, nullable=False)
    sample_size = Column(Integer, default=0)
    success_count = Column(Integer, default=0)
    avg_improvement = Column(Float, default=0.0)
    avg_wr_delta = Column(Float, default=0.0)
    avg_sharpe_delta = Column(Float, default=0.0)
    last_updated = Column(
        DateTime, nullable=False, default=lambda: datetime.now(timezone.utc)
    )


class BlockedSignalCounterfactual(Base):
    __tablename__ = "blocked_signal_counterfactual"
    __table_args__ = (
        Index("ix_bsc_strategy", "strategy"),
        Index("ix_bsc_block_reason", "block_reason_code"),
        Index("ix_bsc_market", "market_ticker"),
        Index("ix_bsc_scored", "scored"),
    )

    id = Column(Integer, primary_key=True)
    source_table = Column(String, nullable=False)  # "trade_attempt" | "decision_log"
    source_id = Column(Integer, nullable=False)
    strategy = Column(String, nullable=False, index=True)
    market_ticker = Column(String, nullable=False)
    direction = Column(String, nullable=True)  # "up"|"down"|"yes"|"no"
    confidence = Column(Float, nullable=True)
    edge = Column(Float, nullable=True)
    model_probability = Column(Float, nullable=True)
    market_price = Column(Float, nullable=True)
    requested_size = Column(Float, nullable=True)
    entry_price = Column(Float, nullable=True)
    block_reason = Column(Text, nullable=True)
    block_reason_code = Column(String, nullable=True)
    block_phase = Column(
        String, nullable=True
    )  # "preflight"|"risk_gate"|"sizing"|"context"
    scored = Column(Boolean, default=False, index=True)
    actual_outcome = Column(String, nullable=True)  # "up"|"down"|"yes"|"no"
    settlement_value = Column(Float, nullable=True)  # 1.0 or 0.0
    would_have_won = Column(Boolean, nullable=True)
    hypothetical_pnl = Column(Float, nullable=True)
    resolution_source = Column(
        String, nullable=True
    )  # "market_outcome"|"gamma_api"|"signal_calibration"
    resolved_at = Column(DateTime, nullable=True)
    signal_blocked_at = Column(
        DateTime, nullable=False, default=lambda: datetime.now(timezone.utc)
    )
    scored_at = Column(DateTime, nullable=True)


class CounterfactualInsight(Base):
    __tablename__ = "counterfactual_insights"
    __table_args__ = (Index("ix_ci_dimension", "dimension", "dimension_value"),)

    id = Column(Integer, primary_key=True)
    dimension = Column(
        String, nullable=False
    )  # "strategy"|"block_reason"|"edge_range"|"confidence_range"
    dimension_value = Column(
        String, nullable=False
    )  # e.g. "btc_oracle", "RISK_REJECTED_LOW_CONFIDENCE"
    total_blocked = Column(Integer, default=0)
    total_would_win = Column(Integer, default=0)
    total_would_lose = Column(Integer, default=0)
    counterfactual_wr = Column(Float, default=0.0)
    hypothetical_total_pnl = Column(Float, default=0.0)
    lost_profit = Column(Float, default=0.0)
    sample_period_start = Column(DateTime, nullable=True)
    sample_period_end = Column(DateTime, nullable=True)
    computed_at = Column(
        DateTime, nullable=False, default=lambda: datetime.now(timezone.utc)
    )
