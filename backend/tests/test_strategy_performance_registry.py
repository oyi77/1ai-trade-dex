"""Tests for StrategyPerformanceRegistry — strategy metrics aggregation."""

from datetime import datetime, timezone

from backend.models.database import Trade
from backend.core.strategy_performance_registry import (
    strategy_performance_registry,
    StrategyPerformanceSnapshot,
)


def test_strategy_performance_registry_updates_on_settlement(db):
    """Registry computes correct aggregates after multiple settled trades."""
    strategy = "test_strategy"

    # Create settled trades: 3 wins, 2 losses
    for direction, pnl, result in [
        ("up", 50.0, "win"),
        ("down", -25.0, "loss"),
        ("up", 75.0, "win"),
        ("down", -30.0, "loss"),
        ("up", 45.0, "win"),
    ]:
        trade = Trade(
            strategy=strategy,
            market_ticker="TEST-USD",
            direction=direction,
            size=1.0,
            entry_price=0.50,
            pnl=pnl,
            result=result,
            timestamp=datetime.now(timezone.utc),
            settlement_time=datetime.now(timezone.utc),
            settled=True,
            settlement_value=1.0 if result == "win" else 0.0,
            model_probability=0.60,
            edge_at_entry=0.10,
        )
        db.add(trade)
    db.commit()

    # Update registry from DB
    report = strategy_performance_registry.update_from_settlement(strategy, db=db)

    assert report.strategy_name == strategy
    assert report.total_trades == 5
    assert report.wins == 3
    assert report.losses == 2
    assert abs(report.win_rate - 0.6) < 1e-6
    assert report.total_pnl == 115.0  # 50+75+45 -25 -30
    assert report.gross_profit == 170.0
    assert report.gross_loss == -55.0
    assert report.profit_factor > 3.0  # 170/55 ≈ 3.09
    assert report.max_drawdown >= 0.0
    assert report.consecutive_losses == 0
    # Net profitable but below promotion thresholds (needs 30 trades minimum)
    assert report.total_pnl > 0
    assert (
        report.is_profitable is False
    )  # promotion thresholds not yet met (only 5 trades)


def test_strategy_performance_registry_snapshot_persisted(db):
    """update_from_settlement writes a StrategyPerformanceSnapshot row."""
    strategy = "persist_test"

    trade = Trade(
        strategy=strategy,
        market_ticker="TEST-USD",
        direction="up",
        size=1.0,
        entry_price=0.5,
        pnl=10.0,
        result="win",
        timestamp=datetime.now(timezone.utc),
        settlement_time=datetime.now(timezone.utc),
        settled=True,
        settlement_value=1.0,
        model_probability=0.6,
        edge_at_entry=0.1,
    )
    db.add(trade)
    db.commit()

    strategy_performance_registry.update_from_settlement(strategy, db=db)

    # Verify snapshot row exists
    snapshots = db.query(StrategyPerformanceSnapshot).filter_by(strategy=strategy).all()
    assert len(snapshots) == 1
    snap = snapshots[0]
    assert snap.total_trades == 1
    assert snap.win_rate == 1.0
    assert snap.total_pnl == 10.0
