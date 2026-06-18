"""APEX edge calculator — unified edge computation combining probability models.

Orchestrates Brownian bridge, near-resolution, and other models to produce
a single best-estimate probability and edge signal for each market.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from backend.core.edge.edge_types import (
    EdgeSignal,
    EdgeType,
    MarketSnapshot,
    ProbabilityEstimate,
    clamp,
)
from backend.core.edge.probability_models import (
    BrownianBridgeModel,
    NearResolutionModel,
    ProbabilityModel,
)
from backend.core.edge.calibration_tracker import CalibrationTracker

logger = logging.getLogger(__name__)


def _classify_edge(
    model_prob: float,
    market_price: float,
    time_to_resolution_hours: float | None,
    spread: float,
) -> EdgeType:
    """Classify the dominant edge type based on signal characteristics."""
    # Near-resolution with high certainty
    if time_to_resolution_hours is not None and time_to_resolution_hours < 72:
        if model_prob > 0.85 or model_prob < 0.15:
            return EdgeType.RESOLUTION_TIMING

    # Wide spread
    if spread > 0.03:
        return EdgeType.LIQUIDITY_GAP

    # Significant probability deviation from market
    if abs(model_prob - market_price) > 0.10:
        return EdgeType.MISPRICED_PROBABILITY

    # Time decay for moderate certainty near resolution
    if time_to_resolution_hours is not None and time_to_resolution_hours < 168:
        return EdgeType.TIME_DECAY

    return EdgeType.MISPRICED_PROBABILITY


class APEXEdgeCalculator:
    """Computes structural edge by combining probability models with calibration.

    Runs all applicable probability models on each market, produces a
    weighted ensemble estimate, applies calibration adjustments, and
    generates EdgeSignal objects for the router.
    """

    def __init__(self, settings_obj: Any = None):
        from backend.config import settings as _settings

        self.settings = settings_obj or _settings
        self.models: list[ProbabilityModel] = [
            BrownianBridgeModel(),
            NearResolutionModel(
                min_hours=getattr(self.settings, "APEX_NEAR_RESOLUTION_MIN_HOURS", 1.0),
                max_hours=getattr(self.settings, "APEX_NEAR_RESOLUTION_MAX_HOURS", 72.0),
                min_price=getattr(self.settings, "APEX_NEAR_RESOLUTION_MIN_PRICE", 0.85),
            ),
        ]
        self.calibration = CalibrationTracker()

    async def compute_edge(
        self,
        snapshot: MarketSnapshot,
        market_price: float | None = None,
    ) -> EdgeSignal | None:
        """Get best probability estimate and compute edge for a market.

        Args:
            snapshot: Market snapshot with prices, volume, dates.
            market_price: Override market price (defaults to snapshot.yes_price).

        Returns:
            EdgeSignal if tradeable edge found, None otherwise.
        """
        if market_price is None:
            market_price = snapshot.yes_price

        # Need time to resolution for probability models
        time_to_resolution = timedelta(hours=999)  # default: far future
        if snapshot.end_date:
            remaining = snapshot.end_date - datetime.now(timezone.utc)
            if remaining.total_seconds() > 0:
                time_to_resolution = remaining
            else:
                return None  # market already resolved

        # Run all applicable models
        estimates: list[ProbabilityEstimate] = []
        for model in self.models:
            try:
                est = await model.estimate_probability(
                    snapshot, market_price, time_to_resolution
                )
                if est is not None:
                    estimates.append(est)
            except Exception as e:
                logger.debug(f"APEX: Model {model.__class__.__name__} failed: {e}")
                continue

        if not estimates:
            return None

        # Weighted ensemble: higher confidence = more weight
        total_weight = sum(e.confidence for e in estimates)
        if total_weight == 0:
            return None

        weighted_prob = sum(e.probability * e.confidence for e in estimates) / total_weight
        avg_confidence = total_weight / len(estimates)

        # Apply calibration adjustment
        calibration_adj = self.calibration.get_adjustment(
            snapshot.category, weighted_prob
        )
        weighted_prob = clamp(weighted_prob + calibration_adj / 100, 0.01, 0.99)

        # Reliability multiplier from calibration
        reliability = self.calibration.get_reliability(snapshot.category)
        confidence = avg_confidence * reliability

        # Compute edge
        edge_pp = abs(weighted_prob - market_price) * 100

        # Direction
        direction = "YES" if weighted_prob > market_price else "NO"

        # Minimum edge threshold
        min_edge = getattr(self.settings, "APEX_MIN_EDGE_PP", 2.0)
        if edge_pp < min_edge:
            return None

        # Minimum confidence
        min_confidence = getattr(self.settings, "APEX_MIN_CONFIDENCE", 0.5)
        if confidence < min_confidence:
            return None

        # Classify edge type
        hours_left = (
            snapshot.time_to_resolution_hours
            if snapshot.time_to_resolution_hours
            else 999
        )
        edge_type = _classify_edge(weighted_prob, market_price, hours_left, snapshot.spread)

        # Determine expiration
        expires_in = min(
            timedelta(hours=max(hours_left * 0.5, 1)),
            timedelta(hours=24),
        )

        return EdgeSignal(
            market_ticker=snapshot.ticker,
            token_id=snapshot.token_id,
            edge_type=edge_type,
            direction=direction,
            model_probability=weighted_prob,
            market_price=market_price,
            edge_pp=edge_pp,
            confidence=confidence,
            time_to_resolution_hours=hours_left,
            metadata={
                "estimates": [
                    {"model": e.model_name, "prob": e.probability, "conf": e.confidence}
                    for e in estimates
                ],
                "calibration_adj_pp": calibration_adj,
                "reliability": reliability,
                "category": snapshot.category,
            },
            detected_at=datetime.now(timezone.utc),
            expires_at=datetime.now(timezone.utc) + expires_in,
        )

    async def compute_edges(
        self, snapshots: list[MarketSnapshot]
    ) -> list[EdgeSignal]:
        """Compute edges for multiple market snapshots.

        Filters out None results and returns sorted by expected value.
        """
        edges = []
        for snap in snapshots:
            try:
                edge = await self.compute_edge(snap)
                if edge is not None:
                    edges.append(edge)
            except Exception as e:
                logger.debug(f"APEX: Edge computation failed for {snap.ticker}: {e}")
                continue

        edges.sort(key=lambda s: s.expected_value, reverse=True)
        return edges
