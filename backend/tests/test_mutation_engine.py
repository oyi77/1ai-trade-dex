from backend.domain.evolution.mutation_engine import (
    mutate_genome, tweak_random_numeric_gene, swap_indicator,
    shift_timeframe, reassign_risk_model, normalize
)
from backend.domain.genome.models import (
    StrategyGenome, PerceptionChromosome, CognitionChromosome,
    EntryLogic, EntryCondition, ExitLogic, MarketSelector,
    ExecutionChromosome, RiskChromosome, MetaChromosome
)


def test_normalize_function():
    """Test the normalize helper function."""
    assert normalize(0.5, 0, 1) == 0.5
    assert normalize(0, 0, 1) == 0.0
    assert normalize(1, 0, 1) == 1.0
    assert normalize(2, 0, 1) == 1.0  # Clamped
    assert normalize(-1, 0, 1) == 0.0  # Clamped


def test_tweak_random_numeric_gene():
    """Test tweaking a numeric gene."""
    # Create a minimal genome
    perception = PerceptionChromosome()
    cognition = CognitionChromosome(
        entry_logic=EntryLogic(
            trigger_type='threshold_cross',
            conditions=[EntryCondition(indicator='rsi', operator='>', value=70.0, weight=0.8)]
        ),
        exit_logic=ExitLogic(trigger_type='profit_target', profit_target_pct=0.1),
        market_selector=MarketSelector()
    )
    execution = ExecutionChromosome()
    risk = RiskChromosome()
    meta = MetaChromosome()

    genome = StrategyGenome(
        strategy_name='test',
        archetype='test',
        chromosomes={
            'perception': perception,
            'cognition': cognition,
            'execution': execution,
            'risk': risk,
            'meta': meta
        }
    )

    gene, new_value = tweak_random_numeric_gene(genome, sigma=0.1)
    assert gene != ""
    assert isinstance(new_value, (int, float))


def test_swap_indicator():
    """Test indicator swapping."""
    perception = PerceptionChromosome()
    cognition = CognitionChromosome(
        entry_logic=EntryLogic(
            trigger_type='threshold_cross',
            conditions=[EntryCondition(indicator='rsi', operator='>', value=70.0)]
        ),
        exit_logic=ExitLogic(trigger_type='profit_target'),
        market_selector=MarketSelector()
    )
    execution = ExecutionChromosome()
    risk = RiskChromosome()
    meta = MetaChromosome()

    genome = StrategyGenome(
        strategy_name='test',
        archetype='test',
        chromosomes={
            'perception': perception,
            'cognition': cognition,
            'execution': execution,
            'risk': risk,
            'meta': meta
        }
    )

    old, new = swap_indicator(genome, weighted_by_regime="trending")
    assert old != new
    assert old in ["rsi", "orderbook_imbalance"]


def test_shift_timeframe():
    """Test timeframe shifting."""
    perception = PerceptionChromosome(timeframes=["5m", "15m"])
    cognition = CognitionChromosome(
        entry_logic=EntryLogic(
            trigger_type='threshold_cross',
            conditions=[EntryCondition(indicator='rsi', operator='>', value=70.0)]
        ),
        exit_logic=ExitLogic(trigger_type='profit_target'),
        market_selector=MarketSelector()
    )
    execution = ExecutionChromosome()
    risk = RiskChromosome()
    meta = MetaChromosome()

    genome = StrategyGenome(
        strategy_name='test',
        archetype='test',
        chromosomes={
            'perception': perception,
            'cognition': cognition,
            'execution': execution,
            'risk': risk,
            'meta': meta
        }
    )

    old, new = shift_timeframe(genome, current_volatility=1.0)
    assert old in ["1m", "5m", "15m", "30m", "1h", "4h", "1d"]
    assert new in ["1m", "5m", "15m", "30m", "1h", "4h", "1d"]


def test_reassign_risk_model():
    """Test risk model reassignment."""
    perception = PerceptionChromosome()
    cognition = CognitionChromosome(
        entry_logic=EntryLogic(
            trigger_type='threshold_cross',
            conditions=[EntryCondition(indicator='rsi', operator='>', value=70.0)]
        ),
        exit_logic=ExitLogic(trigger_type='profit_target'),
        market_selector=MarketSelector()
    )
    execution = ExecutionChromosome()
    risk = RiskChromosome(position_sizing_model="kelly_fraction")
    meta = MetaChromosome()

    genome = StrategyGenome(
        strategy_name='test',
        archetype='test',
        chromosomes={
            'perception': perception,
            'cognition': cognition,
            'execution': execution,
            'risk': risk,
            'meta': meta
        }
    )

    old, new = reassign_risk_model(genome, drawdown_history=[0.1, 0.05])
    assert old in ["kelly_fraction", "fixed_fraction", "volatility_targeted", "optimal_f"]
    assert new in ["kelly_fraction", "fixed_fraction", "volatility_targeted", "optimal_f"]
    assert old != new


def test_mutate_genome_basic():
    """Test basic genome mutation."""
    perception = PerceptionChromosome()
    cognition = CognitionChromosome(
        entry_logic=EntryLogic(
            trigger_type='threshold_cross',
            conditions=[EntryCondition(indicator='rsi', operator='>', value=70.0)]
        ),
        exit_logic=ExitLogic(trigger_type='profit_target', profit_target_pct=0.1),
        market_selector=MarketSelector()
    )
    execution = ExecutionChromosome()
    risk = RiskChromosome()
    meta = MetaChromosome()

    genome = StrategyGenome(
        strategy_name='test',
        archetype='test',
        chromosomes={
            'perception': perception,
            'cognition': cognition,
            'execution': execution,
            'risk': risk,
            'meta': meta
        }
    )

    new_genome, mutations = mutate_genome(genome, 'neutral', 0.5)

    # Verify new genome properties
    assert new_genome.genome_id != genome.genome_id
    assert new_genome.stage == "DRAFT"
    assert new_genome.lineage.creator == "mutation"
    assert new_genome.lineage.generation == genome.lineage.generation + 1
    assert genome.genome_id in new_genome.lineage.parent_genome_ids


def test_mutate_genome_high_fitness():
    """Test mutation with high fitness score (lower mutation rate)."""
    perception = PerceptionChromosome()
    cognition = CognitionChromosome(
        entry_logic=EntryLogic(
            trigger_type='threshold_cross',
            conditions=[EntryCondition(indicator='rsi', operator='>', value=70.0)]
        ),
        exit_logic=ExitLogic(trigger_type='profit_target'),
        market_selector=MarketSelector()
    )
    execution = ExecutionChromosome()
    risk = RiskChromosome()
    meta = MetaChromosome(mutation_rate=0.20)

    genome = StrategyGenome(
        strategy_name='test',
        archetype='test',
        chromosomes={
            'perception': perception,
            'cognition': cognition,
            'execution': execution,
            'risk': risk,
            'meta': meta
        }
    )

    # High fitness should result in fewer mutations
    new_genome, mutations = mutate_genome(genome, 'neutral', 0.9)

    assert new_genome.stage == "DRAFT"
    assert new_genome.lineage.creator == "mutation"


def test_mutate_genome_low_fitness():
    """Test mutation with low fitness score (higher mutation rate)."""
    perception = PerceptionChromosome()
    cognition = CognitionChromosome(
        entry_logic=EntryLogic(
            trigger_type='threshold_cross',
            conditions=[EntryCondition(indicator='rsi', operator='>', value=70.0)]
        ),
        exit_logic=ExitLogic(trigger_type='profit_target'),
        market_selector=MarketSelector()
    )
    execution = ExecutionChromosome()
    risk = RiskChromosome()
    meta = MetaChromosome(mutation_rate=0.10)

    genome = StrategyGenome(
        strategy_name='test',
        archetype='test',
        chromosomes={
            'perception': perception,
            'cognition': cognition,
            'execution': execution,
            'risk': risk,
            'meta': meta
        }
    )

    # Low fitness should result in more mutations
    new_genome, mutations = mutate_genome(genome, 'neutral', 0.2)

    assert new_genome.stage == "DRAFT"
    assert new_genome.lineage.creator == "mutation"
