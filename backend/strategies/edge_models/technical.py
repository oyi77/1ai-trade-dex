"""Technical EdgeCalculator — RSI, momentum, VWAP, SMA composite edge.

Extracts the same weighted composite formula used by CryptoOracleStrategy:
  composite = rsi_norm*0.25 + mom_signal*0.30 + vwap_signal*0.25 + sma_signal*0.20

Converts composite into a model probability and edge vs. market price.
"""

from __future__ import annotations

from typing import Any

from loguru import logger

from backend.strategies.edge_models.base import EdgeCalculator, EdgeResult


class TechnicalEdgeCalculator(EdgeCalculator):
    """Edge from RSI, momentum, VWAP deviation, SMA crossover.

    Expected market_data keys:
        - 'rsi': float (0-100)
        - 'momentum_5m': float (price change rate over 5 min)
        - 'vwap_deviation': float (price vs VWAP ratio)
        - 'sma_crossover': float (short SMA vs long SMA ratio)
    """

    @property
    def name(self) -> str:
        return "technical"

    @property
    def description(self) -> str:
        return (
            "Technical edge from RSI/momentum/VWAP/SMA weighted composite. "
            "Converts normalized indicators into model probability."
        )

    async def calculate(
        self,
        market_price: float,
        market_data: dict[str, Any],
        params: dict[str, Any] | None = None,
    ) -> EdgeResult | None:
        params = params or {}
        rsi = market_data.get("rsi")
        momentum = market_data.get("momentum_5m")
        vwap_dev = market_data.get("vwap_deviation")
        sma_cross = market_data.get("sma_crossover")

        if any(v is None for v in [rsi, momentum, vwap_dev, sma_cross]):
            logger.debug("TechnicalEdgeCalculator: missing indicator data, skipping")
            return None

        # Normalize each indicator to [-1, 1]
        rsi_norm = (rsi - 50.0) / 50.0
        mom_signal = max(-1.0, min(1.0, momentum * 10.0))
        vwap_signal = max(-1.0, min(1.0, vwap_dev * 100.0))
        sma_signal = max(-1.0, min(1.0, sma_cross * 100.0))

        # Weighted composite (same weights as CryptoOracleStrategy)
        composite = (
            rsi_norm * 0.25 + mom_signal * 0.30 + vwap_signal * 0.25 + sma_signal * 0.20
        )

        # Map composite to model probability
        oracle_base = params.get("oracle_implied_base", 0.50)
        oracle_scale = params.get("oracle_implied_scale", 0.30)
        model_probability = oracle_base + composite * oracle_scale
        model_probability = max(0.0, min(1.0, model_probability))

        direction = "up" if composite > 0 else "down"
        edge = abs(model_probability - market_price)

        if edge < params.get("min_edge", 0.02):
            return None

        return EdgeResult(
            edge=edge,
            model_probability=model_probability,
            confidence=min(1.0, abs(composite)),
            direction=direction,
            reasoning=(
                f"Technical composite={composite:.3f} "
                f"(RSI={rsi:.1f}, mom={momentum:.4f}, VWAP={vwap_dev:.4f}, SMA={sma_cross:.4f})"
            ),
            metadata={
                "rsi": rsi,
                "momentum_5m": momentum,
                "vwap_deviation": vwap_dev,
                "sma_crossover": sma_cross,
                "composite": composite,
            },
        )
