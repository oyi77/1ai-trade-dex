from datetime import datetime, timedelta, timezone

from backend.core.profitability_gates import (
    compute_profitability_metrics,
    evaluate_profitability_gate,
)
from backend.models.database import Trade


def make_trade(index: int, pnl: float, strategy: str = "gate_strategy") -> Trade:
    return Trade(
        id=index,
        market_ticker=f"gate-{index}",
        platform="polymarket",
        strategy=strategy,
        trading_mode="paper",
        direction="up",
        entry_price=0.5,
        size=10.0,
        timestamp=datetime.now(timezone.utc) + timedelta(minutes=index),
        settled=True,
        result="win" if pnl > 0 else "loss",
        pnl=pnl,
    )


def test_profitability_metrics_capture_outlier_dependence():
    trades = [make_trade(1, 100.0), make_trade(2, -10.0), make_trade(3, -10.0)]

    metrics = compute_profitability_metrics(trades)

    assert metrics.total_pnl == 80.0
    assert metrics.profit_factor == 5.0
    assert metrics.top_trade_pnl_share == 1.25


def test_profitability_gate_blocks_lucky_outlier_strategy():
    trades = [make_trade(1, 100.0)] + [make_trade(i, -1.0) for i in range(2, 52)]

    result = evaluate_profitability_gate(
        trades,
        min_trades=50,
        min_profit_factor=1.2,
        max_drawdown=100.0,
        max_top_trade_pnl_share=0.40,
    )

    assert result.passed is False
    assert any("top_trade_pnl_share" in reason for reason in result.reasons)


def test_profitability_gate_allows_distributed_positive_edge():
    trades = [make_trade(i, 2.0 if i % 2 else -1.0) for i in range(1, 61)]

    result = evaluate_profitability_gate(
        trades,
        min_trades=50,
        min_profit_factor=1.2,
        max_drawdown=20.0,
        max_top_trade_pnl_share=0.40,
    )

    assert result.passed is True
    assert result.reasons == []
