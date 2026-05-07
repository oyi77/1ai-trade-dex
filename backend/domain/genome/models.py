from pydantic import BaseModel, Field
from typing import Literal, Optional
from uuid import uuid4
from datetime import datetime
from dataclasses import dataclass

class LineageData(BaseModel):
    parent_genome_ids: list[str] = Field(default_factory=list)
    generation: int = 1
    birth_timestamp: datetime = Field(default_factory=datetime.utcnow)
    creator: Literal["human", "mutation", "crossover", "synthesis"] = "human"

class PerceptionChromosome(BaseModel):
    data_sources: list[str] = ["polymarket_clob"]
    feature_extractors: list[str] = ["price_velocity", "orderbook_imbalance"]
    timeframes: list[str] = ["5m", "15m"]
    signal_aggregation: Literal["weighted_average", "majority_vote", "bayesian_fusion"] = "weighted_average"

class EntryCondition(BaseModel):
    indicator: str
    operator: str
    value: float | list[float]
    weight: float = Field(ge=0.0, le=1.0, default=1.0)

class EntryLogic(BaseModel):
    trigger_type: Literal["threshold_cross", "pattern_match", "statistical_arbitrage", "event_driven", "momentum_breakout"]
    conditions: list[EntryCondition]
    conjunction: Literal["AND", "OR", "weighted_score"] = "AND"
    min_confidence: float = Field(ge=0.0, le=1.0, default=0.50)

class ExitLogic(BaseModel):
    trigger_type: Literal["time_based", "profit_target", "stop_loss", "trailing_stop", "market_resolution", "spread_convergence"]
    profit_target_pct: Optional[float] = None
    stop_loss_pct: Optional[float] = None
    max_hold_time_hours: float = 24.0

class MarketSelector(BaseModel):
    criteria: list[str] = ["high_volume", "short_settlement"]
    scoring_function: str = "weighted_composite_score"
    max_concurrent_positions: int = 5

class CognitionChromosome(BaseModel):
    entry_logic: EntryLogic
    exit_logic: ExitLogic
    market_selector: MarketSelector

class ExecutionChromosome(BaseModel):
    order_type: Literal["limit", "market", "fok", "ioc", "post_only"] = "limit"
    slippage_tolerance: float = Field(ge=0.0, le=0.05, default=0.02)
    execution_speed_target_ms: int = 500
    retry_logic: Literal["exponential_backoff", "immediate", "abandon"] = "exponential_backoff"
    atomic_multi_leg: bool = False

class RiskChromosome(BaseModel):
    position_sizing_model: Literal["kelly_fraction", "fixed_fraction", "volatility_targeted", "optimal_f"] = "kelly_fraction"
    kelly_fraction: float = Field(ge=0.05, le=0.50, default=0.30)
    max_position_fraction: float = Field(ge=0.01, le=0.25, default=0.08)
    max_total_exposure_fraction: float = Field(ge=0.30, le=0.95, default=0.70)
    daily_drawdown_limit_pct: float = 0.10
    weekly_drawdown_limit_pct: float = 0.20
    correlation_aware_sizing: bool = False

class MetaChromosome(BaseModel):
    self_optimization_enabled: bool = True
    hyperparameter_tuning_frequency: Literal["every_trade", "hourly", "daily", "weekly"] = "daily"
    adaptation_speed: Literal["conservative", "moderate", "aggressive"] = "moderate"
    crossover_eligibility: bool = True
    mutation_rate: float = Field(ge=0.01, le=0.50, default=0.10)
    next_mutation_target: Optional[str] = None

class FitnessMetrics(BaseModel):
    sharpe_ratio: float = 0.0
    win_rate: float = 0.0
    profit_factor: float = 0.0
    max_drawdown_pct: float = 0.0
    brier_score: float = 0.25
    alpha_per_trade: float = 0.0
    capital_rotation_efficiency: float = 0.0
    total_trades: int = 0
    last_evaluated: Optional[datetime] = None

@dataclass
class DeathCertificate:
    genome_id: str
    strategy_name: str
    reason: str
    final_metrics: dict
    kill_timestamp: datetime
    total_pnl: float
    total_trades: int
    regime_at_death: str
    killer_condition: str
    rehabilitation_eligible: bool

class StrategyGenome(BaseModel):
    genome_id: str = Field(default_factory=lambda: str(uuid4()))
    strategy_name: str
    archetype: str
    version: str = "1.0.0"
    stage: Literal["DRAFT", "SHADOW", "PAPER", "LIVE", "BREEDING", "LEGEND", "GRAVEYARD"] = "DRAFT"
    lineage: LineageData = Field(default_factory=LineageData)
    chromosomes: dict = Field(...)
    fitness_metrics: FitnessMetrics = Field(default_factory=FitnessMetrics)
    chromosome_performance_history: dict[str, list[float]] = Field(default_factory=dict)
    death_certificate: Optional[dict] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
