"""
Multi-model signal ensemble for PolyEdge Trading Bot.

Combines technical, AI, orderbook, and data-quality signals
into a single weighted probability with confidence scoring.
"""
import logging
from dataclasses import dataclass

logger = logging.getLogger("trading_bot.ensemble")


@dataclass
class EnsembleSignal:
    combined_probability: float  # final weighted probability [0, 1]
    confidence: float            # overall confidence [0, 1]
    component_breakdown: dict    # component_name -> weighted contribution
    edge: float                  # |combined_probability - market_price|


class EnsembleSignalGenerator:
    DEFAULT_WEIGHTS = {
        "technical": 0.40,
        "ai": 0.30,
        "orderbook": 0.15,
        "data_quality": 0.15,
    }

    def __init__(self, weights: dict = None):
        self.weights = weights if weights is not None else dict(self.DEFAULT_WEIGHTS)

    def combine_signals(
        self,
        technical_prob: float,
        technical_conf: float = 0.0,
        ai_prob: float = None,
        ai_confidence: float = 0.0,
        orderbook_imbalance: float = 0.0,
        orderbook_conf: float = 0.0,
        wash_trade_score: int = 0,
        market_price: float = 0.5,
    ) -> EnsembleSignal:
        """
        Combine component signals into a single EnsembleSignal.

        Args:
            technical_prob: Technical analysis probability [0, 1]
            ai_prob: AI model probability [0, 1], or None to skip
            orderbook_imbalance: Order book imbalance [-1, 1]
            wash_trade_score: Wash trade score [0, 100]
            market_price: Current market price [0, 1]

        Returns:
            EnsembleSignal with combined probability and confidence
        """
        weights = dict(self.weights)

        # Orderbook component: maps [-1, 1] imbalance -> [0.35, 0.65]
        orderbook_prob = 0.5 + (orderbook_imbalance * 0.15)

        # data_quality is a confidence multiplier only — base weights (technical + ai +
        # orderbook) are renormalized to sum to 1.0 among themselves.
        quality_factor = 1.0 - (wash_trade_score / 200.0)
        quality_factor = max(0.5, min(1.0, quality_factor))

        components: dict[str, tuple[float, float]] = {}
        components["technical"] = (technical_prob, weights["technical"])
        if ai_prob is not None:
            components["ai"] = (ai_prob, weights["ai"])
        components["orderbook"] = (orderbook_prob, weights["orderbook"])

        total_weight = sum(w for _, w in components.values())

        component_breakdown: dict[str, float] = {}
        if total_weight > 0:
            combined = sum(p * w / total_weight for p, w in components.values())
            for name, (p, w) in components.items():
                component_breakdown[name] = p * w / total_weight
        else:
            combined = 0.5
            for name, (p, _) in components.items():
                component_breakdown[name] = 0.0

        component_breakdown["data_quality"] = weights["data_quality"] * quality_factor

        combined = max(0.01, min(0.99, combined))

        active_probs = [technical_prob, orderbook_prob]
        if ai_prob is not None:
            active_probs.append(ai_prob)

        if len(active_probs) > 1:
            prob_mean = sum(active_probs) / len(active_probs)
            prob_var = sum((p - prob_mean) ** 2 for p in active_probs) / len(active_probs)
            agreement = 1.0 - min(1.0, prob_var * 4.0)
        else:
            agreement = 0.5

# Weighted average probability using component confidences as weights
        components_with_conf = []
        if technical_conf > 0:
            components_with_conf.append((technical_prob, technical_conf))
        if ai_prob is not None and ai_confidence > 0:
            components_with_conf.append((ai_prob, ai_confidence))
        if orderbook_conf > 0:
            components_with_conf.append((orderbook_prob, orderbook_conf))

        if components_with_conf:
            total_conf = sum(c for _, c in components_with_conf)
            if total_conf > 0:
                weighted_avg_conf = sum(p * c / total_conf for p, c in components_with_conf)
            else:
                weighted_avg_conf = agreement
        else:
            weighted_avg_conf = agreement

        # Confidence is max of weighted-average component confidence and quality-adjusted agreement
        confidence = max(weighted_avg_conf, agreement * quality_factor)
        confidence = max(0.0, min(1.0, confidence))

        component_breakdown["weighted_avg_confidence"] = weighted_avg_conf
        component_breakdown["confidence_source"] = "weighted_average_components"
        confidence = max(0.0, min(1.0, confidence))

        edge = abs(combined - market_price)

        logger.debug(
            "Ensemble: combined=%.4f confidence=%.4f edge=%.4f quality=%.4f",
            combined,
            confidence,
            edge,
            quality_factor,
        )

        return EnsembleSignal(
            combined_probability=combined,
            confidence=confidence,
            component_breakdown=component_breakdown,
            edge=edge,
        )
