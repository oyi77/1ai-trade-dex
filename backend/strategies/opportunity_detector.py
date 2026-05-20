"""
Opportunity Detector for PolyEdge.

Multi-type opportunity scanning across prediction markets:
  1. Price discrepancy (YES + NO < 1.0 = risk-free arb)
  2. Momentum (price moved >5% in 1h window)
  3. Liquidity gap (wide spread on active market)
  4. Event-driven (placeholder — needs news feed)
  5. Emotional trading (sharp move then reversion)

All detectors are pure functions — no DB or network calls — so they can
be tested in isolation and composed by any strategy.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class Opportunity:
    """A detected trading opportunity."""

    type: str  # "price_discrepancy" | "momentum" | "liquidity_gap" | "event_driven" | "emotional_trading"
    market_id: str
    market_title: str
    expected_value: float
    confidence: float  # 0-1
    entry_price: float
    target_price: float
    stop_loss: float
    max_size: float
    time_horizon: str
    details: dict = field(default_factory=dict)


@dataclass
class OddsAnalysis:
    """Resolved odds snapshot for a single market."""

    mid_price: float
    best_bid: float
    best_ask: float
    spread: float
    depth_bid_usd: float
    depth_ask_usd: float
    fair_value: float


# ---------------------------------------------------------------------------
# Core resolution
# ---------------------------------------------------------------------------


def resolve_market_odds(
    yes_price: float,
    no_price: float,
    bid_depth: float = 0.0,
    ask_depth: float = 0.0,
) -> OddsAnalysis:
    """Calculate mid, spread, and fair value from YES/NO prices.

    Parameters
    ----------
    yes_price : float
        Best ask for YES token.
    no_price : float
        Best ask for NO token.
    bid_depth : float
        Total bid-side depth in USD.
    ask_depth : float
        Total ask-side depth in USD.

    Returns
    -------
    OddsAnalysis
    """
    mid = (yes_price + (1.0 - no_price)) / 2.0
    spread = yes_price + no_price - 1.0
    # Fair value: average of YES mid and implied NO mid
    fair_value = mid

    return OddsAnalysis(
        mid_price=round(mid, 6),
        best_bid=round(yes_price, 6),
        best_ask=round(no_price, 6),
        spread=round(spread, 6),
        depth_bid_usd=bid_depth,
        depth_ask_usd=ask_depth,
        fair_value=round(fair_value, 6),
    )


# ---------------------------------------------------------------------------
# Type 1 — Price discrepancy
# ---------------------------------------------------------------------------

_FEE_THRESHOLD = 0.98  # 2% edge after ~1% round-trip fees


def detect_price_discrepancy(
    yes_price: float,
    no_price: float,
    market_id: str = "",
    market_title: str = "",
) -> Optional[Opportunity]:
    """Return opportunity if YES + NO < 0.98 (2%+ edge after fees).

    Parameters
    ----------
    yes_price : float
        Current YES price.
    no_price : float
        Current NO price.

    Returns
    -------
    Optional[Opportunity]
    """
    combined = yes_price + no_price
    if combined >= _FEE_THRESHOLD:
        return None

    edge = 1.0 - combined
    confidence = min(edge / 0.10, 1.0)  # scale: 10% edge = max confidence

    return Opportunity(
        type="price_discrepancy",
        market_id=market_id,
        market_title=market_title,
        expected_value=edge,
        confidence=round(confidence, 4),
        entry_price=round(combined, 4),
        target_price=1.0,
        stop_loss=round(max(combined - 0.02, 0.0), 4),
        max_size=1000.0,
        time_horizon="immediate",
        details={
            "yes_price": yes_price,
            "no_price": no_price,
            "combined": combined,
            "edge_pct": round(edge * 100, 2),
        },
    )


# ---------------------------------------------------------------------------
# Type 2 — Momentum
# ---------------------------------------------------------------------------

_MOMENTUM_THRESHOLD = 0.05  # 5%
_MOMENTUM_WINDOW_SEC = 3600  # 1 hour


def detect_momentum(
    price_history: List[float],
    timestamps: List[float],
    market_id: str = "",
    market_title: str = "",
) -> Optional[Opportunity]:
    """Return opportunity if price moved >5% in any 1-hour window.

    Parameters
    ----------
    price_history : list[float]
        Chronological price samples (oldest first).
    timestamps : list[float]
        Unix timestamps parallel to *price_history*.

    Returns
    -------
    Optional[Opportunity]
    """
    if len(price_history) < 2 or len(price_history) != len(timestamps):
        return None

    max_change = 0.0
    max_start = 0.0
    max_end = 0.0

    for i in range(len(price_history)):
        for j in range(i + 1, len(price_history)):
            dt = timestamps[j] - timestamps[i]
            if dt > _MOMENTUM_WINDOW_SEC:
                break
            if price_history[i] == 0:
                continue
            change = abs(price_history[j] - price_history[i]) / price_history[i]
            if change > max_change:
                max_change = change
                max_start = price_history[i]
                max_end = price_history[j]

    if max_change < _MOMENTUM_THRESHOLD:
        return None

    # Direction: "up" means we BUY (ride momentum up), "down" means we BUY THE DIP
    direction = "up" if max_end > max_start else "down"
    confidence = min(max_change / 0.20, 1.0)  # 20% move = max confidence

    if direction == "up":
        # Momentum up: buy, target 10% more, stop at pre-spike price
        entry = max_end
        target = round(max_end * 1.10, 4)
        stop = round(max_start, 4)
    else:
        # Momentum down: buy the dip, target reversion to pre-spike, stop 5% below entry
        entry = max_end
        target = round(max_start, 4)
        stop = round(max_end * 0.95, 4)

    return Opportunity(
        type="momentum",
        market_id=market_id,
        market_title=market_title,
        expected_value=max_change,
        confidence=round(confidence, 4),
        entry_price=round(entry, 4),
        target_price=target,
        stop_loss=stop,
        max_size=500.0,
        time_horizon="1h",
        details={
            "direction": direction,
            "change_pct": round(max_change * 100, 2),
            "price_from": max_start,
            "price_to": max_end,
        },
    )


# ---------------------------------------------------------------------------
# Type 3 — Liquidity gap
# ---------------------------------------------------------------------------

_SPREAD_THRESHOLD_CENTS = 5
_MIN_VOLUME_USD = 1000


def detect_liquidity_gap(
    spread_cents: float,
    market: dict,
    market_id: str = "",
    market_title: str = "",
) -> Optional[Opportunity]:
    """Return opportunity if spread > 5c on market with >$1000 volume.

    Parameters
    ----------
    spread_cents : float
        Current bid-ask spread in cents.
    market : dict
        Market dict with at least a ``volume`` key.

    Returns
    -------
    Optional[Opportunity]
    """
    volume = float(market.get("volume", 0))
    if spread_cents <= _SPREAD_THRESHOLD_CENTS or volume < _MIN_VOLUME_USD:
        return None

    edge = spread_cents / 100.0
    confidence = min(spread_cents / 20.0, 1.0)  # 20c spread = max confidence

    return Opportunity(
        type="liquidity_gap",
        market_id=market_id,
        market_title=market_title,
        expected_value=edge,
        confidence=round(confidence, 4),
        entry_price=0.5,  # mid — actual price determined at execution
        target_price=0.5,
        stop_loss=0.5 - edge,
        max_size=200.0,
        time_horizon="minutes",
        details={
            "spread_cents": spread_cents,
            "volume_usd": volume,
        },
    )


# ---------------------------------------------------------------------------
# Type 4 — Event-driven (placeholder)
# ---------------------------------------------------------------------------


def detect_event_driven(
    market: dict,
    market_id: str = "",
    market_title: str = "",
) -> Optional[Opportunity]:
    """Placeholder for event-driven detection (needs news feed integration).

    Always returns None until a news/event feed is wired in.
    """
    return None


# ---------------------------------------------------------------------------
# Type 5 — Emotional trading
# ---------------------------------------------------------------------------

_EMOTIONAL_SPIKE = 0.10  # 10% move
_EMOTIONAL_REVERT = 0.50  # 50% reversion of that move


def detect_emotional_trading(
    price_history: List[float],
    timestamps: List[float],
    market_id: str = "",
    market_title: str = "",
) -> Optional[Opportunity]:
    """Return opportunity if price moved >10% then reverted >50%.

    Parameters
    ----------
    price_history : list[float]
        Chronological price samples (oldest first).
    timestamps : list[float]
        Unix timestamps parallel to *price_history*.

    Returns
    -------
    Optional[Opportunity]
    """
    if len(price_history) < 3 or len(price_history) != len(timestamps):
        return None

    # Find the peak/trough relative to the first price
    base = price_history[0]
    if base == 0:
        return None

    # Walk forward to find a spike >= 10%
    for i in range(1, len(price_history)):
        change = (price_history[i] - base) / base
        if abs(change) < _EMOTIONAL_SPIKE:
            continue

        # Spike found at index i — check for reversion after it
        spike_price = price_history[i]
        spike_dir = 1 if change > 0 else -1

        for j in range(i + 1, len(price_history)):
            reversion = (spike_price - price_history[j]) * spike_dir
            revert_pct = (
                reversion / abs(spike_price - base)
                if abs(spike_price - base) > 0
                else 0
            )

            if revert_pct >= _EMOTIONAL_REVERT:
                confidence = min(abs(change) / 0.30, 1.0)
                # Target: expected reversion point (not full base — only 50% revert assumed)
                expected_revert = spike_price - (spike_price - base) * _EMOTIONAL_REVERT
                return Opportunity(
                    type="emotional_trading",
                    market_id=market_id,
                    market_title=market_title,
                    expected_value=abs(change),
                    confidence=round(confidence, 4),
                    entry_price=round(price_history[j], 4),
                    target_price=round(expected_revert, 4),
                    stop_loss=round(spike_price, 4),
                    max_size=300.0,
                    time_horizon="1h",
                    details={
                        "spike_pct": round(change * 100, 2),
                        "revert_pct": round(revert_pct * 100, 2),
                        "spike_price": spike_price,
                        "revert_price": price_history[j],
                        "base_price": base,
                    },
                )
        # If spike found but no reversion yet, break (only check first spike)
        break

    return None


# ---------------------------------------------------------------------------
# Composite scanner
# ---------------------------------------------------------------------------


async def scan_for_opportunities(
    markets: List[dict] | None = None,
) -> List[Opportunity]:
    """Run all detectors across provided markets.

    Parameters
    ----------
    markets : list[dict] | None
        List of market dicts. Each should have keys like ``yes_price``,
        ``no_price``, ``volume``, ``spread_cents``, ``price_history``,
        ``timestamps``, ``condition_id``, ``question``.

    Returns
    -------
    list[Opportunity]
        All detected opportunities, sorted by expected_value descending.
    """
    if not markets:
        return []

    opportunities: List[Opportunity] = []

    for mkt in markets:
        mid = mkt.get("condition_id", mkt.get("market_id", ""))
        title = mkt.get("question", mkt.get("title", ""))

        # Type 1 — price discrepancy
        yes_p = mkt.get("yes_price")
        no_p = mkt.get("no_price")
        if yes_p is not None and no_p is not None:
            opp = detect_price_discrepancy(yes_p, no_p, mid, title)
            if opp:
                opportunities.append(opp)

        # Type 2 — momentum
        ph = mkt.get("price_history")
        ts = mkt.get("timestamps")
        if ph and ts:
            opp = detect_momentum(ph, ts, mid, title)
            if opp:
                opportunities.append(opp)

        # Type 3 — liquidity gap
        sc = mkt.get("spread_cents")
        if sc is not None:
            opp = detect_liquidity_gap(sc, mkt, mid, title)
            if opp:
                opportunities.append(opp)

        # Type 4 — event-driven (placeholder)
        opp = detect_event_driven(mkt, mid, title)
        if opp:
            opportunities.append(opp)

        # Type 5 — emotional trading
        if ph and ts:
            opp = detect_emotional_trading(ph, ts, mid, title)
            if opp:
                opportunities.append(opp)

    opportunities.sort(key=lambda o: o.expected_value, reverse=True)
    return opportunities
