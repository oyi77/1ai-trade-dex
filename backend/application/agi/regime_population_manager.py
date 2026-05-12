"""Regime Detection -> Population Rebalancing.

Wave 9: Meta-Learning Layer -- Part 5.4
Fixes Gap G2 by dynamically adjusting strategy allocations based on market regime.
Uses real market data from BtcPriceSnapshot and genome data from GenomeRegistry.
"""

import json
from typing import Dict, Any, List
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from loguru import logger

from backend.core.event_bus import publish_event
from backend.core.regime_detector import RegimeDetector
from backend.models.database import BtcPriceSnapshot, GenomeRegistry


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


def _build_market_data(db: Session) -> dict:
    """Build market data dict for RegimeDetector from live price history."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=30)
    snapshots = (
        db.query(BtcPriceSnapshot)
        .filter(BtcPriceSnapshot.timestamp >= cutoff)
        .order_by(BtcPriceSnapshot.timestamp.asc())
        .all()
    )
    prices = [s.price for s in snapshots]
    if len(prices) < 30:
        return {"prices": [], "volumes": []}

    sma_50 = sum(prices[-50:]) / min(len(prices), 50) if prices else None
    sma_window = min(len(prices), 200)
    sma_200 = sum(prices[-sma_window:]) / sma_window if prices else None

    # ATR approximation: average absolute daily change
    if len(prices) >= 2:
        daily_changes = [abs(prices[i] - prices[i - 1]) for i in range(1, len(prices))]
        atr = sum(daily_changes) / len(daily_changes)
    else:
        atr = 0.0

    # ATR percentile: how current atr compares to recent range
    atr_history = list(reversed(daily_changes[-20:])) if len(daily_changes) >= 20 else daily_changes
    atr_percentile = sum(1 for a in atr_history if a <= atr) / max(len(atr_history), 1)

    # Drawdown: peak-to-current
    peak = max(prices) if prices else 0
    current = prices[-1] if prices else 0
    drawdown = (peak - current) / peak if peak > 0 else 0.0

    # Volume trend: positive if recent volumes increasing
    volume_trend = 0.0

    return {
        "prices": prices,
        "volumes": [],
        "sma_50": sma_50,
        "sma_200": sma_200,
        "atr": atr,
        "atr_percentile": atr_percentile,
        "drawdown": drawdown,
        "volume_trend": volume_trend,
    }


def get_live_genomes(db: Session) -> List[GenomeRegistry]:
    """Get all live genomes from the registry."""
    return (
        db.query(GenomeRegistry)
        .filter(GenomeRegistry.stage == "LIVE")
        .all()
    )


def detect_regime_and_rebalance(db: Session) -> str:
    """Detect current market regime and rebalance strategy allocations.

    Analyzes live BTC price data to determine regime, then adjusts capital
    allocation weights for strategy archetypes based on regime preferences.

    Returns:
        Detected regime name (string).
    """
    market_data = _build_market_data(db)
    if len(market_data.get("prices", [])) < 30:
        logger.warning(
            "regime_population_manager: insufficient price data ({}) for regime detection",
            len(market_data.get("prices", []))
        )
        return "neutral"

    detector = RegimeDetector()
    result = detector.detect_regime(market_data)
    regime = result.regime.value
    confidence = result.confidence

    logger.info(
        "regime_population_manager: detected regime={} confidence={:.2f}",
        regime, confidence,
        indicators=result.indicators
    )

    prefs = REGIME_STRATEGY_PREFERENCES.get(regime, {})
    if prefs:
        for archetype in prefs.get("boost", []):
            publish_event("archetype_allocation_changed", {
                "archetype": archetype,
                "factor": 1.50,
                "action": "boost",
                "regime": regime,
            })

        for archetype in prefs.get("suppress", []):
            publish_event("archetype_allocation_changed", {
                "archetype": archetype,
                "factor": 0.50,
                "action": "suppress",
                "regime": regime,
            })

    # Trigger mutation with risk-chromosome target for live genomes
    for genome in get_live_genomes(db):
        try:
            chromosomes = json.loads(genome.chromosomes_json) if genome.chromosomes_json else {}
        except Exception:
            chromosomes = {}
        chromosomes.setdefault("meta", {})["next_mutation_target"] = "risk_chromosome"
        genome.chromosomes_json = json.dumps(chromosomes)

    publish_event("regime_shift", {"to": regime, "confidence": confidence})
    return regime
