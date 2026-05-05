import pytest
from datetime import datetime
from backend.domain.genome.models import (
    LineageData, PerceptionChromosome, EntryCondition, EntryLogic, ExitLogic,
    MarketSelector, CognitionChromosome, ExecutionChromosome, RiskChromosome,
    MetaChromosome, FitnessMetrics, StrategyGenome, DeathCertificate
)


def test_lineage_data_creation():
    """Test LineageData model creation and validation."""
    lineage = LineageData(
        parent_genome_ids=["parent1", "parent2"],
        generation=2,
        creator="crossover"
    )
    assert lineage.parent_genome_ids == ["parent1", "parent2"]
    assert lineage.generation == 2
    assert lineage.creator == "crossover"
    assert isinstance(lineage.birth_timestamp, datetime)


def test_perception_chromosome_defaults():
    """Test PerceptionChromosome with default values."""
    chromo = PerceptionChromosome()
    assert chromo.data_sources == ["polymarket_clob"]
    assert chromo.feature_extractors == ["price_velocity", "orderbook_imbalance"]
    assert chromo.timeframes == ["5m", "15m"]
    assert chromo.signal_aggregation == "weighted_average"


def test_entry_condition_validation():
    """Test EntryCondition field validation."""
    # Valid condition
    condition = EntryCondition(
        indicator="rsi",
        operator=">",
        value=70.0,
        weight=0.8
    )
    assert condition.indicator == "rsi"
    assert condition.weight == 0.8

    # Test weight bounds
    with pytest.raises(ValueError):
        EntryCondition(indicator="test", operator=">", value=50.0, weight=1.5)  # > 1.0
    with pytest.raises(ValueError):
        EntryCondition(indicator="test", operator=">", value=50.0, weight=-0.1)  # < 0.0


def test_entry_logic_validation():
    """Test EntryLogic trigger types and conditions."""
    entry_logic = EntryLogic(
        trigger_type="momentum_breakout",
        conditions=[EntryCondition(indicator="rsi", operator=">", value=70.0)],
        conjunction="AND",
        min_confidence=0.6
    )
    assert entry_logic.trigger_type == "momentum_breakout"
    assert len(entry_logic.conditions) == 1


def test_exit_logic_validation():
    """Test ExitLogic trigger types."""
    exit_logic = ExitLogic(
        trigger_type="profit_target",
        profit_target_pct=0.20,
        stop_loss_pct=0.10
    )
    assert exit_logic.trigger_type == "profit_target"
    assert exit_logic.profit_target_pct == 0.20


def test_market_selector_defaults():
    """Test MarketSelector defaults."""
    selector = MarketSelector()
    assert selector.criteria == ["high_volume", "short_settlement"]
    assert selector.scoring_function == "weighted_composite_score"
    assert selector.max_concurrent_positions == 5


def test_cognition_chromosome_integration():
    """Test CognitionChromosome with all components."""
    cognition = CognitionChromosome(
        entry_logic=EntryLogic(
            trigger_type="threshold_cross",
            conditions=[EntryCondition(indicator="rsi", operator=">", value=70.0)]
        ),
        exit_logic=ExitLogic(trigger_type="profit_target"),
        market_selector=MarketSelector()
    )
    assert hasattr(cognition, "entry_logic")
    assert hasattr(cognition, "exit_logic")
    assert hasattr(cognition, "market_selector")


def test_execution_chromosome_validation():
    """Test ExecutionChromosome field constraints."""
    execution = ExecutionChromosome(
        order_type="limit",
        slippage_tolerance=0.03,
        execution_speed_target_ms=300
    )
    assert execution.order_type == "limit"
    assert execution.slippage_tolerance == 0.03

    # Test slippage tolerance bounds
    with pytest.raises(ValueError):
        ExecutionChromosome(slippage_tolerance=0.06)  # > 0.05
    with pytest.raises(ValueError):
        ExecutionChromosome(slippage_tolerance=-0.1)  # < 0.0


def test_risk_chromosome_validation():
    """Test RiskChromosome field constraints."""
    risk = RiskChromosome(
        position_sizing_model="kelly_fraction",
        kelly_fraction=0.25,
        max_position_fraction=0.10
    )
    assert risk.position_sizing_model == "kelly_fraction"

    # Test kelly fraction bounds
    with pytest.raises(ValueError):
        RiskChromosome(kelly_fraction=0.6)  # > 0.5
    with pytest.raises(ValueError):
        RiskChromosome(kelly_fraction=0.04)  # < 0.05


def test_meta_chromosome_defaults():
    """Test MetaChromosome defaults."""
    meta = MetaChromosome()
    assert meta.self_optimization_enabled is True
    assert meta.hyperparameter_tuning_frequency == "daily"
    assert meta.adaptation_speed == "moderate"
    assert meta.crossover_eligibility is True


def test_fitness_metrics_defaults():
    """Test FitnessMetrics defaults."""
    metrics = FitnessMetrics()
    assert metrics.sharpe_ratio == 0.0
    assert metrics.win_rate == 0.0
    assert metrics.brier_score == 0.25
    assert metrics.total_trades == 0
    assert metrics.last_evaluated is None


def test_strategy_genome_creation():
    """Test StrategyGenome with all components."""
    genome = StrategyGenome(
        strategy_name="Test Strategy",
        archetype="test_archetype",
        chromosomes={
            "perception": PerceptionChromosome(),
            "cognition": CognitionChromosome(
                entry_logic=EntryLogic(
                    trigger_type="threshold_cross",
                    conditions=[EntryCondition(indicator="rsi", operator=">", value=70.0)]
                ),
                exit_logic=ExitLogic(trigger_type="profit_target"),
                market_selector=MarketSelector()
            ),
            "execution": ExecutionChromosome(),
            "risk": RiskChromosome(),
            "meta": MetaChromosome()
        }
    )
    assert genome.strategy_name == "Test Strategy"
    assert genome.archetype == "test_archetype"
    assert genome.stage == "DRAFT"
    assert len(genome.chromosomes) == 5
    assert isinstance(genome.genome_id, str)
    assert len(genome.genome_id) > 0


def test_death_certificate_creation():
    """Test DeathCertificate dataclass."""
    cert = DeathCertificate(
        genome_id="test123",
        strategy_name="Failed Strategy",
        reason="auto_kill_drawdown",
        final_metrics={"sharpe_ratio": -2.0, "win_rate": 0.3},
        kill_timestamp=datetime.utcnow(),
        total_pnl=-1000.0,
        total_trades=50,
        regime_at_death="volatile",
        killer_condition="max_drawdown_pct > 0.50",
        rehabilitation_eligible=False
    )
    assert cert.genome_id == "test123"
    assert cert.reason == "auto_kill_drawdown"
    assert cert.rehabilitation_eligible is False