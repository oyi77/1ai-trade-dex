"""Integration test: full learning feedback loop end-to-end."""

import pytest
from datetime import datetime, timezone
from unittest.mock import MagicMock
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.models.database import Base, StrategyConfig
from backend.models.outcome_tables import (
    StrategyOutcome,
    ParamChange,
    StrategyHealthRecord,
    TradingCalibrationRecord,
)
from backend.core.outcome_repository import record_outcome, get_strategy_stats
from backend.core.trading_calibration import TradingCalibration
from backend.core.thompson_sampler import ThompsonSampler
from backend.core.strategy_health import StrategyHealthMonitor
from backend.core.safe_param_tuner import SafeParamTuner
from backend.core.learning.online_learner import OnlineLearner


@pytest.fixture
def db():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    StrategyOutcome.__table__.create(bind=engine, checkfirst=True)
    ParamChange.__table__.create(bind=engine, checkfirst=True)
    StrategyHealthRecord.__table__.create(bind=engine, checkfirst=True)
    TradingCalibrationRecord.__table__.create(bind=engine, checkfirst=True)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


def _make_trade(trade_id, strategy, result, pnl, prob=0.65):
    t = MagicMock()
    t.id = trade_id
    t.strategy = strategy
    t.result = result
    t.pnl = pnl
    t.model_probability = prob
    t.market_ticker = "TEST-MARKET"
    t.market_type = "binary"
    t.trading_mode = "paper"
    t.direction = "YES"
    t.market_price_at_entry = 0.60
    t.edge_at_entry = 0.05
    t.confidence = 0.70
    t.settlement_time = datetime.now(timezone.utc)
    return t


def test_record_outcome_and_stats(db):
    trade = _make_trade(1, "btc_oracle", "win", 10.0)
    outcome = record_outcome(trade, db)
    assert outcome is not None
    assert outcome.strategy == "btc_oracle"
    assert outcome.result == "win"
    assert outcome.pnl == 10.0

    stats = get_strategy_stats("btc_oracle", None, db)
    assert stats is not None
    assert stats["wins"] == 1
    assert stats["win_rate"] == 1.0


def test_calibration_brier(db):
    tc = TradingCalibration()
    for _ in range(10):
        tc.record("btc_oracle", 0.7, 1)
    for _ in range(5):
        tc.record("btc_oracle", 0.3, 0)
    brier = tc.brier_score("btc_oracle")
    assert brier is not None
    assert 0.0 <= brier <= 1.0


def test_thompson_sampler_update_and_allocate(db):
    ts = ThompsonSampler()
    for _ in range(20):
        ts.update("btc_oracle", won=True)
    for _ in range(5):
        ts.update("btc_oracle", won=False)
    for _ in range(10):
        ts.update("copy_trader", won=True)
    for _ in range(10):
        ts.update("copy_trader", won=False)

    alloc = ts.allocate(["btc_oracle", "copy_trader"], total_capital=1000.0)
    assert "btc_oracle" in alloc
    assert "copy_trader" in alloc
    assert abs(sum(alloc.values()) - 1000.0) < 1.0
    assert alloc["btc_oracle"] > alloc["copy_trader"]


def test_strategy_health_active(db):
    monitor = StrategyHealthMonitor()
    for i in range(35):
        t = _make_trade(
            i + 100,
            "btc_oracle",
            "win" if i % 2 == 0 else "loss",
            5.0 if i % 2 == 0 else -3.0,
        )
        t.trading_mode = "paper"
        record_outcome(t, db)

    health = monitor.assess("btc_oracle", db, trading_mode="paper")
    assert health["total_trades"] == 35
    assert health["status"] in ("active", "warned")
    assert 0.0 <= health["win_rate"] <= 1.0


def test_strategy_health_kill(db):
    monitor = StrategyHealthMonitor()
    for i in range(35):
        t = _make_trade(i + 200, "bad_strategy", "loss", -10.0, prob=0.9)
        t.trading_mode = "paper"
        record_outcome(t, db)

    health = monitor.assess("bad_strategy", db, trading_mode="paper")
    assert health["status"] == "killed"
    assert health["win_rate"] < monitor.KILL_WIN_RATE


def test_safe_param_tuner_no_crash(db):
    import json

    config = StrategyConfig(
        strategy_name="btc_oracle",
        enabled=True,
        params=json.dumps({"edge_threshold": 0.05, "kelly_fraction": 0.1}),
    )
    db.add(config)
    db.commit()

    for i in range(25):
        t = _make_trade(
            i + 300,
            "btc_oracle",
            "win" if i % 3 != 0 else "loss",
            5.0 if i % 3 != 0 else -2.0,
        )
        record_outcome(t, db)

    tuner = SafeParamTuner()
    changes = tuner.tune("btc_oracle", db)
    assert isinstance(changes, dict)


def test_online_learner_full_loop(db):
    import json

    config = StrategyConfig(
        strategy_name="copy_trader",
        enabled=True,
        params=json.dumps({"edge_threshold": 0.04}),
    )
    db.add(config)
    db.commit()

    learner = OnlineLearner()
    for i in range(40):
        t = _make_trade(
            i + 400,
            "copy_trader",
            "win" if i % 2 == 0 else "loss",
            4.0 if i % 2 == 0 else -2.0,
        )
        learner.on_trade_settled(t, db)

    alloc = learner.get_allocation(["copy_trader"], total_capital=500.0)
    assert "copy_trader" in alloc

    calibrated = learner.get_calibrated_prob("copy_trader", 0.65)
    assert 0.0 <= calibrated <= 1.0
