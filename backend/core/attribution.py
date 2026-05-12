"""Strategy attribution: per-strategy P&L breakdown and metrics computation."""
import math
from dataclasses import dataclass
from datetime import datetime

from backend.core.portfolio_optimizer import StrategyMetrics

from loguru import logger
@dataclass
class StrategyAttribution:
    strategy: str
    period_pnl: float
    period_trades: int
    period_win_rate: float
    contribution_pct: float  # % of total P&L from this strategy


def compute_attribution(
    trades: list,
    period_start: datetime,
    period_end: datetime,
) -> list[StrategyAttribution]:
    """Group settled trades by strategy and compute attribution for the period.

    Only settled trades whose timestamp falls within [period_start, period_end]
    are included. contribution_pct is strategy_pnl / total_pnl * 100; when
    total_pnl is 0 each strategy gets 0%.
    """
    in_period = [
        t for t in trades
        if getattr(t, "settled", False)
        and t.timestamp is not None
        and period_start <= t.timestamp <= period_end
    ]

    # Group by strategy
    groups: dict[str, list] = {}
    for t in in_period:
        key = getattr(t, "strategy", None) or "unknown"
        groups.setdefault(key, []).append(t)

    total_pnl = sum(
        (getattr(t, "pnl", None) or 0.0) for t in in_period
    )

    attributions: list[StrategyAttribution] = []
    for strategy, strat_trades in groups.items():
        pnl = sum((getattr(t, "pnl", None) or 0.0) for t in strat_trades)
        trade_count = len(strat_trades)
        wins = sum(
            1 for t in strat_trades if getattr(t, "result", None) == "win"
        )
        win_rate = wins / trade_count if trade_count > 0 else 0.0
        contribution_pct = (pnl / total_pnl * 100.0) if total_pnl != 0 else 0.0

        attributions.append(
            StrategyAttribution(
                strategy=strategy,
                period_pnl=pnl,
                period_trades=trade_count,
                period_win_rate=win_rate,
                contribution_pct=contribution_pct,
            )
        )

    logger.debug(
        "compute_attribution: %d strategies, total_pnl=%.4f over %d trades",
        len(attributions),
        total_pnl,
        len(in_period),
    )
    return attributions


def compute_strategy_metrics(trades: list, strategy_name: str) -> StrategyMetrics:
    """Compute StrategyMetrics for a named strategy from its trade history.

    Sharpe = mean(pnl_list) / std(pnl_list) * sqrt(252) when std > 0, else 0.
    Max drawdown is computed from the cumulative P&L curve.
    Average edge uses edge_at_entry when available.
    Only settled trades belonging to strategy_name are used.
    """
    strat_trades = [
        t for t in trades
        if getattr(t, "settled", False)
        and (getattr(t, "strategy", None) or "unknown") == strategy_name
    ]

    trade_count = len(strat_trades)
    pnl_list = [getattr(t, "pnl", None) or 0.0 for t in strat_trades]
    total_pnl = sum(pnl_list)

    wins = sum(1 for t in strat_trades if getattr(t, "result", None) == "win")
    win_rate = wins / trade_count if trade_count > 0 else 0.0

    # Sharpe ratio (annualised)
    if trade_count > 1:
        mean_pnl = total_pnl / trade_count
        variance = sum((p - mean_pnl) ** 2 for p in pnl_list) / (trade_count - 1)
        std_pnl = math.sqrt(variance)
        sharpe = (mean_pnl / std_pnl * math.sqrt(252)) if std_pnl > 0 else 0.0
    else:
        sharpe = 0.0

    # Max drawdown from cumulative P&L curve
    max_drawdown = _compute_max_drawdown(pnl_list)

    # Average edge at entry
    edges = [
        getattr(t, "edge_at_entry", None)
        for t in strat_trades
        if getattr(t, "edge_at_entry", None) is not None
    ]
    avg_edge = sum(edges) / len(edges) if edges else 0.0

    logger.debug(
        "compute_strategy_metrics: strategy=%s trades=%d sharpe=%.3f drawdown=%.4f",
        strategy_name,
        trade_count,
        sharpe,
        max_drawdown,
    )

    return StrategyMetrics(
        name=strategy_name,
        total_pnl=total_pnl,
        trade_count=trade_count,
        win_rate=win_rate,
        sharpe_ratio=sharpe,
        max_drawdown=max_drawdown,
        avg_edge=avg_edge,
    )


def _compute_max_drawdown(pnl_list: list[float]) -> float:
    """Return the maximum peak-to-trough drawdown from a series of P&L values."""
    if not pnl_list:
        return 0.0

    cumulative = 0.0
    peak = 0.0
    max_dd = 0.0

    for pnl in pnl_list:
        cumulative += pnl
        if cumulative > peak:
            peak = cumulative
        drawdown = peak - cumulative
        if drawdown > max_dd:
            max_dd = drawdown

    return max_dd
