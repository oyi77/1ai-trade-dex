"""Strategy Fingerprint -- 14-dimension profiling from trading history."""

from __future__ import annotations

import math
import statistics
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Literal


from backend.core.market_classifier import classify_market


@dataclass
class StrategyFingerprint:
    """14-dimension strategy profile derived from position history."""

    strategy_type: Literal[
        "SCALPER", "SWING", "POSITION", "WHALE", "HEDGER", "MIXED"
    ] = "MIXED"
    confidence: float = 0.0
    primary_category: str = "Other"
    primary_category_share: float = 0.0
    avg_position_size: float = 0.0
    size_strategy: Literal["FIXED", "KELLY", "VARIABLE", "UNKNOWN"] = "UNKNOWN"
    win_rate: float = 0.0
    profit_factor: float = 0.0
    sharpe_ratio: float = 0.0
    avg_hold_time_hours: float = 0.0
    hold_style: Literal["SCALPER", "SWING", "POSITION"] = "SWING"
    preferred_outcome: Literal["YES", "NO", "NEUTRAL"] = "NEUTRAL"
    preferred_side: Literal["BUY", "SELL", "NEUTRAL"] = "NEUTRAL"
    avg_price_entry: float = 0.0
    limit_order_pct: float = 0.0
    max_consecutive_losses: int = 0
    recovery_ability: float = 0.0
    is_replicable: bool = False
    replication_difficulty: Literal["EASY", "MEDIUM", "HARD"] = "MEDIUM"
    copy_trade_suitability: int = 1
    red_flags: list[str] = field(default_factory=list)
    green_flags: list[str] = field(default_factory=list)
    categories: dict = field(default_factory=dict)
    sizing_analysis: dict = field(default_factory=dict)
    timing_analysis: dict = field(default_factory=dict)


def strategy_fingerprint(positions: list[dict]) -> StrategyFingerprint:
    """Build a 14-dimension fingerprint from trading history.

    Parameters
    ----------
    positions : list[dict]
        Each dict must have: title, outcome, avgPrice, totalBought,
        realizedPnl, timestamp, slug, eventSlug.
    """
    fp = StrategyFingerprint()

    if not positions:
        return fp

    n = len(positions)

    # ------------------------------------------------------------------
    # 1. Category preference
    # ------------------------------------------------------------------
    category_counts: Counter[str] = Counter()
    for p in positions:
        title = p.get("title", "")
        slug = p.get("slug", "")
        event_slug = p.get("eventSlug", "")
        cat = classify_market(title, slug=slug, event_slug=event_slug)
        category_counts[cat] += 1

    total_cat = sum(category_counts.values())
    if total_cat > 0:
        primary, primary_count = category_counts.most_common(1)[0]
        fp.primary_category = primary
        fp.primary_category_share = primary_count / total_cat

    fp.categories = {
        cat: {"count": cnt, "share": cnt / total_cat}
        for cat, cnt in category_counts.most_common()
    }

    # ------------------------------------------------------------------
    # 2. Position sizing
    # ------------------------------------------------------------------
    sizes = [abs(p.get("totalBought", 0)) for p in positions]
    fp.avg_position_size = statistics.mean(sizes) if sizes else 0.0

    if len(sizes) >= 5:
        size_std = statistics.stdev(sizes) if len(sizes) > 1 else 0.0
        cv = size_std / fp.avg_position_size if fp.avg_position_size > 0 else 0.0
        if cv < 0.15:
            fp.size_strategy = "FIXED"
        elif cv < 0.5:
            fp.size_strategy = "KELLY"
        else:
            fp.size_strategy = "VARIABLE"
    else:
        fp.size_strategy = "UNKNOWN"

    fp.sizing_analysis = {
        "mean": fp.avg_position_size,
        "median": statistics.median(sizes) if sizes else 0.0,
        "std": statistics.stdev(sizes) if len(sizes) > 1 else 0.0,
        "cv": (
            statistics.stdev(sizes) / statistics.mean(sizes)
            if len(sizes) > 1 and statistics.mean(sizes) > 0
            else 0.0
        ),
    }

    # ------------------------------------------------------------------
    # 3. Win rate & profit factor
    # ------------------------------------------------------------------
    pnls = [p.get("realizedPnl", 0) for p in positions]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]

    fp.win_rate = len(wins) / n if n > 0 else 0.0

    gross_wins = sum(wins) if wins else 0.0
    gross_losses = abs(sum(losses)) if losses else 0.0
    if gross_losses > 0:
        fp.profit_factor = gross_wins / gross_losses
    elif gross_wins > 0:
        fp.profit_factor = 999.99  # Cap to avoid JSON serialization issues
    else:
        fp.profit_factor = 0.0

    # ------------------------------------------------------------------
    # 4. Sharpe ratio (annualized from per-trade returns)
    # ------------------------------------------------------------------
    if len(pnls) >= 2:
        mean_pnl = statistics.mean(pnls)
        std_pnl = statistics.stdev(pnls)
        if std_pnl > 0:
            # Annualize: use daily aggregation if timestamps span >1 day, else sqrt(trades)
            timestamps = sorted(
                float(p.get("timestamp", 0)) for p in positions if p.get("timestamp")
            )
            if len(timestamps) >= 2:
                days_span = max((timestamps[-1] - timestamps[0]) / 86400, 1)
                trades_per_year = len(pnls) * (365 / days_span)
                annualization = math.sqrt(trades_per_year)
            else:
                annualization = math.sqrt(252)  # fallback
            fp.sharpe_ratio = (mean_pnl / std_pnl) * annualization
        else:
            fp.sharpe_ratio = 0.0

    # ------------------------------------------------------------------
    # 5. Hold duration & style
    # ------------------------------------------------------------------
    hold_hours = _estimate_hold_times(positions)
    if hold_hours:
        fp.avg_hold_time_hours = statistics.mean(hold_hours)
    else:
        fp.avg_hold_time_hours = 0.0

    if fp.avg_hold_time_hours < 1:
        fp.hold_style = "SCALPER"
    elif fp.avg_hold_time_hours < 24:
        fp.hold_style = "SWING"
    else:
        fp.hold_style = "POSITION"

    # ------------------------------------------------------------------
    # 6. Outcome preference (YES vs NO)
    # ------------------------------------------------------------------
    outcome_counts: Counter[str] = Counter()
    for p in positions:
        o = (p.get("outcome") or "").upper()
        if o in ("YES", "NO"):
            outcome_counts[o] += 1
    total_outcomes = sum(outcome_counts.values())
    if total_outcomes > 0:
        fp.preferred_outcome = (
            "YES" if outcome_counts["YES"] >= outcome_counts["NO"] else "NO"
        )
    else:
        fp.preferred_outcome = "NEUTRAL"

    # ------------------------------------------------------------------
    # 7. Side preference (BUY vs SELL)
    # ------------------------------------------------------------------
    side_counts: Counter[str] = Counter()
    for p in positions:
        s = (p.get("side") or "BUY").upper()
        if s in ("BUY", "SELL"):
            side_counts[s] += 1
    total_sides = sum(side_counts.values())
    if total_sides > 0:
        fp.preferred_side = (
            "BUY" if side_counts["BUY"] >= side_counts["SELL"] else "SELL"
        )
    else:
        fp.preferred_side = "NEUTRAL"

    # ------------------------------------------------------------------
    # 8. Price sensitivity
    # ------------------------------------------------------------------
    prices = [p.get("avgPrice", 0) for p in positions if p.get("avgPrice")]
    fp.avg_price_entry = statistics.mean(prices) if prices else 0.0

    # ------------------------------------------------------------------
    # 9. Limit order estimate
    # ------------------------------------------------------------------
    limit_like = sum(1 for p in prices if p not in (0.0, 0.5, 1.0))
    fp.limit_order_pct = limit_like / len(prices) if prices else 0.0

    # ------------------------------------------------------------------
    # 10. Consecutive losses & recovery
    # ------------------------------------------------------------------
    fp.max_consecutive_losses = _max_consecutive_losses(pnls)

    if gross_losses > 0 and gross_wins > 0:
        fp.recovery_ability = min(1.0, gross_wins / (gross_losses * 2))
    elif gross_wins > 0:
        fp.recovery_ability = 1.0
    else:
        fp.recovery_ability = 0.0

    # ------------------------------------------------------------------
    # 11. Entry timing analysis
    # ------------------------------------------------------------------
    hour_counts: Counter[int] = Counter()
    dow_counts: Counter[int] = Counter()
    for p in positions:
        ts = p.get("timestamp")
        if ts:
            try:
                dt = datetime.fromtimestamp(ts, tz=timezone.utc)
                hour_counts[dt.hour] += 1
                dow_counts[dt.weekday()] += 1
            except (OSError, ValueError):
                pass
    fp.timing_analysis = {
        "hour_distribution": dict(hour_counts),
        "dow_distribution": dict(dow_counts),
        "peak_hour": hour_counts.most_common(1)[0][0] if hour_counts else None,
        "peak_dow": dow_counts.most_common(1)[0][0] if dow_counts else None,
    }

    # ------------------------------------------------------------------
    # 12. Strategy type classification
    # ------------------------------------------------------------------
    fp.strategy_type = _classify_strategy_type(
        n,
        fp.avg_position_size,
        fp.avg_hold_time_hours,
        fp.avg_price_entry,
        sizes,
        pnls,
    )

    # ------------------------------------------------------------------
    # 13. Confidence (sample-size based)
    # ------------------------------------------------------------------
    fp.confidence = _compute_confidence(n, fp.win_rate)

    # ------------------------------------------------------------------
    # 14. Red / green flags
    # ------------------------------------------------------------------
    fp.red_flags = _detect_red_flags(positions, pnls, n, fp)
    fp.green_flags = _detect_green_flags(n, fp)

    # ------------------------------------------------------------------
    # Replicability & copy-trade suitability
    # ------------------------------------------------------------------
    fp.is_replicable = n >= 30 and fp.win_rate >= 0.45 and fp.confidence >= 0.5
    if fp.is_replicable:
        if fp.confidence >= 0.8 and fp.win_rate >= 0.52:
            fp.replication_difficulty = "EASY"
        else:
            fp.replication_difficulty = "MEDIUM"
    else:
        fp.replication_difficulty = "HARD"

    fp.copy_trade_suitability = _copy_trade_score(fp)

    return fp


# ======================================================================
# Internal helpers
# ======================================================================


def _estimate_hold_times(positions: list[dict]) -> list[float]:
    """Estimate hold duration (hours) from consecutive timestamp gaps."""
    timestamps = sorted(
        (p.get("timestamp", 0) for p in positions if p.get("timestamp")),
    )
    if len(timestamps) < 2:
        return []
    return [
        (timestamps[i + 1] - timestamps[i]) / 3600
        for i in range(len(timestamps) - 1)
        if timestamps[i + 1] > timestamps[i]
    ]


def _max_consecutive_losses(pnls: list[float]) -> int:
    """Longest streak of negative PnL trades."""
    streak = 0
    max_streak = 0
    for p in pnls:
        if p < 0:
            streak += 1
            max_streak = max(max_streak, streak)
        else:
            streak = 0
    return max_streak


def _classify_strategy_type(
    n: int,
    avg_size: float,
    avg_hold_hrs: float,
    avg_price: float,
    sizes: list[float],
    pnls: list[float],
) -> str:
    """Classify the overarching strategy type."""
    # Whale: few very large trades
    if n <= 20 and avg_size > 500:
        return "WHALE"

    # Scalper: many small, short hold
    if n >= 30 and avg_hold_hrs < 1 and avg_size < 100:
        return "SCALPER"

    # Hedger: trades both sides near 0.50
    if avg_price > 0.40 and avg_price < 0.60 and n >= 10:
        sizes_near_half = sum(1 for s in sizes if 0.40 < s / max(avg_size, 1) < 0.60)
        if sizes_near_half / max(n, 1) > 0.6:
            return "HEDGER"

    # Position: long hold
    if avg_hold_hrs >= 24:
        return "POSITION"

    # Swing: moderate hold, moderate size
    if avg_hold_hrs >= 1:
        return "SWING"

    return "MIXED"


def _compute_confidence(n: int, win_rate: float) -> float:
    """Confidence 0-1 based on sample size and consistency."""
    if n < 5:
        return 0.0
    if n < 20:
        base = 0.2
    elif n < 50:
        base = 0.5
    elif n < 100:
        base = 0.65
    elif n < 200:
        base = 0.75
    else:
        base = 0.85

    # Bonus for non-degenerate win rates (closer to 0.5 is less informative)
    edge_bonus = min(0.15, abs(win_rate - 0.5) * 0.5)
    return min(1.0, base + edge_bonus)


def _detect_red_flags(
    positions: list[dict], pnls: list[float], n: int, fp: StrategyFingerprint
) -> list[str]:
    """Detect warning signs in trading history."""
    flags: list[str] = []

    if n < 20:
        flags.append("small sample")

    if n > 0:
        max_pnl = max(pnls) if pnls else 0
        total_pnl = sum(pnls)
        if max_pnl > 500 and total_pnl > 0 and max_pnl / total_pnl > 0.7:
            flags.append("lucky trade")

    if n >= 20 and fp.max_consecutive_losses >= max(5, n * 0.2):
        flags.append("extended losing streak")

    if fp.primary_category_share > 0.95 and n >= 10:
        flags.append("no diversification")

    return flags


def _detect_green_flags(n: int, fp: StrategyFingerprint) -> list[str]:
    """Detect positive signals in trading history."""
    flags: list[str] = []

    if n >= 500:
        flags.append("large sample")

    if fp.win_rate >= 0.53 and n >= 50:
        flags.append("consistent win rate")

    if fp.profit_factor >= 1.5 and n >= 30:
        flags.append("strong profit factor")

    if fp.max_consecutive_losses <= 3 and n >= 20:
        flags.append("low drawdown")

    if fp.sharpe_ratio > 1.0 and n >= 30:
        flags.append("good risk-adjusted returns")

    return flags


def _copy_trade_score(fp: StrategyFingerprint) -> int:
    """Composite copy-trade suitability score 1-10."""
    score = 1

    # Sample size
    if fp.confidence >= 0.8:
        score += 3
    elif fp.confidence >= 0.5:
        score += 2
    elif fp.confidence >= 0.3:
        score += 1

    # Win rate
    if fp.win_rate >= 0.55:
        score += 2
    elif fp.win_rate >= 0.50:
        score += 1

    # Profit factor
    if fp.profit_factor >= 2.0:
        score += 2
    elif fp.profit_factor >= 1.2:
        score += 1

    # No red flags
    if not fp.red_flags:
        score += 1

    # Replicable
    if fp.is_replicable:
        score += 1

    return min(10, max(1, score))
