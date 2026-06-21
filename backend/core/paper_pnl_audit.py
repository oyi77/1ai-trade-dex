from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from sqlalchemy.orm import Session

from backend.core.settlement.settlement_helpers import calculate_pnl
from backend.models.database import Trade


@dataclass(frozen=True)
class PnlMismatch:
    trade_id: int
    market_ticker: str | None
    current_pnl: float
    recomputed_pnl: float
    delta: float
    entry_price: float | None
    size: float | None


@dataclass(frozen=True)
class PaperPnlAuditReport:
    mode: str
    trade_count: int
    current_total_pnl: float
    recomputed_total_pnl: float
    delta_total_pnl: float
    mismatch_count: int
    largest_outlier_pnl: float
    top_outlier_share: float
    top_mismatches: list[PnlMismatch]


@dataclass(frozen=True)
class PaperPnlApplyResult:
    report_before: PaperPnlAuditReport
    updated_trade_count: int
    recalculated_bot_state: bool


def _settlement_value_for_trade(trade: Trade) -> float | None:
    # Early exits (see ADR-017) realize a partial pnl via calculate_exit_pnl,
    # not a binary settlement value — skip recompute to avoid false-positive
    # mismatches against the full-binary calculate_pnl result.
    if trade.settlement_source and str(trade.settlement_source).startswith("early_exit_"):
        return None
    if trade.settlement_value is not None:
        return float(trade.settlement_value)
    direction = (trade.direction or "").strip().lower()
    if trade.result == "win":
        return 0.0 if direction in {"down", "no", "sell"} else 1.0
    if trade.result == "loss":
        return 1.0 if direction in {"down", "no", "sell"} else 0.0
    if trade.result in {"push", "expired", "closed", "expired_unresolved"}:
        return float(trade.entry_price or 0.0)
    return None


def audit_trades(
    trades: Iterable[Trade], mismatch_tolerance: float = 0.01, top_n: int = 10
) -> PaperPnlAuditReport:
    trade_list = list(trades)
    current_total = 0.0
    recomputed_total = 0.0
    mismatches: list[PnlMismatch] = []
    outlier_pnls: list[float] = []

    for trade in trade_list:
        current_pnl = float(trade.pnl or 0.0)
        current_total += current_pnl
        outlier_pnls.append(abs(current_pnl))
        settlement_value = _settlement_value_for_trade(trade)
        if settlement_value is None:
            recomputed_pnl = current_pnl
        else:
            recomputed_pnl = calculate_pnl(trade, settlement_value)
        recomputed_total += recomputed_pnl
        delta = recomputed_pnl - current_pnl
        if abs(delta) > mismatch_tolerance:
            mismatches.append(
                PnlMismatch(
                    trade_id=int(trade.id or 0),
                    market_ticker=trade.market_ticker,
                    current_pnl=round(current_pnl, 6),
                    recomputed_pnl=round(recomputed_pnl, 6),
                    delta=round(delta, 6),
                    entry_price=trade.entry_price,
                    size=trade.size,
                )
            )

    abs_total_pnl = sum(outlier_pnls)
    largest_outlier = max(outlier_pnls) if outlier_pnls else 0.0
    top_outlier_share = largest_outlier / abs_total_pnl if abs_total_pnl > 0 else 0.0
    top_mismatches = sorted(mismatches, key=lambda item: abs(item.delta), reverse=True)[
        :top_n
    ]
    return PaperPnlAuditReport(
        mode="paper",
        trade_count=len(trade_list),
        current_total_pnl=round(current_total, 6),
        recomputed_total_pnl=round(recomputed_total, 6),
        delta_total_pnl=round(recomputed_total - current_total, 6),
        mismatch_count=len(mismatches),
        largest_outlier_pnl=round(largest_outlier, 6),
        top_outlier_share=round(top_outlier_share, 6),
        top_mismatches=top_mismatches,
    )


def audit_paper_pnl(
    db: Session, limit: int | None = None, top_n: int = 10
) -> PaperPnlAuditReport:
    query = (
        db.query(Trade)
        .filter(
            Trade.trading_mode == "paper",
            Trade.settled.is_(True),
            Trade.pnl.isnot(None),
        )
        .order_by(Trade.timestamp.asc(), Trade.id.asc())
    )
    if limit is not None:
        query = query.limit(limit)
    return audit_trades(query.all(), top_n=top_n)


def apply_paper_pnl_recalculation(
    db: Session,
    mismatch_tolerance: float = 0.01,
    limit: int | None = None,
    top_n: int = 10,
) -> PaperPnlApplyResult:
    query = (
        db.query(Trade)
        .filter(
            Trade.trading_mode == "paper",
            Trade.settled.is_(True),
            Trade.pnl.isnot(None),
        )
        .order_by(Trade.timestamp.asc(), Trade.id.asc())
    )
    if limit is not None:
        query = query.limit(limit)
    trades = query.all()
    report_before = audit_trades(
        trades, mismatch_tolerance=mismatch_tolerance, top_n=top_n
    )
    updated = 0
    for trade in trades:
        settlement_value = _settlement_value_for_trade(trade)
        if settlement_value is None:
            continue
        recomputed_pnl = calculate_pnl(trade, settlement_value)
        current_pnl = float(trade.pnl or 0.0)
        if abs(recomputed_pnl - current_pnl) <= mismatch_tolerance:
            continue
        trade.pnl = recomputed_pnl
        updated += 1

    recalculated_bot_state = False
    if updated:
        from backend.core.wallet.bankroll_reconciliation import reconcile_bot_state

        db.flush()
        import asyncio

        try:
            asyncio.get_running_loop()
        except RuntimeError:
            asyncio.run(
                reconcile_bot_state(
                    db,
                    modes=("paper",),
                    apply=True,
                    commit=False,
                    source="paper_pnl_recalculation",
                )
            )
        else:
            raise RuntimeError(
                "apply_paper_pnl_recalculation cannot run inside an active event loop"
            )
        recalculated_bot_state = True
    return PaperPnlApplyResult(
        report_before=report_before,
        updated_trade_count=updated,
        recalculated_bot_state=recalculated_bot_state,
    )
