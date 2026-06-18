"""APEX edge model — unified data structures for edge detection, signals, and exits."""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Optional


class EdgeType(enum.Enum):
    """Types of structural edges APEX can detect."""
    RESOLUTION_TIMING = "resolution_timing"
    ORDER_BOOK_STALE = "order_book_stale"
    LIQUIDITY_GAP = "liquidity_gap"
    MOMENTUM_REVERSION = "momentum_reversion"
    INFORMATION_ASYMMETRY = "information_asymmetry"
    CROSS_PLATFORM = "cross_platform"


class ExitReason(enum.Enum):
    """Reasons for exiting a position."""
    PROFIT_TARGET = "profit_target"
    STOP_LOSS = "stop_loss"
    TIME_DECAY = "time_decay"
    EDGE_DECAY = "edge_decay"
    MARKET_RESOLVED = "market_resolved"
    CORRELATED_EXIT = "correlated_exit"
    RISK_REDUCTION = "risk_reduction"


@dataclass
class Edge:
    """A detected structural edge in a prediction market.

    An edge represents a discrepancy between the market price and our estimate
    of the true probability, along with metadata about detection confidence and
    expected duration.
    """

    market_id: str
    token_id: str
    edge_type: EdgeType
    direction: str  # "yes" or "no"
    entry_price: float  # current market price (0.01-0.99)
    fair_price: float  # our estimated true probability
    edge_pp: float  # fair_price - entry_price in percentage points
    confidence: float  # 0.0-1.0, how confident in our estimate
    edge_score: float  # composite: edge_pp * confidence
    time_horizon_min: int  # expected hold duration in minutes
    metadata: Dict[str, Any] = field(default_factory=dict)
    detected_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    expires_at: Optional[datetime] = None  # when edge signal goes stale

    @property
    def expected_value(self) -> float:
        """Expected value per dollar invested."""
        if self.direction == "yes":
            return self.fair_price - self.entry_price
        return (1.0 - self.fair_price) - (1.0 - self.entry_price)

    @property
    def is_expired(self) -> bool:
        """Whether this edge has passed its expiration time."""
        if self.expires_at is None:
            return False
        return datetime.now(timezone.utc) > self.expires_at

    def remaining_edge(self) -> float:
        """Calculate remaining edge using exponential decay.

        Edge decays with configurable half-life. At time t after detection,
        remaining edge = edge_pp * (0.5 ** (t / half_life)).
        """
        if self.expires_at is None:
            return self.edge_pp

        now = datetime.now(timezone.utc)
        elapsed = (now - self.detected_at).total_seconds()
        half_life = (self.expires_at - self.detected_at).total_seconds()
        if half_life <= 0:
            return 0.0

        decay_factor = 0.5 ** (elapsed / half_life)
        return self.edge_pp * decay_factor


@dataclass
class Signal:
    """An actionable trading signal derived from one or more edges.

    A signal has passed through the signal pipeline: it's been filtered,
    deduplicated, sized, and ranked. It's ready for risk evaluation.
    """

    market_id: str
    token_id: str
    edge_type: EdgeType
    direction: str  # "yes" or "no"
    entry_price: float
    fair_price: float
    edge_pp: float
    confidence: float
    edge_score: float  # edge_pp * confidence
    size_usd: float  # position size in USD
    expected_value: float  # edge_pp * size_usd
    time_horizon_min: int
    profit_target_pct: float  # target profit percentage
    stop_loss_pct: float  # stop loss percentage
    max_hold_seconds: int  # maximum hold time
    source_edges: list[Edge] = field(default_factory=list)  # edges that contributed
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def profit_target_price(self) -> float:
        """Target exit price based on profit target."""
        if self.direction == "yes":
            return self.entry_price * (1 + self.profit_target_pct)
        return self.entry_price * (1 - self.profit_target_pct)

    @property
    def stop_loss_price(self) -> float:
        """Stop loss price."""
        if self.direction == "yes":
            return self.entry_price * (1 - self.stop_loss_pct)
        return self.entry_price * (1 + self.stop_loss_pct)


@dataclass
class ExitSignal:
    """A signal to exit an existing position."""

    trade_id: int
    market_id: str
    reason: ExitReason
    exit_price: float  # target exit price
    urgency: float  # 0.0-1.0, how fast we need to exit
    edge_at_entry: float  # original edge when position was opened
    current_edge: float  # current edge estimate
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def is_urgent(self) -> bool:
        """Whether this exit requires immediate action."""
        return self.urgency >= 0.8
