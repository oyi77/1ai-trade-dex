"""Maker/Taker edge differential analytics with 5-minute in-memory cache.

Computes full-history ROI for maker and taker trades and produces an
AGI recommendation to guide strategy weight rebalancing.
"""

from __future__ import annotations

import time
from typing import Optional

from loguru import logger
from sqlalchemy.orm import Session

from backend.models.database import Trade


class MakerTakerAnalytics:
    """Compute maker vs taker ROI over all settled trades, with a 5-min cache."""

    MIN_SETTLED_TRADES: int = 20   # per role, before acting on the recommendation
    CACHE_TTL_SECONDS: int = 300   # 5 minutes

    def __init__(self) -> None:
        self._cache: Optional[dict] = None
        self._cache_time: float = 0.0

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_stats(self, db: Session) -> dict:
        """Return cached maker/taker ROI stats computed from all settled trades.

        Returns a dict with keys:
            maker        – {count, pnl, size, roi}
            taker        – {count, pnl, size, roi}
            recommendation – 'prefer_maker' | 'reduce_taker' | 'neutral' | 'insufficient_data'
            cached_at    – ISO-8601 timestamp of when the cache was last refreshed
        """
        now = time.monotonic()
        if self._cache is not None and (now - self._cache_time) < self.CACHE_TTL_SECONDS:
            return self._cache

        stats = self._compute(db)
        self._cache = stats
        self._cache_time = now
        return stats

    def invalidate(self) -> None:
        """Force the next call to recompute from the DB."""
        self._cache = None
        self._cache_time = 0.0

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _compute(self, db: Session) -> dict:
        """Run the full-history settled-trade query and compute per-role ROI."""
        import datetime

        try:
            trades = (
                db.query(Trade)
                .filter(Trade.settled.is_(True))
                .all()
            )
        except Exception:
            logger.exception("[MakerTakerAnalytics] DB query failed")
            trades = []

        maker_trades = [t for t in trades if getattr(t, "role", None) == "maker"]
        taker_trades = [t for t in trades if getattr(t, "role", None) == "taker"]

        maker_stats = self._role_stats(maker_trades)
        taker_stats = self._role_stats(taker_trades)

        recommendation = self._recommend(maker_stats, taker_stats)

        result = {
            "maker": maker_stats,
            "taker": taker_stats,
            "recommendation": recommendation,
            "cached_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        }

        logger.debug(
            "[MakerTakerAnalytics] maker=%s taker=%s → %s",
            maker_stats,
            taker_stats,
            recommendation,
        )
        return result

    @staticmethod
    def _role_stats(trades: list) -> dict:
        """Aggregate count, total PnL, total size, and ROI for a list of trades."""
        count = len(trades)
        pnl = sum(getattr(t, "pnl", None) or 0.0 for t in trades)
        size = sum(getattr(t, "size", None) or 0.0 for t in trades)
        roi = (pnl / size) if size > 0 else 0.0
        return {
            "count": count,
            "pnl": round(pnl, 4),
            "size": round(size, 4),
            "roi": round(roi, 6),
        }

    def _recommend(self, maker: dict, taker: dict) -> str:
        """Derive an AGI recommendation based on minimum-sample-size thresholds and ROI.

        Rules (applied only when both roles have ≥ MIN_SETTLED_TRADES):
            prefer_maker  → maker ROI > taker ROI by > 2 percentage points
            reduce_taker  → taker ROI < -1% (regardless of maker)
            neutral       → neither condition met
        """
        if maker["count"] < self.MIN_SETTLED_TRADES or taker["count"] < self.MIN_SETTLED_TRADES:
            return "insufficient_data"

        maker_roi = maker["roi"]
        taker_roi = taker["roi"]

        if taker_roi < -0.01:
            return "reduce_taker"
        if maker_roi > taker_roi + 0.02:
            return "prefer_maker"
        return "neutral"


# Module-level singleton (import and use directly)
maker_taker_analytics = MakerTakerAnalytics()
