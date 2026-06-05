from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from sqlalchemy.orm import Session

from backend.models.database import Trade


@dataclass(frozen=True)
class ProfitabilityMetrics:
    trade_count: int
    total_pnl: float
    win_rate: float
    profit_factor: float
    max_drawdown: float
    top_trade_pnl_share: float


@dataclass(frozen=True)
class ProfitabilityGateResult:
    passed: bool
    reasons: list[str]
    metrics: ProfitabilityMetrics


def compute_profitability_metrics(trades: Iterable[Trade]) -> ProfitabilityMetrics:
    ordered = sorted(
        [trade for trade in trades if trade.pnl is not None],
        key=lambda trade: (trade.timestamp is None, trade.timestamp, trade.id or 0),
    )
    pnls = [float(trade.pnl or 0.0) for trade in ordered]
    wins = [pnl for pnl in pnls if pnl > 0]
    losses = [pnl for pnl in pnls if pnl < 0]
    total_pnl = sum(pnls)
    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else float("inf")

    peak = 0.0
    cumulative = 0.0
    max_drawdown_usd = 0.0
    for pnl in pnls:
        cumulative += pnl
        peak = max(peak, cumulative)
        max_drawdown_usd = max(max_drawdown_usd, peak - cumulative)

    abs_profit = abs(total_pnl)
    top_trade = max((abs(pnl) for pnl in pnls), default=0.0)
    top_share = top_trade / abs_profit if abs_profit > 0 else 0.0
    return ProfitabilityMetrics(
        trade_count=len(pnls),
        total_pnl=round(total_pnl, 6),
        win_rate=round(len(wins) / len(pnls), 6) if pnls else 0.0,
        profit_factor=round(profit_factor, 6) if profit_factor != float("inf") else profit_factor,
        max_drawdown=round(max_drawdown_usd, 6),
        top_trade_pnl_share=round(top_share, 6),
    )


def evaluate_profitability_gate(
    trades: Iterable[Trade],
    min_trades: int = 50,
    min_profit_factor: float = 1.20,
    max_drawdown: float = 100.0,
    max_top_trade_pnl_share: float = 0.40,
) -> ProfitabilityGateResult:
    metrics = compute_profitability_metrics(trades)
    reasons: list[str] = []
    if metrics.trade_count < min_trades:
        reasons.append(f"trades {metrics.trade_count} < {min_trades}")
    if metrics.profit_factor < min_profit_factor:
        reasons.append(
            f"profit_factor {metrics.profit_factor:.2f} < {min_profit_factor:.2f}"
        )
    if metrics.max_drawdown > max_drawdown:
        reasons.append(f"max_drawdown {metrics.max_drawdown:.2f} > {max_drawdown:.2f}")
    if metrics.top_trade_pnl_share > max_top_trade_pnl_share:
        reasons.append(
            f"top_trade_pnl_share {metrics.top_trade_pnl_share:.2f} > {max_top_trade_pnl_share:.2f}"
        )
    return ProfitabilityGateResult(passed=not reasons, reasons=reasons, metrics=metrics)


def evaluate_strategy_paper_gate(
    db: Session, strategy_name: str, min_trades: int = 50
) -> ProfitabilityGateResult:
    trades = (
        db.query(Trade)
        .filter(
            Trade.strategy == strategy_name,
            Trade.trading_mode == "paper",
            Trade.settled.is_(True),
            Trade.pnl.isnot(None),
        )
        .order_by(Trade.timestamp.asc(), Trade.id.asc())
        .all()
    )
    return evaluate_profitability_gate(trades, min_trades=min_trades)
