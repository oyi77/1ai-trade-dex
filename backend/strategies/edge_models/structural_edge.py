"""Structural edge calculator — EdgeCalculator ABC implementation for APEX.

Implements the existing EdgeCalculator interface to integrate with the
modular strategy architecture. Delegates to APEXEdgeCalculator internally.
"""

from __future__ import annotations

import logging
from typing import Any

from backend.strategies.edge_models.base import EdgeCalculator, EdgeResult
from backend.core.edge.edge_types import clamp
from backend.core.edge.edge_calculator import APEXEdgeCalculator

logger = logging.getLogger(__name__)


class StructuralEdgeCalculator(EdgeCalculator):
    """EdgeCalculator implementation that uses APEX pipeline internally.

    Bridges the existing EdgeCalculator ABC with the APEX probability
    models and calibration system.
    """

    @property
    def name(self) -> str:
        return "structural_edge"

    @property
    def description(self) -> str:
        return "Structural edge detection using Brownian bridge probability models and calibration feedback"

    async def calculate(
        self,
        market_price: float,
        market_data: dict[str, Any],
        params: dict[str, Any] | None = None,
    ) -> EdgeResult | None:
        """Calculate structural edge from market data.

        Args:
            market_price: Current market yes price (0-1).
            market_data: Dict with keys:
                - 'snapshot': MarketSnapshot object (preferred)
                - 'ticker': Market ticker string
                - 'token_id': Token ID string
                - 'category': Market category string
                - 'volume': Market volume float
                - 'spread': Bid-ask spread float
                - 'end_date': ISO datetime string or None
                - 'bid_depth': Bid depth float
                - 'ask_depth': Ask depth float
            params: Optional overrides for min_edge_pp etc.

        Returns:
            EdgeResult if tradeable edge found, None otherwise.
        """
        from backend.core.edge.edge_types import MarketSnapshot
        from datetime import datetime, timezone

        params = params or {}

        # Build MarketSnapshot from market_data
        snapshot = market_data.get("snapshot")
        if snapshot is None:
            # Build from dict
            end_date = None
            ed_str = market_data.get("end_date")
            if ed_str:
                try:
                    end_date = datetime.fromisoformat(ed_str.replace("Z", "+00:00"))
                except (ValueError, TypeError):
                    pass

            snapshot = MarketSnapshot(
                ticker=market_data.get("ticker", ""),
                token_id=market_data.get("token_id", ""),
                yes_price=market_price,
                no_price=1 - market_price,
                volume=float(market_data.get("volume", 0)),
                liquidity=float(market_data.get("liquidity", 0)),
                spread=float(market_data.get("spread", 0.05)),
                bid_depth=float(market_data.get("bid_depth", 0)),
                ask_depth=float(market_data.get("ask_depth", 0)),
                end_date=end_date,
                category=market_data.get("category", "unknown"),
                question=market_data.get("question", ""),
            )

        # Use APEX edge calculator
        calc = APEXEdgeCalculator()
        edge_signal = await calc.compute_edge(snapshot, market_price)

        if edge_signal is None:
            return None

        # Convert EdgeSignal to EdgeResult
        direction = "up" if edge_signal.direction == "YES" else "down"

        return EdgeResult(
            edge=edge_signal.edge_pp / 100,  # pp to fraction
            model_probability=edge_signal.model_probability,
            confidence=edge_signal.confidence,
            direction=direction,
            reasoning=edge_signal.metadata.get("reasoning", f"APEX {edge_signal.edge_type.value}"),
            metadata={
                "edge_type": edge_signal.edge_type.value,
                "edge_pp": edge_signal.edge_pp,
                "time_to_resolution_hours": edge_signal.time_to_resolution_hours,
                "estimates": edge_signal.metadata.get("estimates", []),
                "calibration_adj_pp": edge_signal.metadata.get("calibration_adj_pp", 0),
                "category": edge_signal.metadata.get("category", "unknown"),
            },
        )