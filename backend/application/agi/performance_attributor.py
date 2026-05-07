"""Performance Attribution — scores chromosome contributions to trade outcomes.

Wave 9: Meta-Learning Layer — Part 5.1
Fixes Gap G3 by extending TradeForensics with chromosome-level attribution.
"""

from typing import Dict, Any

from backend.domain.genome.models import StrategyGenome
from backend.core.event_bus import publish_event


def evaluate_signal_quality(trade: Any, market_state: Dict[str, Any]) -> float:
    """Score perception chromosome: signal quality (0-1).

    Uses edge_at_entry, confidence, and market alignment.
    """
    edge = trade.edge_at_entry or 0.0
    confidence = trade.confidence or 0.5

    # Market alignment: check if market moved in predicted direction
    alignment = 1.0 if trade.result == "win" else 0.0

    # Composite score: edge (40%), confidence (30%), alignment (30%)
    score = (edge * 0.40) + (confidence * 0.30) + (alignment * 0.30)
    return max(0.0, min(1.0, score))


def evaluate_entry_exit_timing(trade: Any, market_state: Dict[str, Any]) -> float:
    """Score cognition chromosome: entry/exit timing (0-1).

    Uses fill ratio, hold time, and PnL efficiency.
    """
    _stored_ratio = getattr(trade, "fill_ratio", None)
    fill_ratio = float(_stored_ratio) if isinstance(_stored_ratio, (int, float)) else (trade.filled_size / trade.size if trade.size > 0 else 1.0)

    # Normalize hold time (shorter is better for 5-min trades)
    hold_time_hours = trade.hold_time_seconds / 3600 if trade.hold_time_seconds else 0
    hold_time_score = max(0.0, 1.0 - (hold_time_hours / 24.0))  # Target < 24h

    # PnL efficiency: PnL per hour held
    pnl_efficiency = (trade.pnl or 0.0) / (hold_time_hours + 0.1)
    pnl_efficiency_score = min(1.0, abs(pnl_efficiency) / 100.0)  # Normalize

    # Composite: fill (30%), timing (40%), efficiency (30%)
    score = (fill_ratio * 0.30) + (hold_time_score * 0.40) + (pnl_efficiency_score * 0.30)
    return max(0.0, min(1.0, score))


def evaluate_fill_quality(trade: Any) -> float:
    """Score execution chromosome: fill quality (0-1).

    Uses slippage and fill ratio.
    """
    slippage = trade.slippage or 0.0
    _stored_ratio = getattr(trade, "fill_ratio", None)
    fill_ratio = float(_stored_ratio) if isinstance(_stored_ratio, (int, float)) else (trade.filled_size / trade.size if trade.size > 0 else 1.0)

    # Slippage penalty (inverse relationship)
    slippage_score = max(0.0, 1.0 - (slippage / 0.05))  # 5% slippage = 0 score

    # Composite: fill ratio (60%), slippage (40%)
    score = (fill_ratio * 0.60) + (slippage_score * 0.40)
    return max(0.0, min(1.0, score))


def evaluate_sizing_optimality(trade: Any, genome: StrategyGenome) -> float:
    """Score risk chromosome: position sizing (0-1).

    Uses position size relative to trade capital and PnL consistency.
    """
    # Use trade size as proxy for position sizing (simplified for now)
    # In production, this would use actual portfolio capital
    trade_size = trade.size or 1.0

    # Normalize size (assume target size around 100 units)
    size_score = max(0.0, 1.0 - abs(trade_size - 100.0) / 200.0)

    # PnL consistency (use max_drawdown as proxy for volatility)
    max_drawdown = genome.fitness_metrics.max_drawdown_pct or 0.0
    consistency_score = max(0.0, 1.0 - (max_drawdown / 0.20))  # Target < 20% drawdown

    # Composite: size (40%), consistency (60%)
    score = (size_score * 0.40) + (consistency_score * 0.60)
    return max(0.0, min(1.0, score))


def evaluate_regime_alignment(genome: StrategyGenome, market_state: Dict[str, Any]) -> float:
    """Score meta chromosome: regime alignment (0-1).

    Uses current regime vs. genome's optimal regime.
    """
    current_regime = market_state.get("regime", "neutral")
    genome_regime = genome.chromosomes.get("meta", {}).get("optimal_regime", "neutral")

    # Perfect match = 1.0, mismatch = lower score
    if current_regime == genome_regime:
        return 1.0
    elif genome_regime == "neutral" or current_regime == "neutral":
        return 0.7
    else:
        return 0.3


def attribute_trade_to_chromosomes(
    trade: Any,  # Trade object from DB
    genome: StrategyGenome,
    market_state: Dict[str, Any]
) -> Dict[str, float]:
    """Scores each chromosome's contribution to this trade outcome.

    Appends to genome.chromosome_performance_history.
    If a chromosome scores < 0.3 for 5 consecutive trades,
    sets genome.chromosomes['meta'].next_mutation_target to that chromosome.

    Args:
        trade: Trade object from database
        genome: StrategyGenome instance
        market_state: Current market state dictionary

    Returns:
        Dictionary mapping chromosome name to performance score (0-1)
    """
    attribution = {
        "perception": evaluate_signal_quality(trade, market_state),
        "cognition": evaluate_entry_exit_timing(trade, market_state),
        "execution": evaluate_fill_quality(trade),
        "risk": evaluate_sizing_optimality(trade, genome),
        "meta": evaluate_regime_alignment(genome, market_state),
    }

    # Track performance history and flag underperforming chromosomes
    for chromosome, score in attribution.items():
        genome.chromosome_performance_history.setdefault(chromosome, []).append(score)

        # Flag underperforming chromosome for targeted mutation
        recent = genome.chromosome_performance_history[chromosome][-5:]
        if len(recent) == 5 and all(s < 0.30 for s in recent):
            # Ensure meta chromosome exists
            if "meta" not in genome.chromosomes:
                genome.chromosomes["meta"] = {}
            genome.chromosomes["meta"]["next_mutation_target"] = chromosome

            publish_event("chromosome_flagged", {
                "genome_id": genome.genome_id,
                "chromosome": chromosome,
                "avg_score": sum(recent) / 5
            })

    return attribution
