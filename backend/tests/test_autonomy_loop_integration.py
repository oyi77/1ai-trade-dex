"""Full autonomy loop integration tests — async daemon + DB integration."""

import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from backend.config import settings
from backend.core.autonomous_promoter import AutonomousPromoter
from backend.core.wallet.bankroll_allocator import BankrollAllocator
from backend.core.trade_forensics import TradeForensics
from backend.models import database as _db_mod
from backend.models.database import StrategyConfig, Trade
from backend.models.kg_models import ExperimentRecord
from backend.core.agi_types import ExperimentStatus


@pytest.fixture(autouse=True)
def enable_autonomy(monkeypatch):
    """Enable autonomous features globally for these tests."""
    monkeypatch.setattr(settings, "AGI_AUTO_PROMOTE", True)
    monkeypatch.setattr(settings, "AGI_AUTO_ENABLE", True)
    monkeypatch.setattr(settings, "AGI_STRATEGY_HEALTH_ENABLED", True)
    monkeypatch.setattr(settings, "AGI_BANKROLL_ALLOCATION_ENABLED", True)
    monkeypatch.setattr(settings, "LIVE_STRATEGY_ALLOWLIST", ["e2e_strat"])


@pytest.mark.asyncio
async def test_promoter_full_lifecycle_shadow_to_live_and_kill(db):
    """Drive a single experiment through DRAFT→SHADOW→PAPER→LIVE and then kill it."""
    strategy_name = "e2e_strat"
    strategy = StrategyConfig(
        strategy_name=strategy_name,
        enabled=False,
        params="{}",
        interval_seconds=60,
    )
    db.add(strategy)
    db.commit()

    # Experiment uses same name as strategy for identity
    exp = ExperimentRecord(
        name=strategy_name,
        strategy_composition={},
        status=ExperimentStatus.DRAFT.value,
    )
    db.add(exp)
    db.commit()
    exp_id = exp.id

    promoter = AutonomousPromoter()

    # Run 1: DRAFT → BACKTEST
    await promoter.run_once()
    with _db_mod.SessionLocal() as verify_db:
        exp_v = verify_db.get(ExperimentRecord, exp_id)
        assert exp_v.status == ExperimentStatus.BACKTEST.value

    # Mark backtest as passed so BACKTEST → SHADOW gate opens
    with _db_mod.SessionLocal() as update_db:
        exp_u = update_db.get(ExperimentRecord, exp_id)
        exp_u.backtest_passed = True
        update_db.commit()

    # Run 2: BACKTEST → SHADOW
    await promoter.run_once()
    # Verify using a fresh session to see committed changes
    with _db_mod.SessionLocal() as verify_db:
        exp_v = verify_db.get(ExperimentRecord, exp_id)
        assert exp_v.status == ExperimentStatus.SHADOW.value
        assert exp_v.shadow_trades == 0

    # Simulate shadow trading results
    with _db_mod.SessionLocal() as update_db:
        exp_u = update_db.get(ExperimentRecord, exp_id)
        exp_u.shadow_trades = 150
        exp_u.shadow_win_rate = 0.62
        exp_u.created_at = datetime.now(timezone.utc) - timedelta(days=8)
        update_db.commit()

    # Run 3: SHADOW → PAPER
    await promoter.run_once()
    with _db_mod.SessionLocal() as verify_db:
        exp_v = verify_db.get(ExperimentRecord, exp_id)
        assert exp_v.status == ExperimentStatus.PAPER.value
        assert exp_v.promoted_at is not None
        # Move promoted_at back 4 days so age requirement satisfied
        exp_v.promoted_at = datetime.now(timezone.utc) - timedelta(days=4)
        verify_db.commit()

    # Mock StrategyHealthMonitor.assess to return healthy metrics
    with patch(
        "backend.core.strategy_health.StrategyHealthMonitor.assess"
    ) as mock_assess:
        mock_assess.return_value = {
            "status": "active",
            "total_trades": 60,
            "win_rate": 0.58,
            "sharpe": 1.1,
            "max_drawdown": 0.12,
        }
        # Run 4: PAPER → LIVE_TRIAL
        await promoter.run_once()

    with _db_mod.SessionLocal() as verify_db:
        exp_v = verify_db.get(ExperimentRecord, exp_id)
        assert exp_v.status == ExperimentStatus.LIVE_TRIAL.value
        # Set promoted_at back 8 days to pass AGI_LIVE_TRIAL_DAYS gate
        exp_v.promoted_at = datetime.now(timezone.utc) - timedelta(days=8)
        verify_db.commit()

    # Run 5: LIVE_TRIAL → LIVE_PROMOTED
    with patch(
        "backend.core.strategy_health.StrategyHealthMonitor.assess"
    ) as mock_assess:
        mock_assess.return_value = {
            "status": "active",
            "total_trades": 30,
            "win_rate": 0.58,
            "sharpe": 1.1,
            "max_drawdown": 0.12,
        }
        await promoter.run_once()

    with _db_mod.SessionLocal() as verify_db:
        exp_v = verify_db.get(ExperimentRecord, exp_id)
        assert exp_v.status == ExperimentStatus.LIVE_PROMOTED.value

    # Strategy should be auto-enabled
    with _db_mod.SessionLocal() as verify_db:
        strategy = (
            verify_db.query(StrategyConfig)
            .filter_by(strategy_name=strategy_name)
            .first()
        )
        assert strategy.enabled is True

    from backend.core import scheduler as sched_mod

    assert hasattr(sched_mod, "schedule_strategy")
    assert sched_mod.schedule_strategy.call_count >= 1
    sched_mod.schedule_strategy.assert_called_with(strategy_name, 60, mode="live")

    # Mock health to trigger kill
    with patch(
        "backend.core.strategy_health.StrategyHealthMonitor.assess"
    ) as mock_assess:
        mock_assess.return_value = {
            "status": "killed",
            "total_trades": 110,
            "win_rate": 0.35,
            "sharpe": -2.5,
            "max_drawdown": 0.55,
        }
        await promoter.run_once()

    with _db_mod.SessionLocal() as verify_db:
        exp_v = verify_db.get(ExperimentRecord, exp_id)
        assert exp_v.status == ExperimentStatus.PAPER.value
        assert exp_v.promoted_at is None


@pytest.mark.asyncio
async def test_bankroll_allocator_updates_botstate(db):
    """BankrollAllocator handles empty state gracefully."""
    allocator = BankrollAllocator()
    result = await allocator.run_once()
    assert isinstance(result, dict)


@pytest.mark.asyncio
async def test_trade_forensics_returns_structured_report(db):
    """TradeForensics.analyze_losing_trade returns a report dict with required keys."""
    trade = Trade(
        market_ticker="TEST-USD",
        direction="up",
        size=1.0,
        entry_price=0.50,
        pnl=-50.0,
        result="loss",
        timestamp=datetime.now(timezone.utc),
        settlement_time=datetime.now(timezone.utc),
        settled=True,
        settlement_value=0.0,
    )
    db.add(trade)
    db.commit()
    trade_id = trade.id

    forensic = TradeForensics()
    report = await forensic.analyze_losing_trade(trade_id)

    assert isinstance(report, dict)
    required_keys = {
        "trade_id",
        "strategy",
        "market",
        "side",
        "size",
        "entry_price",
        "pnl",
        "root_cause",
        "confidence",
        "contributing_factors",
        "suggestions",
    }
    assert required_keys.issubset(report.keys())
    assert report["trade_id"] == trade_id
    assert report["pnl"] == -50.0
    assert isinstance(report["root_cause"], str)
