"""Tests for bankroll allocation enforcement in RiskManager."""

import json
import pytest
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from sqlalchemy import create_engine, func
from sqlalchemy.orm import sessionmaker

from backend.core.risk_manager import RiskManager
from backend.models.database import Base, Trade, BotState


class _MockSettings:
    INITIAL_BANKROLL: float = 1000.0
    DAILY_LOSS_LIMIT: float = 300.0
    MAX_POSITION_FRACTION: float = 0.05
    MAX_TOTAL_EXPOSURE_FRACTION: float = 0.50
    SLIPPAGE_TOLERANCE: float = 0.02
    DAILY_DRAWDOWN_LIMIT_PCT: float = 0.10
    WEEKLY_DRAWDOWN_LIMIT_PCT: float = 0.20
    TRADING_MODE: str = "paper"
    AUTO_APPROVE_MIN_CONFIDENCE: float = 0.6
    REGIME_ROUTING_ENABLED: bool = False
    DRAWDOWN_BREAKER_ENABLED_PER_MODE: dict = {"paper": True, "testnet": True, "live": True}
    DAILY_LOSS_LIMIT_ENABLED_PER_MODE: dict = {"paper": True, "testnet": True, "live": True}
    AGI_BANKROLL_ALLOCATION_ENABLED: bool = True
    MAX_TOTAL_PENDING_TRADES: int = 10


@pytest.fixture()
def alloc_db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    Session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    db = Session()
    state = BotState(mode="paper", bankroll=1000.0)
    db.add(state)
    db.commit()
    try:
        yield db
    finally:
        db.close()


def _make_rm():
    return RiskManager(settings_obj=_MockSettings())


class TestAllocationEnforcement:
    @patch("backend.db.utils.SessionLocal")
    @patch("backend.core.risk_manager.RiskManager._count_enabled_strategies", return_value=1)
    def test_no_allocation_allows_trade(self, mock_count, mock_session_cls):
        mock_db = MagicMock()
        mock_session_cls.return_value = mock_db
        mock_db.query.return_value.filter.return_value.scalar.return_value = 0.0

        rm = _make_rm()
        result = rm.validate_trade(
            size=5.0,
            current_exposure=0.0,
            bankroll=1000.0,
            confidence=0.7,
            strategy_name="btc_5m",
            db=mock_db,
        )
        assert result.allowed is True
        assert result.adjusted_size == 5.0

    def test_allocation_caps_to_remaining_budget(self, alloc_db):
        state = alloc_db.query(BotState).first()
        misc = {"allocations": {"btc_5m": 20.0}}
        state.misc_data = json.dumps(misc)
        alloc_db.commit()

        rm = _make_rm()
        result = rm.validate_trade(
            size=50.0,
            current_exposure=0.0,
            bankroll=1000.0,
            confidence=0.7,
            strategy_name="btc_5m",
            db=alloc_db,
        )
        assert result.allowed is True
        assert result.adjusted_size <= 20.0

    def test_allocation_exhausted_blocks_trade(self, alloc_db):
        state = alloc_db.query(BotState).first()
        misc = {"allocations": {"btc_5m": 20.0}}
        state.misc_data = json.dumps(misc)
        alloc_db.commit()

        open_trade = Trade(
            market_ticker="test-market",
            direction="up",
            entry_price=0.5,
            size=20.0,
            settled=False,
            trading_mode="paper",
            strategy="btc_5m",
        )
        alloc_db.add(open_trade)
        alloc_db.commit()

        rm = _make_rm()
        result = rm.validate_trade(
            size=5.0,
            current_exposure=20.0,
            bankroll=1000.0,
            confidence=0.7,
            strategy_name="btc_5m",
            db=alloc_db,
        )
        assert result.allowed is False
        assert "allocation exhausted" in result.reason

    def test_allocation_remaining_after_partial_exposure(self, alloc_db):
        state = alloc_db.query(BotState).first()
        misc = {"allocations": {"btc_5m": 50.0}}
        state.misc_data = json.dumps(misc)
        alloc_db.commit()

        open_trade = Trade(
            market_ticker="test-market",
            direction="up",
            entry_price=0.5,
            size=30.0,
            settled=False,
            trading_mode="paper",
            strategy="btc_5m",
        )
        alloc_db.add(open_trade)
        alloc_db.commit()

        rm = _make_rm()
        result = rm.validate_trade(
            size=50.0,
            current_exposure=30.0,
            bankroll=1000.0,
            confidence=0.7,
            strategy_name="btc_5m",
            db=alloc_db,
        )
        assert result.allowed is True
        assert result.adjusted_size == pytest.approx(20.0, abs=0.01)

    def test_other_strategy_allocation_ignored(self, alloc_db):
        state = alloc_db.query(BotState).first()
        misc = {"allocations": {"weather": 10.0}}
        state.misc_data = json.dumps(misc)
        alloc_db.commit()

        rm = _make_rm()
        result = rm.validate_trade(
            size=50.0,
            current_exposure=0.0,
            bankroll=1000.0,
            confidence=0.7,
            strategy_name="btc_5m",
            db=alloc_db,
        )
        assert result.allowed is True
        assert result.adjusted_size == 50.0
