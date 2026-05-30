"""Market Making EdgeCalculator — spread capture edge.

Computes edge from the bid-ask spread: the market maker profits by
buying at bid and selling at ask, capturing the spread minus adverse
selection risk.
"""

from __future__ import annotations

from typing import Any

from loguru import logger

from backend.strategies.edge_models.base import EdgeCalculator, EdgeResult


class MarketMakingEdgeCalculator(EdgeCalculator):
    """Edge from bid-ask spread capture.

    Expected market_data keys:
        - 'bid': float (best bid price)
        - 'ask': float (best ask price)
        - 'mid': float (mid price, optional — computed from bid/ask if absent)
        - 'book_depth': float (total orderbook depth, optional)
        - 'last_trade_price': float (optional, for adverse selection calc)
    """

    @property
    def name(self) -> str:
        return "market_making"

    @property
    def description(self) -> str:
        return (
            "Market making edge from bid-ask spread capture. Profits from "
            "providing liquidity by capturing half-spread minus adverse selection."
        )

    async def calculate(
        self,
        market_price: float,
        market_data: dict[str, Any],
        params: dict[str, Any] | None = None,
    ) -> EdgeResult | None:
        params = params or {}
        bid = market_data.get("bid")
        ask = market_data.get("ask")

        if bid is None or ask is None or bid >= ask:
            logger.debug("MarketMakingEdgeCalculator: invalid bid/ask, skipping")
            return None

        spread = ask - bid
        half_spread = spread / 2.0
        mid = market_data.get("mid", (bid + ask) / 2.0)

        # Adverse selection penalty: if last trade is near one side,
        # the market maker is more likely to be picked off
        last_trade = market_data.get("last_trade_price")
        adverse_selection = 0.0
        if last_trade is not None:
            adverse_selection = abs(last_trade - mid) / spread if spread > 0 else 0.0
            adverse_selection = min(1.0, adverse_selection)

        # Edge = half_spread * (1 - adverse_selection_weight)
        adverse_weight = params.get("adverse_weight", 0.50)
        edge = half_spread * (1.0 - adverse_selection * adverse_weight)

        # Book depth penalty: thin books = higher risk
        book_depth = market_data.get("book_depth")
        depth_penalty = 1.0
        if book_depth is not None:
            min_depth = params.get("min_book_depth", 100.0)
            if book_depth < min_depth:
                depth_penalty = book_depth / min_depth
                edge *= depth_penalty

        min_edge = params.get("min_edge", 0.005)  # lower threshold for MM
        if edge < min_edge:
            return None

        # Model probability for MM: fair value is mid
        model_probability = mid
        direction = "up"  # MM provides both sides, direction neutral

        return EdgeResult(
            edge=edge,
            model_probability=model_probability,
            confidence=max(0.1, 1.0 - adverse_selection),
            direction=direction,
            reasoning=(
                f"MM: bid={bid:.4f}, ask={ask:.4f}, spread={spread:.4f}, "
                f"half_spread={half_spread:.4f}, adverse={adverse_selection:.3f}"
            ),
            metadata={
                "bid": bid,
                "ask": ask,
                "spread": spread,
                "half_spread": half_spread,
                "adverse_selection": adverse_selection,
                "depth_penalty": depth_penalty,
            },
        )
