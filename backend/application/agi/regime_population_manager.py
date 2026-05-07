"""Regime Detection → Population Rebalancing.

Wave 9: Meta-Learning Layer — Part 5.4
Fixes Gap G2 by dynamically adjusting strategy allocations based on market regime.
"""

from typing import Dict, Any

from backend.core.event_bus import publish_event
from backend.core.regime_detector import RegimeDetector


# Strategy preferences by regime
REGIME_STRATEGY_PREFERENCES: Dict[str, Dict[str, Any]] = {
    "volatile": {
        "boost": ["statistical_arb", "market_maker", "arbitrage_hunter"],
        "suppress": ["momentum_surfer", "event_catalyst"],
        "risk_target": "conservative"
    },
    "trending": {
        "boost": ["momentum_surfer", "whale_mirror"],
        "suppress": ["statistical_arb"],
        "risk_target": "moderate"
    },
    "event_dense": {
        "boost": ["news_catalyst", "event_catalyst", "flash_opportunity"],
        "suppress": ["weather_oracle"],
        "risk_target": "moderate"
    },
    "sideways": {
        "boost": ["market_maker", "statistical_arb"],
        "suppress": ["momentum_surfer"],
        "risk_target": "conservative"
    }
}


def get_rolling_volatility(days: int) -> float:
    """Get rolling volatility (simplified placeholder)."""
    return 0.02


def get_trend_strength() -> float:
    """Get trend strength (simplified placeholder)."""
    return 0.5


def get_volume_profile() -> Dict[str, float]:
    """Get volume profile (simplified placeholder)."""
    return {"volume": 1.0, "trend": 0.0}


def get_cross_platform_spreads() -> Dict[str, float]:
    """Get cross-platform spreads (simplified placeholder)."""
    return {"spread": 0.001}


def get_news_sentiment_variance() -> float:
    """Get news sentiment variance (simplified placeholder)."""
    return 0.1


def get_last_regime(db) -> str:
    """Get last detected regime from database."""
    # Simplified: in production, query RegimeLog table
    return "neutral"


def save_regime(regime: str, db) -> None:
    """Save current regime to database."""
    # Simplified: in production, insert into RegimeLog table
    pass


def regime_changed(new_regime: str, db) -> bool:
    """Check if regime has changed from last saved regime."""
    last = get_last_regime(db)
    return new_regime != last


def increase_archetype_allocation(archetype: str, factor: float, db) -> None:
    """Increase capital allocation for an archetype."""
    # Simplified: in production, update ArchetypeAllocation table
    publish_event("archetype_allocation_changed", {
        "archetype": archetype,
        "factor": factor,
        "action": "boost"
    })


def decrease_archetype_allocation(archetype: str, factor: float, db) -> None:
    """Decrease capital allocation for an archetype."""
    # Simplified: in production, update ArchetypeAllocation table
    publish_event("archetype_allocation_changed", {
        "archetype": archetype,
        "factor": factor,
        "action": "suppress"
    })


def get_live_genomes(db) -> list:
    """Get all live genomes."""
    # Simplified: in production, query GenomeRegistry for LIVE stage
    return []


def detect_regime_and_rebalance(db) -> str:
    """Detect current market regime and rebalance strategy allocations.

    Analyzes market conditions to determine regime, then adjusts capital
    allocation weights for strategy archetypes based on regime preferences.

    Args:
        db: Database session

    Returns:
        Detected regime name
    """
    # Detect current regime
    regime = RegimeDetector().detect_regime({
        "volatility_30d": get_rolling_volatility(30),
        "trend_strength": get_trend_strength(),
        "volume_profile": get_volume_profile(),
        "spread_distribution": get_cross_platform_spreads(),
        "news_variance": get_news_sentiment_variance()
    }).regime.value if hasattr(RegimeDetector(), 'detect_regime') else "neutral"

    # Check if regime changed
    if regime_changed(regime, db):
        # Get preferences for this regime
        prefs = REGIME_STRATEGY_PREFERENCES.get(regime, {})

        # Adjust capital allocation weights
        for archetype in prefs.get("boost", []):
            increase_archetype_allocation(archetype, factor=1.50, db=db)

        for archetype in prefs.get("suppress", []):
            decrease_archetype_allocation(archetype, factor=0.50, db=db)

        # Trigger mutation with risk-chromosome target
        for genome in get_live_genomes(db):
            if "meta" not in genome.chromosomes:
                genome.chromosomes["meta"] = {}
            genome.chromosomes["meta"]["next_mutation_target"] = "risk_chromosome"

        # Publish regime shift event
        publish_event("regime_shift", {
            "from": get_last_regime(db),
            "to": regime
        })

        # Save new regime
        save_regime(regime, db)

    return regime
