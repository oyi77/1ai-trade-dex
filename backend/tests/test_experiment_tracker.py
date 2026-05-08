"""Tests for ExperimentTracker — create, record, compare, promote, rollback, auto_promote."""

import json
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.core.experiment_tracker import ExperimentTracker
from backend.models.database import Base, Experiment


@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


@pytest.fixture()
def tracker():
    return ExperimentTracker()


def _make_experiment(
    db,
    strategy_name: str,
    status: str = "candidate",
    sharpe: float = 0.0,
    num_trades: int = 0,
    total_pnl: float = 0.0,
    promoted_at=None,
):
    exp = Experiment(
        strategy_name=strategy_name,
        params_json=json.dumps({"alpha": 0.1}),
        metrics_json=json.dumps(
            {"sharpe": sharpe, "num_trades": num_trades, "total_pnl": total_pnl}
        ),
        status=status,
        created_at=datetime.now(timezone.utc),
        promoted_at=promoted_at,
    )
    db.add(exp)
    db.commit()
    return exp


class TestCreateExperiment:
    def test_creates_candidate(self, db, tracker):
        exp_id = tracker.create_experiment(db, "btc_5m", {"window": 20})
        exp = db.query(Experiment).filter(Experiment.id == exp_id).first()

        assert exp is not None
        assert exp.status == "candidate"
        assert exp.strategy_name == "btc_5m"
        assert json.loads(exp.params_json) == {"window": 20}


class TestRecordMetrics:
    def test_records_metrics(self, db, tracker):
        exp_id = tracker.create_experiment(db, "btc_5m", {"window": 20})
        tracker.record_metrics(db, exp_id, {"sharpe": 1.5, "win_rate": 0.6})

        exp = db.query(Experiment).filter(Experiment.id == exp_id).first()
        metrics = json.loads(exp.metrics_json)
        assert metrics["sharpe"] == 1.5

    def test_no_op_on_missing_id(self, db, tracker):
        tracker.record_metrics(db, 9999, {"sharpe": 1.0})


class TestCompare:
    def test_higher_sharpe_wins(self, db, tracker):
        a = _make_experiment(db, "btc_5m", sharpe=1.0)
        b = _make_experiment(db, "btc_5m", sharpe=2.0)
        result = tracker.compare(db, a.id, b.id)
        assert result["winner"] == b.id

    def test_pnl_tiebreak(self, db, tracker):
        a = _make_experiment(db, "btc_5m", sharpe=1.0, total_pnl=100)
        b = _make_experiment(db, "btc_5m", sharpe=1.0, total_pnl=50)
        result = tracker.compare(db, a.id, b.id)
        assert result["winner"] == a.id


class TestPromote:
    def test_promote_retires_active(self, db, tracker):
        active = _make_experiment(db, "btc_5m", status="active", sharpe=0.5)
        candidate = _make_experiment(db, "btc_5m", status="candidate", sharpe=1.5)

        assert tracker.promote(db, candidate.id)
        db.refresh(active)
        db.refresh(candidate)

        assert active.status == "retired"
        assert candidate.status == "active"
        assert candidate.promoted_at is not None

    def test_promote_missing_returns_false(self, db, tracker):
        assert tracker.promote(db, 9999) is False


class TestRollback:
    def test_rollback_restores_retired(self, db, tracker):
        prev = _make_experiment(
            db,
            "btc_5m",
            status="retired",
            promoted_at=datetime.now(timezone.utc) - timedelta(hours=1),
        )
        current = _make_experiment(db, "btc_5m", status="active")

        assert tracker.rollback(db, "btc_5m")
        db.refresh(prev)
        db.refresh(current)

        assert prev.status == "active"
        assert current.status == "retired"

    def test_rollback_no_previous_returns_false(self, db, tracker):
        _make_experiment(db, "btc_5m", status="active")
        assert tracker.rollback(db, "btc_5m") is False


class TestAutoPromote:
    def test_promotes_when_candidate_beats_active(self, db, tracker):
        _make_experiment(db, "btc_5m", status="active", sharpe=0.5, num_trades=50)
        candidate = _make_experiment(
            db, "btc_5m", status="candidate", sharpe=1.5, num_trades=50
        )

        promoted = tracker.auto_promote(db, min_trades=30, min_sharpe_diff=0.5)
        assert candidate.id in promoted
        db.refresh(candidate)
        assert candidate.status == "active"

    def test_no_promote_below_min_trades(self, db, tracker):
        _make_experiment(db, "btc_5m", status="active", sharpe=0.5, num_trades=50)
        _make_experiment(db, "btc_5m", status="candidate", sharpe=2.0, num_trades=10)

        promoted = tracker.auto_promote(db, min_trades=30, min_sharpe_diff=0.5)
        assert promoted == []

    def test_no_promote_below_sharpe_diff(self, db, tracker):
        _make_experiment(db, "btc_5m", status="active", sharpe=1.0, num_trades=50)
        _make_experiment(db, "btc_5m", status="candidate", sharpe=1.3, num_trades=50)

        promoted = tracker.auto_promote(db, min_trades=30, min_sharpe_diff=0.5)
        assert promoted == []

    def test_promotes_best_of_multiple_candidates(self, db, tracker):
        _make_experiment(db, "btc_5m", status="active", sharpe=0.5, num_trades=50)
        c1 = _make_experiment(
            db, "btc_5m", status="candidate", sharpe=1.2, num_trades=50
        )
        c2 = _make_experiment(
            db, "btc_5m", status="candidate", sharpe=1.8, num_trades=50
        )

        promoted = tracker.auto_promote(db, min_trades=30, min_sharpe_diff=0.5)
        assert c2.id in promoted
        assert c1.id not in promoted

    def test_promotes_across_strategies(self, db, tracker):
        _make_experiment(db, "btc_5m", status="active", sharpe=0.2, num_trades=50)
        c_btc = _make_experiment(
            db, "btc_5m", status="candidate", sharpe=1.0, num_trades=40
        )

        _make_experiment(db, "weather", status="active", sharpe=0.3, num_trades=50)
        c_wx = _make_experiment(
            db, "weather", status="candidate", sharpe=1.5, num_trades=35
        )

        promoted = tracker.auto_promote(db, min_trades=30, min_sharpe_diff=0.5)
        assert c_btc.id in promoted
        assert c_wx.id in promoted
        assert len(promoted) == 2

    def test_promote_without_active_baseline(self, db, tracker):
        candidate = _make_experiment(
            db, "new_strat", status="candidate", sharpe=1.0, num_trades=50
        )

        promoted = tracker.auto_promote(db, min_trades=30, min_sharpe_diff=0.5)
        assert candidate.id in promoted

    def test_rollback_bad_recent_promotion(self, db, tracker):
        prev = _make_experiment(
            db,
            "btc_5m",
            status="retired",
            sharpe=0.8,
            promoted_at=datetime.now(timezone.utc) - timedelta(hours=2),
        )
        bad_active = _make_experiment(
            db,
            "btc_5m",
            status="active",
            sharpe=-1.0,
            promoted_at=datetime.now(timezone.utc) - timedelta(hours=1),
        )

        tracker.auto_promote(
            db,
            rollback_window_hours=24,
            rollback_sharpe_floor=-0.5,
        )

        db.refresh(bad_active)
        db.refresh(prev)
        assert bad_active.status == "retired"
        assert prev.status == "active"

    def test_no_rollback_outside_window(self, db, tracker):
        _make_experiment(
            db,
            "btc_5m",
            status="retired",
            sharpe=0.8,
            promoted_at=datetime.now(timezone.utc) - timedelta(hours=48),
        )
        old_active = _make_experiment(
            db,
            "btc_5m",
            status="active",
            sharpe=-1.0,
            promoted_at=datetime.now(timezone.utc) - timedelta(hours=48),
        )

        tracker.auto_promote(
            db,
            rollback_window_hours=24,
            rollback_sharpe_floor=-0.5,
        )

        db.refresh(old_active)
        assert old_active.status == "active"

    def test_returns_empty_when_nothing_to_do(self, db, tracker):
        promoted = tracker.auto_promote(db)
        assert promoted == []
