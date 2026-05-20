"""Wallet Analyzer — Full PnL, win rate, Sharpe, strategy/category breakdown for any Polymarket wallet."""

from __future__ import annotations

import logging
import math
import statistics
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import numpy as np

from backend.core.market_classifier import classify_market
from backend.data.wallet_history import get_all_closed_positions

logger = logging.getLogger(__name__)

# Minimum sample size before flagging
_MIN_SAMPLE_FLAG = 10


@dataclass
class WalletAnalysis:
    """Complete wallet performance analysis."""

    # Basic
    wallet: str = ""
    total_positions: int = 0
    total_volume: float = 0.0
    total_pnl: float = 0.0
    analyzed_at: str = ""

    # Performance
    win_rate: float = 0.0
    wins: int = 0
    losses: int = 0
    avg_win: float = 0.0
    avg_loss: float = 0.0
    profit_factor: float = 0.0
    expected_value: float = 0.0
    sharpe_ratio: float = 0.0
    max_drawdown: float = 0.0
    recovery_factor: float = 0.0

    # Biggest trades
    biggest_win: dict[str, Any] = field(default_factory=dict)
    biggest_loss: dict[str, Any] = field(default_factory=dict)
    top_10_wins: list[dict[str, Any]] = field(default_factory=list)
    worst_10_losses: list[dict[str, Any]] = field(default_factory=list)

    # Category breakdown: category -> {positions, pnl, wins, losses, win_rate, profit_factor}
    categories: dict[str, dict[str, Any]] = field(default_factory=dict)
    best_category: str = ""
    worst_category: str = ""

    # Temporal
    hourly_performance: dict[int, float] = field(default_factory=dict)
    daily_performance: dict[str, float] = field(default_factory=dict)
    monthly_performance: dict[str, float] = field(default_factory=dict)
    best_hour: int = -1
    worst_hour: int = -1
    best_day: str = ""
    worst_day: str = ""

    # Size
    avg_position_size: float = 0.0
    median_position_size: float = 0.0
    min_position_size: float = 0.0
    max_position_size: float = 0.0
    size_brackets: dict[str, int] = field(default_factory=dict)

    # Outcome bias
    yes_no_ratio: float = 0.0
    yes_win_rate: float = 0.0
    no_win_rate: float = 0.0

    # Risk
    var_95: float = 0.0
    var_99: float = 0.0
    consecutive_losses_max: int = 0
    consecutive_wins_max: int = 0

    # Verdict
    verdict: str = "BREAK-EVEN"
    copy_trade_rating: int = 0
    red_flags: list[str] = field(default_factory=list)


def _safe_div(num: float, den: float, default: float = 0.0) -> float:
    if not den:
        return default
    result = num / den
    return result if math.isfinite(result) else default


def _pnl(pos: dict) -> float:
    return float(pos.get("realizedPnl", 0))


def _volume(pos: dict) -> float:
    return float(pos.get("totalBought", 0))


def _title(pos: dict) -> str:
    return pos.get("title", "")


def _timestamp(pos: dict) -> float:
    return float(pos.get("timestamp", 0))


def _outcome(pos: dict) -> str:
    """Return 'Yes' or 'No' based on position side."""
    side = pos.get("outcome", pos.get("side", ""))
    if isinstance(side, str):
        return "Yes" if side.lower() in ("yes", "true", "1") else "No"
    return "Yes"


def _classify(pos: dict) -> str:
    """Classify a position by its market title."""
    return classify_market(
        title=_title(pos),
        slug=pos.get("slug", ""),
        event_slug=pos.get("eventSlug", ""),
        tags=pos.get("tags", []),
    )


# ---------------------------------------------------------------------------
# Core analysis
# ---------------------------------------------------------------------------


def compute_analysis(
    wallet: str, positions: list[dict], detailed: bool = True
) -> WalletAnalysis:
    """Build a WalletAnalysis from a list of closed position dicts."""
    result = WalletAnalysis(
        wallet=wallet,
        analyzed_at=datetime.now(timezone.utc).isoformat(),
    )

    if not positions:
        return result

    pnls = [_pnl(p) for p in positions]
    volumes = [_volume(p) for p in positions]
    wins_list = [p for p in positions if _pnl(p) > 0]
    losses_list = [p for p in positions if _pnl(p) < 0]
    win_pnls = [_pnl(p) for p in wins_list]
    loss_pnls = [_pnl(p) for p in losses_list]
    gross_wins = sum(win_pnls)
    gross_losses = abs(sum(loss_pnls))

    # --- Basic ---
    result.total_positions = len(positions)
    result.total_volume = sum(volumes)
    result.total_pnl = sum(pnls)

    # --- Performance ---
    result.wins = len(wins_list)
    result.losses = len(losses_list)
    result.win_rate = _safe_div(result.wins, result.total_positions)  # ratio 0-1
    result.avg_win = _safe_div(gross_wins, result.wins)
    result.avg_loss = _safe_div(gross_losses, result.losses)
    result.profit_factor = _safe_div(gross_wins, gross_losses)
    result.expected_value = _safe_div(result.total_pnl, result.total_positions)

    # Max drawdown: running peak - running trough
    running = 0.0
    peak = 0.0
    max_dd = 0.0
    for p in pnls:
        running += p
        if running > peak:
            peak = running
        dd = peak - running
        if dd > max_dd:
            max_dd = dd
    result.max_drawdown = max_dd
    result.recovery_factor = _safe_div(result.total_pnl, max_dd)

    # Sharpe ratio: mean(daily_returns) / std(daily_returns) * sqrt(252)
    daily_returns: dict[str, float] = {}
    for p in positions:
        ts = _timestamp(p)
        if ts > 0:
            day_key = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")
            daily_returns[day_key] = daily_returns.get(day_key, 0.0) + _pnl(p)

    daily_vals = list(daily_returns.values())
    if len(daily_vals) >= 2:
        mean_r = float(np.mean(daily_vals))
        std_r = float(np.std(daily_vals, ddof=1))
        result.sharpe_ratio = _safe_div(mean_r, std_r) * np.sqrt(252)
    elif len(daily_vals) == 1:
        result.sharpe_ratio = 0.0

    # VaR: percentile of per-trade PnL
    if pnls:
        result.var_95 = float(np.percentile(pnls, 5))
        result.var_99 = float(np.percentile(pnls, 1))

    # --- Biggest trades ---
    sorted_wins = sorted(wins_list, key=_pnl, reverse=True)
    sorted_losses = sorted(losses_list, key=_pnl)
    if sorted_wins:
        best = sorted_wins[0]
        result.biggest_win = {
            "title": _title(best),
            "pnl": _pnl(best),
            "timestamp": _timestamp(best),
        }
        result.top_10_wins = [
            {"title": _title(p), "pnl": _pnl(p)} for p in sorted_wins[:10]
        ]
    if sorted_losses:
        worst = sorted_losses[0]
        result.biggest_loss = {
            "title": _title(worst),
            "pnl": _pnl(worst),
            "timestamp": _timestamp(worst),
        }
        result.worst_10_losses = [
            {"title": _title(p), "pnl": _pnl(p)} for p in sorted_losses[:10]
        ]

    # --- Consecutive streaks ---
    streak_losses = 0
    streak_wins = 0
    max_loss_streak = 0
    max_win_streak = 0
    for p in positions:
        if _pnl(p) < 0:
            streak_losses += 1
            streak_wins = 0
            max_loss_streak = max(max_loss_streak, streak_losses)
        elif _pnl(p) > 0:
            streak_wins += 1
            streak_losses = 0
            max_win_streak = max(max_win_streak, streak_wins)
        else:
            streak_losses = 0
            streak_wins = 0
    result.consecutive_losses_max = max_loss_streak
    result.consecutive_wins_max = max_win_streak

    if not detailed:
        # Rapid mode: skip temporal, size, category breakdown
        _assign_verdict(result)
        _assign_copy_rating(result)
        _assign_red_flags(result)
        return result

    # --- Category breakdown ---
    cat_map: dict[str, list[dict]] = {}
    for p in positions:
        cat = _classify(p)
        cat_map.setdefault(cat, []).append(p)

    best_cat_pnl = float("-inf")
    worst_cat_pnl = float("inf")
    for cat, cat_positions in cat_map.items():
        cp = [_pnl(p) for p in cat_positions]
        cw = [p for p in cat_positions if _pnl(p) > 0]
        cl = [p for p in cat_positions if _pnl(p) < 0]
        cat_gross_w = sum(_pnl(p) for p in cw)
        cat_gross_l = abs(sum(_pnl(p) for p in cl))
        cat_total = sum(cp)
        result.categories[cat] = {
            "positions": len(cat_positions),
            "pnl": cat_total,
            "wins": len(cw),
            "losses": len(cl),
            "win_rate": _safe_div(len(cw), len(cat_positions)),  # ratio 0-1
            "profit_factor": _safe_div(cat_gross_w, cat_gross_l),
        }
        if cat_total > best_cat_pnl:
            best_cat_pnl = cat_total
            result.best_category = cat
        if cat_total < worst_cat_pnl:
            worst_cat_pnl = cat_total
            result.worst_category = cat

    # --- Temporal ---
    hourly: dict[int, list[float]] = {}
    daily: dict[str, list[float]] = {}
    monthly: dict[str, list[float]] = {}
    for p in positions:
        ts = _timestamp(p)
        if ts <= 0:
            continue
        dt = datetime.fromtimestamp(ts, tz=timezone.utc)
        hourly.setdefault(dt.hour, []).append(_pnl(p))
        daily.setdefault(dt.strftime("%A"), []).append(_pnl(p))
        monthly.setdefault(dt.strftime("%Y-%m"), []).append(_pnl(p))

    for h, vals in hourly.items():
        result.hourly_performance[h] = sum(vals)
    for d, vals in daily.items():
        result.daily_performance[d] = sum(vals)
    for m, vals in monthly.items():
        result.monthly_performance[m] = sum(vals)

    if result.hourly_performance:
        result.best_hour = max(result.hourly_performance, key=result.hourly_performance.get)  # type: ignore[arg-type]
        result.worst_hour = min(result.hourly_performance, key=result.hourly_performance.get)  # type: ignore[arg-type]
    if result.daily_performance:
        result.best_day = max(result.daily_performance, key=result.daily_performance.get)  # type: ignore[arg-type]
        result.worst_day = min(result.daily_performance, key=result.daily_performance.get)  # type: ignore[arg-type]

    # --- Size ---
    if volumes:
        result.avg_position_size = statistics.mean(volumes)
        result.median_position_size = statistics.median(volumes)
        result.min_position_size = min(volumes)
        result.max_position_size = max(volumes)

        brackets = {"<10": 0, "10-50": 0, "50-100": 0, "100-500": 0, "500+": 0}
        for v in volumes:
            if v < 10:
                brackets["<10"] += 1
            elif v < 50:
                brackets["10-50"] += 1
            elif v < 100:
                brackets["50-100"] += 1
            elif v < 500:
                brackets["100-500"] += 1
            else:
                brackets["500+"] += 1
        result.size_brackets = brackets

    # --- Outcome bias ---
    yes_positions = [p for p in positions if _outcome(p) == "Yes"]
    no_positions = [p for p in positions if _outcome(p) == "No"]
    yes_count = len(yes_positions)
    no_count = len(no_positions)
    result.yes_no_ratio = _safe_div(yes_count, no_count)
    result.yes_win_rate = _safe_div(
        sum(1 for p in yes_positions if _pnl(p) > 0),
        yes_count,
    )  # ratio 0-1
    result.no_win_rate = _safe_div(
        sum(1 for p in no_positions if _pnl(p) > 0),
        no_count,
    )  # ratio 0-1

    _assign_verdict(result)
    _assign_copy_rating(result)
    _assign_red_flags(result)
    return result


def _assign_verdict(result: WalletAnalysis) -> None:
    if result.total_positions == 0:
        result.verdict = "BREAK-EVEN"
    elif result.total_pnl > 0 and result.win_rate >= 0.50:
        result.verdict = "PROFITABLE"
    elif result.total_pnl < 0:
        result.verdict = "LOSING"
    else:
        result.verdict = "BREAK-EVEN"


def _assign_copy_rating(result: WalletAnalysis) -> None:
    """Rate 1-10 based on WR, PF, sample size, drawdown."""
    if result.total_positions == 0:
        result.copy_trade_rating = 0
        return

    score = 0

    # Win rate contribution (0-3) — win_rate is ratio 0-1
    if result.win_rate >= 0.60:
        score += 3
    elif result.win_rate >= 0.50:
        score += 2
    elif result.win_rate >= 0.40:
        score += 1

    # Profit factor contribution (0-3)
    if result.profit_factor >= 2.0:
        score += 3
    elif result.profit_factor >= 1.5:
        score += 2
    elif result.profit_factor >= 1.0:
        score += 1

    # Sample size contribution (0-2)
    if result.total_positions >= 100:
        score += 2
    elif result.total_positions >= 30:
        score += 1

    # Drawdown penalty (0-2)
    if result.max_drawdown > 0 and result.total_pnl > 0:
        dd_ratio = result.max_drawdown / result.total_pnl
        if dd_ratio < 1.0:
            score += 2
        elif dd_ratio < 2.0:
            score += 1

    result.copy_trade_rating = min(max(score, 1), 10)


def _assign_red_flags(result: WalletAnalysis) -> None:
    flags: list[str] = []
    if result.total_positions < _MIN_SAMPLE_FLAG:
        flags.append(f"Small sample size ({result.total_positions} positions)")
    if result.profit_factor > 0 and result.profit_factor < 1.0:
        flags.append(f"Profit factor below 1 ({result.profit_factor:.2f})")
    if result.max_drawdown > 0 and result.total_pnl > 0:
        if result.max_drawdown / result.total_pnl > 3.0:
            flags.append("Extreme drawdown relative to profits")
    if result.consecutive_losses_max >= 10:
        flags.append(f"Long losing streak ({result.consecutive_losses_max})")
    if result.win_rate < 0.30 and result.total_positions >= 10:
        flags.append(f"Very low win rate ({result.win_rate:.1%})")
    result.red_flags = flags


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def analyze_wallet(proxy_wallet: str, detailed: bool = True) -> WalletAnalysis:
    """Full wallet analysis with category, temporal, and size breakdowns."""
    positions = await get_all_closed_positions(proxy_wallet)
    return compute_analysis(proxy_wallet, positions, detailed=detailed)


async def analyze_wallet_rapid(proxy_wallet: str) -> WalletAnalysis:
    """Lightweight analysis — skips temporal, size, and category breakdowns."""
    return await analyze_wallet(proxy_wallet, detailed=False)


async def compare_wallets(wallets: list[str]) -> list[WalletAnalysis]:
    """Analyze multiple wallets and return sorted by total_pnl descending."""
    results: list[WalletAnalysis] = []
    for w in wallets:
        analysis = await analyze_wallet(w)
        results.append(analysis)
    results.sort(key=lambda a: a.total_pnl, reverse=True)
    return results
