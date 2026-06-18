"""APEX edge types — data structures for structural edge detection."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class EdgeType(Enum):
    """Categories of structural edge on Polymarket."""

    MISPRICED_PROBABILITY = "mispriced_probability"
    STALE_ODDS = "stale_odds"
    RESOLUTION_TIMING = "resolution_timing"
    LIQUIDITY_GAP = "liquidity_gap"
    ORDERBOOK_IMBALANCE = "orderbook_imbalance"
    TIME_DECAY = "time_decay"
    CROSS_MARKET = "cross_market"


@dataclass
class EdgeSignal:
    """A tradeable structural edge opportunity."""

    market_ticker: str
    token_id: str
    edge_type: EdgeType
    direction: str  # "YES" or "NO"
    model_probability: float  # our estimated true probability
    market_price: float  # current market price
    edge_pp: float  # edge in percentage points
    confidence: float  # 0.0-1.0 confidence in our estimate
    time_to_resolution_hours: float
    metadata: dict[str, Any] = field(default_factory=dict)
    detected_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    expires_at: datetime | None = None

    @property
    def expected_value(self) -> float:
        """Expected value = edge * confidence."""
        return self.edge_pp * self.confidence

    @property
    def is_expired(self) -> bool:
        """Whether this signal has passed its useful lifetime."""
        if self.expires_at is None:
            return False
        return datetime.now(timezone.utc) > self.expires_at


@dataclass
class StructuralInefficiency:
    """A detected market inefficiency (not necessarily tradeable alone)."""

    market_ticker: str
    inefficiency_type: str
    severity: float  # 0.0-1.0
    description: str
    detected_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class ProbabilityEstimate:
    """Output from a probability model."""

    probability: float  # estimated true probability [0,1]
    confidence: float  # confidence in estimate [0,1]
    model_name: str  # which model produced this
    time_to_resolution_hours: float
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class MarketSnapshot:
    """Cached market data for edge detection."""

    ticker: str
    token_id: str
    yes_price: float
    no_price: float
    volume: float
    liquidity: float
    spread: float
    bid_depth: float
    ask_depth: float
    last_price_change_at: datetime | None = None
    end_date: datetime | None = None
    category: str = ""
    question: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def mid_price(self) -> float:
        return (self.yes_price + self.no_price) / 2

    @property
    def time_to_resolution_hours(self) -> float | None:
        if self.end_date is None:
            return None
        delta = self.end_date - datetime.now(timezone.utc)
        return max(0, delta.total_seconds() / 3600)


def clamp(value: float, lo: float = 0.0, hi: float = 1.0) -> float:
    """Clamp a value between lo and hi."""
    return max(lo, min(hi, value))
