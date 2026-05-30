"""CrossPlatformSignalGenerator — price divergence signals.

Detects when the same market outcome is priced differently across
platforms (Polymarket, Kalshi, SX.bet, etc.), signaling arbitrage
or informed-trading opportunities.
"""

from __future__ import annotations

from typing import Any

from loguru import logger

from backend.strategies.signal_generators.base import Signal, SignalGenerator


class CrossPlatformSignalGenerator(SignalGenerator):
    """Generates signals from cross-platform price divergence.

    Expects each market dict to contain:
        - 'ticker': str
        - 'platform_prices': dict[str, float] mapping platform name to yes-price
            e.g. {"polymarket": 0.65, "kalshi": 0.72, "sxbet": 0.68}
    """

    @property
    def name(self) -> str:
        return "cross_platform"

    @property
    def description(self) -> str:
        return (
            "Cross-platform price divergence signals. Detects when the same "
            "outcome is priced differently across prediction market platforms."
        )

    async def generate(
        self,
        markets: list[dict[str, Any]],
        params: dict[str, Any] | None = None,
    ) -> list[Signal]:
        params = params or {}
        signals: list[Signal] = []
        min_divergence = params.get("min_divergence", 0.03)

        for market in markets:
            ticker = market.get("ticker", "")
            platform_prices: dict[str, float] | None = market.get("platform_prices")

            if not platform_prices or len(platform_prices) < 2:
                continue

            platforms = sorted(platform_prices.keys())
            prices = [platform_prices[p] for p in platforms]
            low_price = min(prices)
            high_price = max(prices)
            divergence = high_price - low_price
            avg_price = sum(prices) / len(prices)

            if divergence < min_divergence:
                continue

            low_platform = min(platforms, key=lambda p: platform_prices[p])
            high_platform = max(platforms, key=lambda p: platform_prices[p])

            # Direction: the cheaper platform is where we'd buy "up"
            # Strength based on divergence magnitude
            max_div = params.get("max_divergence", 0.20)
            normalized_strength = min(1.0, divergence / max_div)

            signals.append(
                Signal(
                    signal_type="price_divergence",
                    strength=normalized_strength,
                    confidence=min(1.0, divergence / 0.10),
                    market_ticker=ticker,
                    data={
                        "divergence": divergence,
                        "avg_price": avg_price,
                        "low_platform": low_platform,
                        "high_platform": high_platform,
                        "low_price": low_price,
                        "high_price": high_price,
                        "all_prices": platform_prices,
                    },
                    reasoning=(
                        f"Price divergence: {low_platform}={low_price:.3f} vs "
                        f"{high_platform}={high_price:.3f} "
                        f"(divergence={divergence:.3f})"
                    ),
                )
            )

        return signals
