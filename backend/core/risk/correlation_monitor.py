"""Cross-market correlation monitor — prevents clustered exposure across related market categories."""

from dataclasses import dataclass, field
from typing import Dict, Optional

from loguru import logger
from prometheus_client import Gauge

from backend.config import settings
from backend.monitoring.agi_metrics import (
    record_correlation_exposure,
    record_correlation_blocked,
)
from backend.db.utils import get_db_session
from backend.models.database import Trade

# ── Market category definitions ──────────────────────────────────────────────

MARKET_CATEGORIES: Dict[str, list[str]] = {
    "crypto": ["btc", "bitcoin", "eth", "ethereum", "solana", "sol", "crypto", "defi", "token", "blockchain", "nft"],
    "politics": ["trump", "biden", "xi", "putin", "election", "president", "senate", "congress", "republican", "democrat", "political", "impeach", "vote", "governor", "party", "caucus"],
    "sports": ["nba", "nfl", "mlb", "nhl", "soccer", "football", "basketball", "baseball", "tennis", "golf", "ufc", "boxing", "f1", "formula", "cricket", "olympic", "world cup", "championship", "playoff", "super bowl", "world series"],
    "esports": ["esport", "league of legends", "dota", "csgo", "valorant", "overwatch", "fortnite", "pubg", "twitch", "streamer", "gaming tournament"],
    "weather": ["weather", "temperature", "hurricane", "tornado", "flood", "rain", "snow", "heat", "cold", "storm", "climate", "celsius", "fahrenheit"],
}

# Prometheus gauge per category
_correlation_exposure_gauge = Gauge(
    "polyedge_correlation_exposure_pct",
    "Correlation-adjusted exposure as percentage of bankroll, by category",
    ["category"],
)


def classify_market_broad(market_ticker: str, event_slug: Optional[str] = None) -> str:
    """Classify a market into a category based on ticker and event slug keywords.

    Returns the matched category name, or 'uncategorized' if no keywords match.
    """
    text = f"{market_ticker or ''} {event_slug or ''}".lower()
    for category, keywords in MARKET_CATEGORIES.items():
        if any(kw in text for kw in keywords):
            return category
    return "uncategorized"


@dataclass
class CorrelationCheckResult:
    allowed: bool
    reason: str
    category_exposure: Dict[str, float] = field(default_factory=dict)
    adjusted_exposure_pct: float = 0.0


class CorrelationMonitor:
    """Monitors cross-market correlation and blocks trades when clustered exposure exceeds threshold."""

    def __init__(self, settings_obj=None):
        self.s = settings_obj or settings
        self.correlation_multiplier = getattr(self.s, "CORRELATION_MULTIPLIER", 2.0)
        self.max_correlated_exposure_pct = getattr(self.s, "MAX_CORRELATED_EXPOSURE_PCT", 0.30)

    def check_correlation(
        self,
        bankroll: float,
        market_ticker: str,
        trade_size: float,
        event_slug: Optional[str] = None,
        db=None,
        mode: Optional[str] = None,
    ) -> CorrelationCheckResult:
        """Check if adding this trade would exceed correlation-adjusted exposure limits.

        Same-category positions count `correlation_multiplier`x (default 2x) toward exposure.
        Blocks if correlation-adjusted exposure > max_correlated_exposure_pct of bankroll.
        """
        if bankroll <= 0:
            return CorrelationCheckResult(True, "zero bankroll — skip check")

        owns_db = db is None
        from contextlib import nullcontext
        ctx = get_db_session() if owns_db else nullcontext(db)
        try:
            with ctx as db:
                effective_mode = mode or self.s.TRADING_MODE

                # Sum open exposure per category
                open_trades = (
                    db.query(Trade.market_ticker, Trade.event_slug, Trade.size)
                    .filter(
                        Trade.settled.is_(False),
                        Trade.trading_mode == effective_mode,
                    )
                    .all()
                )

                category_exposure: Dict[str, float] = {}
                for t_market, t_event, t_size in open_trades:
                    cat = classify_market_broad(t_market, t_event)
                    category_exposure[cat] = category_exposure.get(cat, 0.0) + float(t_size or 0.0)

                # Add the proposed trade
                new_cat = classify_market_broad(market_ticker, event_slug)
                category_exposure[new_cat] = category_exposure.get(new_cat, 0.0) + trade_size

                # Compute correlation-adjusted exposure:
                # Same-category positions count `multiplier`x
                sum(category_exposure.values())
                adjusted_total = 0.0
                for cat, exposure in category_exposure.items():
                    if cat == "uncategorized":
                        adjusted_total += exposure
                    else:
                        adjusted_total += exposure * self.correlation_multiplier

                adjusted_pct = adjusted_total / bankroll if bankroll > 0 else 0.0

                # Emit Prometheus gauges
                for cat, exposure in category_exposure.items():
                    cat_pct = (exposure * (self.correlation_multiplier if cat != "uncategorized" else 1.0)) / bankroll * 100
                    _correlation_exposure_gauge.labels(category=cat).set(cat_pct)
                    record_correlation_exposure(cat, cat_pct)

                if adjusted_pct > self.max_correlated_exposure_pct:
                    record_correlation_blocked()
                    breakdown = ", ".join(
                        f"{cat}=${exp:.2f}" for cat, exp in sorted(category_exposure.items()) if exp > 0
                    )
                    reason = (
                        f"correlation-adjusted exposure {adjusted_pct:.1%} > "
                        f"{self.max_correlated_exposure_pct:.0%} limit "
                        f"(category={new_cat}, breakdown: {breakdown})"
                    )
                    logger.warning("[correlation_monitor] BLOCKED: {}", reason)
                    return CorrelationCheckResult(
                        allowed=False,
                        reason=reason,
                        category_exposure=category_exposure,
                        adjusted_exposure_pct=adjusted_pct,
                    )

                return CorrelationCheckResult(
                    allowed=True,
                    reason="ok",
                    category_exposure=category_exposure,
                    adjusted_exposure_pct=adjusted_pct,
                )
        except Exception as e:
            logger.opt(exception=True).error(
                "[correlation_monitor] check_correlation failed: {}: {}",
                type(e).__name__, e,
            )
            # Fail-open: don't block trades on monitor errors
            return CorrelationCheckResult(True, f"check_error: {type(e).__name__}")
        finally:
            if owns_db:
                db.close()
