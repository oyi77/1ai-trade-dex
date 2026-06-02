"""Arbitrage EdgeCalculator — cross-platform price divergence.

Detects when the same outcome is priced differently across platforms
(Polymarket vs Kalshi vs SX.bet etc.) and computes the edge.
"""

from __future__ import annotations

from typing import Any


from backend.strategies.edge_models.base import EdgeCalculator, EdgeResult


class ArbitrageEdgeCalculator(EdgeCalculator):
    """Edge from cross-platform price divergence.

    Expected market_data keys:
        - 'prices': dict[str, float] mapping platform name to yes-price
            e.g. {"polymarket": 0.65, "kalshi": 0.72}
        - 'market_ticker': str (same outcome across platforms)
    """

    @property
    def name(self) -> str:
        return "arbitrage"

    @property
    def description(self) -> str:
        return (
            "Cross-platform arbitrage edge. Detects price divergence between "
            "platforms for the same market outcome."
        )

    async def calculate(
        self,
        market_price: float,
        market_data: dict[str, Any],
        params: dict[str, Any] | None = None,
    ) -> EdgeResult | None:
        params = params or {}
        prices: dict[str, float] | None = market_data.get("prices")
        if not prices or len(prices) < 2:
            return None

        platform_names = sorted(prices.keys())
        min_platform = min(platform_names, key=lambda p: prices[p])
        max_platform = max(platform_names, key=lambda p: prices[p])
        low_price = prices[min_platform]
        high_price = prices[max_platform]

        # Raw divergence
        divergence = high_price - low_price

        # Account for fees on both legs
        fee_pct = params.get("platform_fee_pct", 0.02)
        total_fees = fee_pct * 2  # buy on cheap + sell on expensive
        net_edge = divergence - total_fees

        min_edge = params.get("min_edge", 0.02)
        if net_edge < min_edge:
            return None

        # Model probability is the average (consensus)
        model_probability = (low_price + high_price) / 2.0
        direction = "up"  # arb is direction-neutral, but buy the cheap side

        return EdgeResult(
            edge=net_edge,
            model_probability=model_probability,
            confidence=min(
                1.0, divergence / 0.10
            ),  # higher divergence = higher confidence
            direction=direction,
            reasoning=(
                f"Arb: {min_platform}={low_price:.3f} vs "
                f"{max_platform}={high_price:.3f} "
                f"(divergence={divergence:.3f}, net={net_edge:.3f})"
            ),
            metadata={
                "buy_platform": min_platform,
                "sell_platform": max_platform,
                "buy_price": low_price,
                "sell_price": high_price,
                "divergence": divergence,
                "total_fees": total_fees,
            },
        )
