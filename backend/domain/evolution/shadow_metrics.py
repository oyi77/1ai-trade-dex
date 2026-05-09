"""Shared metric calculations for settled shadow trades."""

from math import sqrt


def compute_shadow_metrics(settled_trades) -> dict:
    """Compute per-genome metrics from settled shadow trades."""
    if not settled_trades:
        return {
            "total_trades": 0,
            "winning_trades": 0,
            "losing_trades": 0,
            "win_rate": 0.0,
            "total_pnl": 0.0,
            "avg_pnl": 0.0,
            "avg_win": 0.0,
            "avg_loss": 0.0,
            "sharpe_ratio": 0.0,
            "max_drawdown_pct": 0.0,
            "volatility": 0.0,
            "profit_factor": 0.0,
        }

    pnl_values = [float(t.pnl or 0.0) for t in settled_trades]
    wins = [p for p in pnl_values if p > 0]
    losses = [p for p in pnl_values if p <= 0]
    total_pnl = sum(pnl_values)
    avg_pnl = total_pnl / len(pnl_values)
    variance = sum((p - avg_pnl) ** 2 for p in pnl_values) / len(pnl_values) if len(pnl_values) > 1 else 0.0
    volatility = sqrt(max(0.0, variance))
    sharpe_ratio = (avg_pnl / volatility) * sqrt(252) if volatility > 0 else 0.0

    gross_profit = sum(wins)
    gross_loss = abs(sum(p for p in losses if p < 0))
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else gross_profit

    equity = 1.0
    peak = 1.0
    max_drawdown_pct = 0.0
    for trade in settled_trades:
        trade_size = float(trade.size or 0.0)
        trade_return = (float(trade.pnl or 0.0) / trade_size) if trade_size > 0 else 0.0
        equity *= max(0.0, 1.0 + trade_return)
        peak = max(peak, equity)
        drawdown_pct = ((peak - equity) / peak) if peak > 0 else 0.0
        max_drawdown_pct = max(max_drawdown_pct, drawdown_pct)

    return {
        "total_trades": len(settled_trades),
        "winning_trades": len(wins),
        "losing_trades": len(losses),
        "win_rate": len(wins) / len(settled_trades),
        "total_pnl": total_pnl,
        "avg_pnl": avg_pnl,
        "avg_win": sum(wins) / len(wins) if wins else 0.0,
        "avg_loss": sum(losses) / len(losses) if losses else 0.0,
        "sharpe_ratio": sharpe_ratio,
        "max_drawdown_pct": max_drawdown_pct,
        "volatility": volatility,
        "profit_factor": profit_factor,
    }
