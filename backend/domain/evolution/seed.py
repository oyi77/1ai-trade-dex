import random
from typing import List
from backend.domain.genome.models import (
    StrategyGenome, LineageData, PerceptionChromosome,
    CognitionChromosome, EntryLogic, EntryCondition, ExitLogic,
    MarketSelector, ExecutionChromosome, RiskChromosome, MetaChromosome
)

# Founding archetypes with their key traits
FOUNDING_ARCHETYPES = [
    # name                  archetype                   key traits
    ("Arbitrage Hunter",    "arbitrage_hunter",         {"order_type": "post_only", "atomic_multi_leg": True}),
    ("Momentum Surfer",     "momentum_surfer",          {"timeframes": ["1m","5m"], "trigger_type": "momentum_breakout"}),
    ("Weather Oracle",      "weather_oracle",           {"data_sources": ["open_meteo"], "signal_aggregation": "bayesian_fusion"}),
    ("News Catalyst",       "news_catalyst",            {"data_sources": ["news_feed","social_sentiment"], "trigger_type": "event_driven"}),
    ("Whale Mirror",        "whale_mirror",             {"data_sources": ["polymarket_clob"], "feature_extractors": ["whale_position_delta"]}),
    ("Market Maker",        "market_maker",             {"order_type": "post_only", "trigger_type": "statistical_arbitrage"}),
    ("Statistical Arb",     "statistical_arb",          {"trigger_type": "statistical_arbitrage", "signal_aggregation": "bayesian_fusion"}),
    ("Event Catalyst",      "event_catalyst",           {"trigger_type": "event_driven", "exit_trigger": "spread_convergence"}),
    ("Flash Opportunity",   "flash_opportunity",        {"execution_speed_target_ms": 50, "order_type": "fok"}),
]

# Diversity injection: 20% of each genome's numeric genes are randomized within safe bounds
DIVERSITY_FACTOR = 0.20


def inject_diversity(value: float, diversity_factor: float = DIVERSITY_FACTOR) -> float:
    """Add random variation to a numeric gene within safe bounds."""
    if random.random() < diversity_factor:
        variation = random.uniform(-0.2, 0.2)  # ±20%
        return max(0.0, value * (1 + variation))
    return value


def create_base_perception(archetype: str, traits: dict) -> PerceptionChromosome:
    """Create perception chromosome with archetype-specific traits."""
    base = PerceptionChromosome()

    if "data_sources" in traits:
        base.data_sources = traits["data_sources"]
    if "feature_extractors" in traits:
        base.feature_extractors = traits["feature_extractors"]
    if "timeframes" in traits:
        base.timeframes = traits["timeframes"]
    if "signal_aggregation" in traits:
        base.signal_aggregation = traits["signal_aggregation"]

    return base


def create_base_cognition(archetype: str, traits: dict) -> CognitionChromosome:
    """Create cognition chromosome with archetype-specific traits."""
    trigger_type = traits.get("trigger_type", "threshold_cross")
    exit_trigger = traits.get("exit_trigger", "profit_target")

    entry_logic = EntryLogic(
        trigger_type=trigger_type,
        conditions=[EntryCondition(
            indicator="rsi" if archetype == "momentum_surfer" else "orderbook_imbalance",
            operator=">" if archetype == "momentum_surfer" else "crosses_above",
            value=70.0 if archetype == "momentum_surfer" else 0.5
        )],
        min_confidence=inject_diversity(0.5)
    )

    exit_logic = ExitLogic(
        trigger_type=exit_trigger,
        profit_target_pct=inject_diversity(0.15),
        stop_loss_pct=inject_diversity(0.08)
    )

    market_selector = MarketSelector(
        criteria=["high_volume"] if archetype == "market_maker" else ["high_volume", "short_settlement"],
        max_concurrent_positions=5 if archetype == "arbitrage_hunter" else 3
    )

    return CognitionChromosome(
        entry_logic=entry_logic,
        exit_logic=exit_logic,
        market_selector=market_selector
    )


def create_base_execution(archetype: str, traits: dict) -> ExecutionChromosome:
    """Create execution chromosome with archetype-specific traits."""
    base = ExecutionChromosome()

    if "order_type" in traits:
        base.order_type = traits["order_type"]
    if "execution_speed_target_ms" in traits:
        base.execution_speed_target_ms = traits["execution_speed_target_ms"]
    if "atomic_multi_leg" in traits:
        base.atomic_multi_leg = traits["atomic_multi_leg"]

    base.slippage_tolerance = inject_diversity(0.02)

    return base


def create_base_risk(archetype: str, traits: dict) -> RiskChromosome:
    """Create risk chromosome with archetype-specific traits."""
    base = RiskChromosome()

    if archetype in ["flash_opportunity", "momentum_surfer"]:
        base.position_sizing_model = "volatility_targeted"
        base.max_position_fraction = inject_diversity(0.12)
    elif archetype == "market_maker":
        base.position_sizing_model = "fixed_fraction"
        base.max_position_fraction = inject_diversity(0.05)
    else:
        base.max_position_fraction = inject_diversity(0.08)

    base.kelly_fraction = inject_diversity(0.30)
    base.max_total_exposure_fraction = inject_diversity(0.70)

    return base


def create_base_meta(archetype: str, traits: dict) -> MetaChromosome:
    """Create meta chromosome with archetype-specific traits."""
    base = MetaChromosome()

    if archetype in ["weather_oracle", "news_catalyst", "event_catalyst"]:
        base.adaptation_speed = "aggressive"
        base.hyperparameter_tuning_frequency = "hourly"
    elif archetype == "market_maker":
        base.adaptation_speed = "conservative"
        base.hyperparameter_tuning_frequency = "weekly"

    base.mutation_rate = inject_diversity(0.15)

    return base


def seed_initial_population() -> List[StrategyGenome]:
    """
    Generate the founding population of 9 archetypal genomes.
    Each has lineage.creator = "synthesis" and stage = "DRAFT".
    """
    genomes = []

    for name, archetype, traits in FOUNDING_ARCHETYPES:
        genome = StrategyGenome(
            strategy_name=name,
            archetype=archetype,
            stage="DRAFT",
            lineage=LineageData(
                parent_genome_ids=[],
                generation=1,
                creator="synthesis"
            ),
            chromosomes={
                "perception": create_base_perception(archetype, traits),
                "cognition": create_base_cognition(archetype, traits),
                "execution": create_base_execution(archetype, traits),
                "risk": create_base_risk(archetype, traits),
                "meta": create_base_meta(archetype, traits)
            }
        )
        genomes.append(genome)

    return genomes
