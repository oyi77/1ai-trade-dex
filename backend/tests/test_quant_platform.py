"""Tests for quant research platform modules — calibration, experiments, ranking, walk-forward."""

import json
import pytest
from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.models.database import Base


@pytest.fixture
def db():
    """In-memory SQLite DB with all tables."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


# ─── Calibration Tracker Tests ───


class TestCalibrationTracker:
    def test_record_prediction(self, db):
        from backend.core.learning.calibration_tracker import CalibrationTracker
        from backend.models.database import CalibrationRecord

        tracker = CalibrationTracker()
        tracker.record_prediction(db, "general_scanner", "test-market", 0.75, "yes")

        records = db.query(CalibrationRecord).all()
        assert len(records) == 1
        assert records[0].strategy == "general_scanner"
        assert records[0].predicted_prob == 0.75
        assert records[0].direction == "yes"
        assert records[0].actual_outcome is None

    def test_record_outcome(self, db):
        from backend.core.learning.calibration_tracker import CalibrationTracker
        from backend.models.database import CalibrationRecord

        tracker = CalibrationTracker()
        tracker.record_prediction(db, "general_scanner", "test-market", 0.80, "yes")
        updated = tracker.record_outcome(db, "test-market", 1.0)

        assert updated == 1
        record = db.query(CalibrationRecord).first()
        assert record.actual_outcome == "win"
        assert record.settlement_value == 1.0

    def test_record_outcome_loss(self, db):
        from backend.core.learning.calibration_tracker import CalibrationTracker

        tracker = CalibrationTracker()
        tracker.record_prediction(db, "test", "mkt-1", 0.70, "yes")
        tracker.record_outcome(db, "mkt-1", 0.0)

        from backend.models.database import CalibrationRecord

        record = db.query(CalibrationRecord).first()
        assert record.actual_outcome == "loss"

    def test_no_direction_records_correctly(self, db):
        from backend.core.learning.calibration_tracker import CalibrationTracker

        tracker = CalibrationTracker()
        tracker.record_prediction(db, "test", "mkt-no", 0.30, "no")
        tracker.record_outcome(db, "mkt-no", 0.0)  # NO wins

        from backend.models.database import CalibrationRecord

        record = db.query(CalibrationRecord).first()
        assert record.actual_outcome == "win"

    def test_calibration_curve(self, db):
        from backend.core.learning.calibration_tracker import CalibrationTracker

        tracker = CalibrationTracker()
        # Add several predictions with outcomes
        for i in range(10):
            prob = 0.8
            tracker.record_prediction(db, "test", f"mkt-{i}", prob, "yes")
            # 8 out of 10 win (matching 0.8 probability = well-calibrated)
            outcome = 1.0 if i < 8 else 0.0
            tracker.record_outcome(db, f"mkt-{i}", outcome)

        curve = tracker.get_calibration_curve(db, "test", num_bins=5)
        assert len(curve) > 0
        # All predictions were at 0.8, so one bin should have all 10
        bin_with_data = [b for b in curve if b["count"] > 0]
        assert len(bin_with_data) == 1
        assert bin_with_data[0]["count"] == 10
        assert bin_with_data[0]["actual_win_rate"] == 0.8

    def test_brier_score(self, db):
        from backend.core.learning.calibration_tracker import CalibrationTracker

        tracker = CalibrationTracker()
        # Perfect calibration: predict 1.0, always win
        tracker.record_prediction(db, "perfect", "p1", 1.0, "yes")
        tracker.record_outcome(db, "p1", 1.0)

        brier = tracker.get_brier_score(db, "perfect")
        assert brier == 0.0  # Perfect score

    def test_brier_score_none_when_empty(self, db):
        from backend.core.learning.calibration_tracker import CalibrationTracker

        tracker = CalibrationTracker()
        assert tracker.get_brier_score(db, "nonexistent") is None


# ─── Experiment Tracker Tests ───


class TestExperimentTracker:
    def test_create_experiment(self, db):
        from backend.core.experiment_tracker import ExperimentTracker

        tracker = ExperimentTracker()
        exp_id = tracker.create_experiment(db, "test_strategy", {"kelly": 0.05})

        assert exp_id is not None
        assert exp_id > 0

    def test_record_metrics(self, db):
        from backend.core.experiment_tracker import ExperimentTracker

        tracker = ExperimentTracker()
        exp_id = tracker.create_experiment(db, "test", {"kelly": 0.1})
        tracker.record_metrics(db, exp_id, {"sharpe": 1.5, "win_rate": 0.6})

        from backend.models.database import Experiment

        exp = db.query(Experiment).filter(Experiment.id == exp_id).first()
        metrics = json.loads(exp.metrics_json)
        assert metrics["sharpe"] == 1.5

    def test_compare_experiments(self, db):
        from backend.core.experiment_tracker import ExperimentTracker

        tracker = ExperimentTracker()
        a = tracker.create_experiment(db, "test", {"kelly": 0.05})
        b = tracker.create_experiment(db, "test", {"kelly": 0.10})
        tracker.record_metrics(db, a, {"sharpe": 1.0, "total_pnl": 10})
        tracker.record_metrics(db, b, {"sharpe": 2.0, "total_pnl": 20})

        result = tracker.compare(db, a, b)
        assert result["winner"] == b
        assert result["sharpe_diff"] == 1.0

    def test_promote_and_rollback(self, db):
        from backend.core.experiment_tracker import ExperimentTracker
        from backend.models.database import Experiment, StrategyConfig

        # Create a strategy config first
        config = StrategyConfig(
            strategy_name="test_strat",
            enabled=True,
            interval_seconds=60,
            params='{"old": true}',
        )
        db.add(config)
        db.commit()

        tracker = ExperimentTracker()
        exp_a = tracker.create_experiment(db, "test_strat", {"version": "A"})
        tracker.promote(db, exp_a)

        exp = db.query(Experiment).filter(Experiment.id == exp_a).first()
        assert exp.status == "active"

        # Promote a new one
        exp_b = tracker.create_experiment(db, "test_strat", {"version": "B"})
        tracker.promote(db, exp_b)

        # A should be retired
        exp_a_check = db.query(Experiment).filter(Experiment.id == exp_a).first()
        assert exp_a_check.status == "retired"

        # Rollback should bring A back
        tracker.rollback(db, "test_strat")
        exp_a_final = db.query(Experiment).filter(Experiment.id == exp_a).first()
        assert exp_a_final.status == "active"

    def test_get_history(self, db):
        from backend.core.experiment_tracker import ExperimentTracker

        tracker = ExperimentTracker()
        tracker.create_experiment(db, "strat1", {"a": 1})
        tracker.create_experiment(db, "strat1", {"b": 2})
        tracker.create_experiment(db, "strat2", {"c": 3})

        history = tracker.get_history(db, strategy_name="strat1")
        assert len(history) == 2


# ─── Strategy Ranker Tests ───


class TestStrategyRanker:
    def _create_trades(self, db, strategy, wins, losses):
        from backend.models.database import Trade

        now = datetime.now(timezone.utc)
        for i in range(wins):
            t = Trade(
                market_ticker=f"win-{strategy}-{i}",
                direction="yes",
                entry_price=0.50,
                size=2.0,
                strategy=strategy,
                settled=True,
                result="win",
                pnl=2.0,
                timestamp=now - timedelta(days=i),
                trading_mode="paper",
            )
            db.add(t)
        for i in range(losses):
            t = Trade(
                market_ticker=f"loss-{strategy}-{i}",
                direction="yes",
                entry_price=0.50,
                size=2.0,
                strategy=strategy,
                settled=True,
                result="loss",
                pnl=-2.0,
                timestamp=now - timedelta(days=i),
                trading_mode="paper",
            )
            db.add(t)
        db.commit()

    def test_rank_all(self, db):
        from backend.core.strategy_ranker import StrategyRanker

        self._create_trades(db, "good_strat", wins=8, losses=2)
        self._create_trades(db, "bad_strat", wins=2, losses=8)

        ranker = StrategyRanker()
        ranked = ranker.rank_all(db, lookback_days=30, min_trades=5)

        assert len(ranked) == 2
        assert ranked[0].name == "good_strat"
        assert ranked[0].win_rate > ranked[1].win_rate

    def test_auto_allocate(self, db):
        from backend.core.strategy_ranker import StrategyRanker

        self._create_trades(db, "winner", wins=9, losses=1)
        self._create_trades(db, "mediocre", wins=5, losses=5)

        ranker = StrategyRanker()
        allocs = ranker.auto_allocate(db, bankroll=100.0, lookback_days=30)

        assert "winner" in allocs
        # Winner should get more allocation
        if "mediocre" in allocs:
            assert allocs["winner"] >= allocs["mediocre"]
        # No single strategy over 50%
        for v in allocs.values():
            assert v <= 50.0

    def test_disable_underperformers(self, db):
        from backend.core.strategy_ranker import StrategyRanker
        from backend.models.database import StrategyConfig

        # Create a losing strategy with 30+ trades
        self._create_trades(db, "loser", wins=5, losses=30)

        config = StrategyConfig(
            strategy_name="loser", enabled=True, interval_seconds=60, params="{}"
        )
        db.add(config)
        db.commit()

        ranker = StrategyRanker()
        disabled = ranker.disable_underperformers(db, min_sharpe=0.0, min_trades=30)

        assert "loser" in disabled
        cfg = (
            db.query(StrategyConfig)
            .filter(StrategyConfig.strategy_name == "loser")
            .first()
        )
        # disable_for_rehab fully disables losing strategies (no paper-mode
        # zombie): enabled=False with disabled_at recorded.
        assert cfg.enabled is False
        assert cfg.disabled_at is not None


# ─── Backtester Metrics Tests ───


class TestBacktesterMetrics:
    def test_sharpe_uses_returns_not_pnl(self):
        from backend.core.backtester import (
            BacktestTrade,
            BacktestEngine,
            BacktestConfig,
        )
        from datetime import datetime

        config = BacktestConfig(
            strategy_name="test",
            start_date=datetime(2024, 1, 1),
            end_date=datetime(2024, 12, 31),
        )
        engine = BacktestEngine(config)

        # Create trades with varying returns so stdev > 0
        trades = [
            BacktestTrade(
                timestamp=datetime(2024, 1, 1),
                market_ticker="t0",
                direction="yes",
                entry_price=0.5,
                size=2.0,
                edge=0.05,
                pnl=2.0,
                settled=True,  # return = 1.0
            ),
            BacktestTrade(
                timestamp=datetime(2024, 1, 2),
                market_ticker="t1",
                direction="yes",
                entry_price=0.6,
                size=3.0,
                edge=0.05,
                pnl=2.0,
                settled=True,  # return = 0.67
            ),
            BacktestTrade(
                timestamp=datetime(2024, 1, 3),
                market_ticker="t2",
                direction="yes",
                entry_price=0.4,
                size=4.0,
                edge=0.05,
                pnl=6.0,
                settled=True,  # return = 1.5
            ),
            BacktestTrade(
                timestamp=datetime(2024, 1, 4),
                market_ticker="t3",
                direction="yes",
                entry_price=0.5,
                size=2.0,
                edge=0.05,
                pnl=-1.0,
                settled=True,  # return = -0.5
            ),
        ]

        metrics = engine._calculate_metrics(trades, [], 100.0)

        # Sharpe should exist and be positive (all trades win)
        assert metrics["sharpe_ratio"] > 0
        assert metrics["sortino_ratio"] >= 0
        assert metrics["profit_factor"] > 0

    def test_profit_factor_calculation(self):
        from backend.core.backtester import (
            BacktestTrade,
            BacktestEngine,
            BacktestConfig,
        )
        from datetime import datetime

        config = BacktestConfig(
            strategy_name="test",
            start_date=datetime(2024, 1, 1),
            end_date=datetime(2024, 12, 31),
        )
        engine = BacktestEngine(config)

        trades = [
            BacktestTrade(
                timestamp=datetime(2024, 1, 1),
                market_ticker="w1",
                direction="yes",
                entry_price=0.5,
                size=2.0,
                edge=0.05,
                pnl=2.0,
                settled=True,
            ),
            BacktestTrade(
                timestamp=datetime(2024, 1, 2),
                market_ticker="l1",
                direction="yes",
                entry_price=0.5,
                size=2.0,
                edge=0.05,
                pnl=-2.0,
                settled=True,
            ),
        ]

        metrics = engine._calculate_metrics(trades, [], 100.0)
        # PF = 2.0 / 2.0 = 1.0
        assert metrics["profit_factor"] == 1.0

    def test_slippage_in_config(self):
        from backend.core.backtester import BacktestConfig

        config = BacktestConfig(
            strategy_name="test",
            start_date=datetime(2024, 1, 1),
            end_date=datetime(2024, 12, 31),
            slippage=0.02,
        )
        assert config.slippage == 0.02


# ─── Walk-Forward Tests ───


class TestWalkForward:
    @pytest.mark.asyncio
    async def test_walk_forward_no_data(self, db):
        from backend.core.walk_forward import WalkForwardEngine

        engine = WalkForwardEngine()
        result = await engine.run(
            db,
            "nonexistent",
            start_date=datetime(2024, 1, 1),
            end_date=datetime(2024, 6, 1),
            in_sample_days=30,
            out_sample_days=7,
        )

        assert result.strategy == "nonexistent"
        assert len(result.windows) > 0
        assert result.in_sample_sharpe == 0.0

    @pytest.mark.asyncio
    async def test_sweep_empty(self, db):
        from backend.core.walk_forward import WalkForwardEngine

        engine = WalkForwardEngine()
        results = await engine.sweep(
            db,
            "test",
            param_grid={"kelly_fraction": [0.05, 0.10]},
            start_date=datetime(2024, 1, 1),
            end_date=datetime(2024, 6, 1),
        )

        assert len(results) == 2
