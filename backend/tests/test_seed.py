import pytest
from backend.domain.evolution.seed import seed_initial_population, FOUNDING_ARCHETYPES
from backend.domain.genome.models import StrategyGenome


def test_founding_archetypes_count():
    """Test that we have exactly 9 founding archetypes."""
    assert len(FOUNDING_ARCHETYPES) == 9


def test_seed_initial_population_count():
    """Test that seed function generates 9 genomes."""
    genomes = seed_initial_population()
    assert len(genomes) == 9


def test_seed_genome_properties():
    """Test properties of seeded genomes."""
    genomes = seed_initial_population()
    
    for genome in genomes:
        # All should be StrategyGenome instances
        assert isinstance(genome, StrategyGenome)
        
        # All should be DRAFT stage
        assert genome.stage == "DRAFT"
        
        # All should have synthesis creator
        assert genome.lineage.creator == "synthesis"
        
        # All should be generation 1
        assert genome.lineage.generation == 1
        
        # All should have no parents
        assert len(genome.lineage.parent_genome_ids) == 0
        
        # All should have 5 chromosomes
        assert len(genome.chromosomes) == 5
        assert "perception" in genome.chromosomes
        assert "cognition" in genome.chromosomes
        assert "execution" in genome.chromosomes
        assert "risk" in genome.chromosomes
        assert "meta" in genome.chromosomes


def test_archetype_names():
    """Test that all expected archetype names are present."""
    genomes = seed_initial_population()
    archetype_names = [genome.strategy_name for genome in genomes]
    expected_names = [
        "Arbitrage Hunter", "Momentum Surfer", "Weather Oracle", 
        "News Catalyst", "Whale Mirror", "Market Maker", 
        "Statistical Arb", "Event Catalyst", "Flash Opportunity"
    ]
    
    for expected_name in expected_names:
        assert expected_name in archetype_names


def test_archetype_types():
    """Test that all expected archetype types are present."""
    genomes = seed_initial_population()
    archetype_types = [genome.archetype for genome in genomes]
    expected_types = [
        "arbitrage_hunter", "momentum_surfer", "weather_oracle", 
        "news_catalyst", "whale_mirror", "market_maker", 
        "statistical_arb", "event_catalyst", "flash_opportunity"
    ]
    
    for expected_type in expected_types:
        assert expected_type in archetype_types


def test_archetype_specific_traits():
    """Test that specific archetypes have expected traits."""
    genomes = seed_initial_population()
    
    # Find specific archetypes and test their traits
    arbitrage_hunter = next(g for g in genomes if g.archetype == "arbitrage_hunter")
    assert arbitrage_hunter.chromosomes["execution"].order_type == "post_only"
    assert arbitrage_hunter.chromosomes["execution"].atomic_multi_leg is True
    
    momentum_surfer = next(g for g in genomes if g.archetype == "momentum_surfer")
    assert "1m" in momentum_surfer.chromosomes["perception"].timeframes
    assert "5m" in momentum_surfer.chromosomes["perception"].timeframes
    assert momentum_surfer.chromosomes["cognition"].entry_logic.trigger_type == "momentum_breakout"
    
    weather_oracle = next(g for g in genomes if g.archetype == "weather_oracle")
    assert "open_meteo" in weather_oracle.chromosomes["perception"].data_sources
    assert weather_oracle.chromosomes["perception"].signal_aggregation == "bayesian_fusion"
    
    flash_opportunity = next(g for g in genomes if g.archetype == "flash_opportunity")
    assert flash_opportunity.chromosomes["execution"].execution_speed_target_ms == 50
    assert flash_opportunity.chromosomes["execution"].order_type == "fok"


def test_genome_ids_unique():
    """Test that all generated genomes have unique IDs."""
    genomes = seed_initial_population()
    genome_ids = [g.genome_id for g in genomes]
    assert len(genome_ids) == len(set(genome_ids))  # All unique


def test_diversity_injection():
    """Test that diversity injection produces variation across calls."""
    import random
    original_state = random.getstate()
    try:
        random.seed(42)
        pop1 = seed_initial_population()
        random.seed(99)
        pop2 = seed_initial_population()
        
        momo1 = next(g for g in pop1 if g.archetype == "momentum_surfer")
        momo2 = next(g for g in pop2 if g.archetype == "momentum_surfer")
        
        traits_differ = (
            momo1.chromosomes["execution"].slippage_tolerance != momo2.chromosomes["execution"].slippage_tolerance or
            momo1.chromosomes["risk"].kelly_fraction != momo2.chromosomes["risk"].kelly_fraction or
            momo1.chromosomes["meta"].mutation_rate != momo2.chromosomes["meta"].mutation_rate
        )
        
        assert traits_differ
    finally:
        random.setstate(original_state)