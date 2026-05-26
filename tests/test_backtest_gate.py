"""Backtest gate integration test.

Exercises the full experiment promotion pipeline through the backtest gate:
  DRAFT → BACKTEST → SHADOW → PAPER → LIVE_PROMOTED
  REVIEW → BACKTEST (with improvement) or RETIRED (expired)
  BACKTEST → RETIRED (failed after 7 days)
"""

import sys
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

_sched_stub = MagicMock()
_sched_stub.start_scheduler = MagicMock()
_sched_stub.stop_scheduler = MagicMock()
_sched_stub.log_event = MagicMock()
_sched_stub.is_scheduler_running = MagicMock(return_value=False)
_sched_stub.get_recent_events = MagicMock(return_value=[])

sys.modules.setdefault("apscheduler", MagicMock())
sys.modules.setdefault("apscheduler.schedulers", MagicMock())
sys.modules.setdefault("apscheduler.schedulers.asyncio", MagicMock())
sys.modules["backend.core.scheduler"] = _sched_stub

# ---------------------------------------------------------------------------
# Use the configured test database engine and session
# ---------------------------------------------------------------------------
from backend.models import database as _db_mod  # noqa: E402
from backend.models.database import Base, BotState, StrategyProposal  # noqa: E402
from backend.models.kg_models import ExperimentRecord  # noqa: E402

_engine = _db_mod.engine
_TestSession = _db_mod.SessionLocal

from backend.core.agi_types import ExperimentStatus  # noqa: E402
from backend.core.autonomous_promoter import AutonomousPromoter  # noqa: E402
from backend.core import autonomous_promoter as _promoter_mod  # noqa: E402
from backend.db import utils as _db_utils_mod  # noqa: E402
from backend.config import settings  # noqa: E402

# Ensure promoter uses the active test's SessionLocal
_promoter_mod.SessionLocal = _TestSession
_db_utils_mod.SessionLocal = _TestSession

_PROMOTER_KEYS = {
    "AGI_PROMOTER_SHADOW_MIN_TRADES": 5,
    "AGI_PROMOTER_SHADOW_MIN_DAYS": 0,
    "AGI_PROMOTER_SHADOW_MIN_WIN_RATE": 0.45,
    "AGI_PROMOTER_SHADOW_MAX_DRAWDOWN": 0.25,
    "AGI_PROMOTER_PAPER_MIN_TRADES": 3,
    "AGI_PROMOTER_PAPER_MIN_WIN_RATE": 0.50,
    "AGI_PROMOTER_PAPER_MIN_SHARPE": 0.5,
    "AGI_PROMOTER_PAPER_MAX_DRAWDOWN": 0.20,
    "AGI_AUTO_PROMOTE": False,
    "AGI_STRATEGY_HEALTH_ENABLED": True,
}


def _apply_test_settings():
    saved = {}
    for key, val in _PROMOTER_KEYS.items():
        saved[key] = getattr(settings, key, None)
        object.__setattr__(settings, key, val)
    return saved


def _restore_settings(saved):
    for key, val in saved.items():
        if val is not None:
            object.__setattr__(settings, key, val)


def _seed_bot_state(db):
    db.query(BotState).delete()
    db.commit()
    db.add(
        BotState(
            mode="paper",
            bankroll=10000.0,
            paper_bankroll=10000.0,
            total_trades=0,
            winning_trades=0,
            total_pnl=0.0,
            is_running=True,
        )
    )
    db.commit()


@pytest.mark.asyncio
async def test_draft_to_backtest_auto_promotion():
    """DRAFT experiments auto-promote to BACKTEST status."""
    db = _TestSession()
    saved = _apply_test_settings()
    try:
        _seed_bot_state(db)

        exp = ExperimentRecord(
            name="test_strategy_v1",
            strategy_name="test_strategy",
            status=ExperimentStatus.DRAFT.value,
            created_at=datetime.now(timezone.utc),
        )
        db.add(exp)

        # Add a dummy proposal so it doesn't auto-pass the backtest gate
        proposal = StrategyProposal(
            strategy_name="test_strategy",
            status="pending",
            backtest_passed=False,
            created_at=datetime.now(timezone.utc),
            change_details="{}",
            expected_impact="dummy",
        )
        db.add(proposal)
        db.commit()

        promoter = AutonomousPromoter()
        await promoter.run_once()

        db.refresh(exp)
        assert (
            exp.status == ExperimentStatus.BACKTEST.value
        ), f"DRAFT should auto-promote to BACKTEST, got {exp.status}"
    finally:
        _restore_settings(saved)
        db.close()


@pytest.mark.asyncio
async def test_backtest_to_shadow_with_proposal():
    """BACKTEST → SHADOW when a passing StrategyProposal exists."""
    db = _TestSession()
    saved = _apply_test_settings()
    try:
        _seed_bot_state(db)

        exp = ExperimentRecord(
            name="btc_momentum_v2",
            strategy_name="btc_momentum",
            status=ExperimentStatus.BACKTEST.value,
            created_at=datetime.now(timezone.utc),
        )
        db.add(exp)

        proposal = StrategyProposal(
            strategy_name="btc_momentum",
            status="pending",
            backtest_passed=True,
            backtest_sharpe=1.2,
            backtest_win_rate=0.58,
            change_details={"param": "kelly_fraction", "value": 0.3},
            expected_impact="Higher returns with controlled risk",
        )
        db.add(proposal)
        db.commit()

        promoter = AutonomousPromoter()
        await promoter.run_once()

        db.refresh(exp)
        assert (
            exp.status == ExperimentStatus.SHADOW.value
        ), f"BACKTEST should promote to SHADOW with passing proposal, got {exp.status}"
        assert bool(exp.backtest_passed) is True
        assert exp.backtest_sharpe == 1.2
        assert exp.backtest_win_rate == 0.58
        assert exp.shadow_trades == 0
    finally:
        _restore_settings(saved)
        db.close()


@pytest.mark.asyncio
async def test_backtest_to_shadow_with_record_flag():
    """BACKTEST → SHADOW when ExperimentRecord.backtest_passed=True (no proposal needed)."""
    db = _TestSession()
    saved = _apply_test_settings()
    try:
        _seed_bot_state(db)

        exp = ExperimentRecord(
            name="weather_v3",
            strategy_name="weather_emos",
            status=ExperimentStatus.BACKTEST.value,
            backtest_passed=True,
            backtest_sharpe=0.8,
            backtest_win_rate=0.52,
            created_at=datetime.now(timezone.utc),
        )
        db.add(exp)

        # Add a dummy proposal so it doesn't auto-pass the backtest gate
        proposal = StrategyProposal(
            strategy_name="bad_algo",
            status="pending",
            backtest_passed=False,
            created_at=datetime.now(timezone.utc),
            change_details="{}",
            expected_impact="dummy",
        )
        db.add(proposal)
        db.commit()

        promoter = AutonomousPromoter()
        await promoter.run_once()

        db.refresh(exp)
        assert (
            exp.status == ExperimentStatus.SHADOW.value
        ), f"BACKTEST with backtest_passed=True should promote to SHADOW, got {exp.status}"
    finally:
        _restore_settings(saved)
        db.close()


@pytest.mark.asyncio
async def test_backtest_stays_when_no_proposal():
    """BACKTEST stays in BACKTEST when no passing proposal and no flag."""
    db = _TestSession()
    saved = _apply_test_settings()
    try:
        _seed_bot_state(db)

        exp = ExperimentRecord(
            name="failing_strategy",
            strategy_name="bad_algo",
            status=ExperimentStatus.BACKTEST.value,
            backtest_passed=False,
            created_at=datetime.now(timezone.utc),
        )
        db.add(exp)
        db.commit()

        promoter = AutonomousPromoter()
        stats = await promoter.run_once()

        db.refresh(exp)
        assert (
            exp.status == ExperimentStatus.BACKTEST.value
        ), f"BACKTEST without passing proposal should stay, got {exp.status}"
        assert stats["retired"] == 0
    finally:
        _restore_settings(saved)
        db.close()


@pytest.mark.asyncio
async def test_backtest_retired_after_7_days():
    """BACKTEST experiment retired after 7 days without passing backtest."""
    db = _TestSession()
    saved = _apply_test_settings()
    try:
        _seed_bot_state(db)

        exp = ExperimentRecord(
            name="stale_strategy",
            strategy_name="old_algo",
            status=ExperimentStatus.BACKTEST.value,
            backtest_passed=False,
            created_at=datetime.now(timezone.utc) - timedelta(days=8),
        )
        db.add(exp)

        # Add a dummy proposal so it doesn't auto-pass the backtest gate
        proposal = StrategyProposal(
            strategy_name="old_algo",
            status="pending",
            backtest_passed=False,
            created_at=datetime.now(timezone.utc) - timedelta(days=8),
            change_details="{}",
            expected_impact="dummy",
        )
        db.add(proposal)
        db.commit()

        promoter = AutonomousPromoter()
        stats = await promoter.run_once()

        db.refresh(exp)
        assert (
            exp.status == ExperimentStatus.RETIRED.value
        ), f"BACKTEST older than 7d with no passing proposal should be RETIRED, got {exp.status}"
        assert exp.retired_at is not None
        assert stats["retired"] == 1
    finally:
        _restore_settings(saved)
        db.close()


@pytest.mark.asyncio
async def test_review_to_backtest_with_improvement():
    """REVIEW → BACKTEST when new passing proposal exists (improvement applied)."""
    db = _TestSession()
    saved = _apply_test_settings()
    try:
        _seed_bot_state(db)

        exp = ExperimentRecord(
            name="degraded_strategy",
            strategy_name="copy_trader",
            status=ExperimentStatus.REVIEW.value,
            review_reason="Performance degradation detected",
            degradation_count=2,
            created_at=datetime.now(timezone.utc) - timedelta(days=3),
            last_degradation_at=datetime.now(timezone.utc) - timedelta(days=2),
        )
        db.add(exp)

        improved_proposal = StrategyProposal(
            strategy_name="copy_trader",
            status="pending",
            backtest_passed=True,
            backtest_sharpe=0.9,
            backtest_win_rate=0.55,
            change_details={"param": "min_whale_pnl", "value": 500},
            expected_impact="Better whale filtering",
        )
        db.add(improved_proposal)
        db.commit()

        promoter = AutonomousPromoter()
        await promoter.run_once()

        db.refresh(exp)
        # REVIEW→BACKTEST→SHADOW happens in same run when proposal exists
        assert exp.status in (
            ExperimentStatus.BACKTEST.value,
            ExperimentStatus.SHADOW.value,
        ), f"REVIEW with improvement should go to BACKTEST or SHADOW, got {exp.status}"
        assert exp.degradation_count == 0, "Degradation count should reset"
        assert exp.review_reason is None, "Review reason should clear"
        assert exp.backtest_sharpe == 0.9
    finally:
        _restore_settings(saved)
        db.close()


@pytest.mark.asyncio
async def test_review_to_retired_when_expired():
    """REVIEW → RETIRED when review period exceeds 14 days without improvement."""
    db = _TestSession()
    saved = _apply_test_settings()
    try:
        _seed_bot_state(db)

        exp = ExperimentRecord(
            name="stale_review",
            strategy_name="bond_scanner",
            status=ExperimentStatus.REVIEW.value,
            review_reason="Sharpe dropped below -0.5",
            degradation_count=3,
            created_at=datetime.now(timezone.utc) - timedelta(days=20),
            last_degradation_at=datetime.now(timezone.utc) - timedelta(days=15),
        )
        db.add(exp)
        db.commit()

        promoter = AutonomousPromoter()
        stats = await promoter.run_once()

        db.refresh(exp)
        assert (
            exp.status == ExperimentStatus.RETIRED.value
        ), f"REVIEW older than 14d without improvement should be RETIRED, got {exp.status}"
        assert exp.retired_at is not None
        assert stats["retired"] == 1
    finally:
        _restore_settings(saved)
        db.close()


@pytest.mark.asyncio
async def test_full_pipeline_backtest_to_shadow_to_paper():
    """Full pipeline: DRAFT → BACKTEST → SHADOW → PAPER in two promoter runs."""
    db = _TestSession()
    saved = _apply_test_settings()
    try:
        _seed_bot_state(db)

        exp = ExperimentRecord(
            name="full_pipeline_test",
            strategy_name="test_strat",
            status=ExperimentStatus.DRAFT.value,
            created_at=datetime.now(timezone.utc) - timedelta(days=3),
        )
        db.add(exp)

        proposal = StrategyProposal(
            strategy_name="test_strat",
            status="pending",
            backtest_passed=True,
            backtest_sharpe=1.5,
            backtest_win_rate=0.60,
            change_details={"param": "threshold", "value": 0.05},
            expected_impact="Better edge detection",
        )
        db.add(proposal)
        db.commit()

        promoter = AutonomousPromoter()
        await promoter.run_once()

        db.refresh(exp)
        assert (
            exp.status == ExperimentStatus.SHADOW.value
        ), f"After first run: should be SHADOW, got {exp.status}"

        exp.shadow_trades = 10
        exp.shadow_win_rate = 0.55
        exp.shadow_pnl = 120.0
        exp.promoted_at = datetime.now(timezone.utc) - timedelta(days=2)
        db.commit()

        await promoter.run_once()

        db.refresh(exp)
        assert (
            exp.status == ExperimentStatus.PAPER.value
        ), f"After shadow criteria met: should be PAPER, got {exp.status}"
    finally:
        _restore_settings(saved)
        db.close()
