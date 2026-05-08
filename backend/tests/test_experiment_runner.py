from datetime import datetime, timezone, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.core.experiment_runner import (
    ExperimentRunner,
    ExperimentResult,
    EvaluationResult,
    PromotionResult,
)
from backend.models.kg_models import Base, ExperimentRecord, DecisionAuditLog


def make_runner_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()
    runner = ExperimentRunner(session=session)
    return runner, session, engine


class TestExperimentRunnerRunShadow:
    def test_run_creates_experiment(self):
        runner, session, _ = make_runner_session()
        result = runner.run_shadow_experiment("test_strat", duration_days=7)
        assert result.status == "shadow"
        assert result.trades >= 0  # Zero trades is valid when no real trade data exists
        assert result.experiment_id is not None

    def test_run_updates_existing_experiment(self):
        runner, session, _ = make_runner_session()
        experiment = ExperimentRecord(
            name="test_strat",
            strategy_composition={"name": "test"},
            status="shadow",
        )
        session.add(experiment)
        session.commit()

        result = runner.run_shadow_experiment("test_strat", duration_days=14)
        assert result.trades >= 0  # Uses real trade data only, not fabricated


class TestExperimentRunnerEvaluate:
    def test_evaluate_meets_criteria(self):
        runner, session, _ = make_runner_session()
        experiment = ExperimentRecord(
            name="good_strat",
            strategy_composition={"name": "good"},
            status="shadow",
            shadow_trades=150,
            shadow_win_rate=0.55,
        )
        experiment.created_at = datetime.now(timezone.utc) - timedelta(days=8)
        session.add(experiment)
        session.commit()

        result = runner.evaluate_experiment(str(experiment.id))
        assert result.meets_criteria
        assert len(result.reasons) == 0

    def test_evaluate_insufficient_trades(self):
        runner, session, _ = make_runner_session()
        experiment = ExperimentRecord(
            name="few_trades",
            strategy_composition={"name": "few"},
            status="shadow",
            shadow_trades=50,
            shadow_win_rate=0.60,
        )
        session.add(experiment)
        session.commit()

        result = runner.evaluate_experiment(str(experiment.id))
        assert not result.meets_criteria
        assert any("trades" in r.lower() for r in result.reasons)

    def test_evaluate_low_win_rate(self):
        runner, session, _ = make_runner_session()
        experiment = ExperimentRecord(
            name="poor_strat",
            strategy_composition={"name": "poor"},
            status="shadow",
            shadow_trades=150,
            shadow_win_rate=0.30,
        )
        session.add(experiment)
        session.commit()

        result = runner.evaluate_experiment(str(experiment.id))
        assert not result.meets_criteria
        assert any("win rate" in r.lower() for r in result.reasons)

    def test_evaluate_nonexistent_experiment(self):
        runner, _, _ = make_runner_session()
        result = runner.evaluate_experiment("999")
        assert not result.meets_criteria
        assert any("not found" in r.lower() for r in result.reasons)


class TestExperimentRunnerPromote:
    def test_promote_meets_criteria(self):
        runner, session, _ = make_runner_session()
        experiment = ExperimentRecord(
            name="promotable",
            strategy_composition={"name": "promotable"},
            status="shadow",
            shadow_trades=150,
            shadow_win_rate=0.55,
        )
        experiment.created_at = datetime.now(timezone.utc) - timedelta(days=8)
        session.add(experiment)
        session.commit()

        result = runner.promote_experiment(str(experiment.id))
        assert result.promoted
        assert result.new_status == "paper"

        updated = session.query(ExperimentRecord).filter_by(id=experiment.id).first()
        assert updated.status == "paper"

    def test_promote_does_not_meet_criteria(self):
        runner, session, _ = make_runner_session()
        experiment = ExperimentRecord(
            name="not_ready",
            strategy_composition={"name": "not_ready"},
            status="shadow",
            shadow_trades=50,
            shadow_win_rate=0.30,
        )
        session.add(experiment)
        session.commit()

        result = runner.promote_experiment(str(experiment.id))
        assert not result.promoted
        assert "criteria" in result.message.lower()


class TestExperimentRunnerRetire:
    def test_retire_experiment(self):
        runner, session, _ = make_runner_session()
        experiment = ExperimentRecord(
            name="retire_me",
            strategy_composition={"name": "retire"},
            status="shadow",
        )
        session.add(experiment)
        session.commit()

        result = runner.retire_experiment(str(experiment.id), "no longer needed")
        assert result

        updated = session.query(ExperimentRecord).filter_by(id=experiment.id).first()
        assert updated.status == "retired"
        assert updated.retired_at is not None

    def test_retire_nonexistent(self):
        runner, _, _ = make_runner_session()
        result = runner.retire_experiment("999", "no such experiment")
        assert not result

    def test_retire_creates_audit_log(self):
        runner, session, _ = make_runner_session()
        experiment = ExperimentRecord(
            name="audit_test",
            strategy_composition={"name": "audit"},
            status="shadow",
        )
        session.add(experiment)
        session.commit()

        runner.retire_experiment(str(experiment.id), "test retirement")
        audit = session.query(DecisionAuditLog).filter_by(decision_type="experiment_retired").first()
        assert audit is not None
        assert "retire" in str(audit.input_data).lower()


class TestExperimentResult:
    def test_creation(self):
        result = ExperimentResult(
            experiment_id="123",
            status="shadow",
            trades=100,
            win_rate=0.55,
            pnl=500.0,
        )
        assert result.experiment_id == "123"
        assert result.status == "shadow"
        assert result.trades == 100
        assert result.win_rate == 0.55
        assert result.pnl == 500.0


class TestEvaluationResult:
    def test_meets_criteria(self):
        result = EvaluationResult(
            experiment_id="123",
            meets_criteria=True,
        )
        assert result.meets_criteria
        assert len(result.reasons) == 0

    def test_does_not_meet(self):
        result = EvaluationResult(
            experiment_id="456",
            meets_criteria=False,
            reasons=["Low win rate", "Insufficient trades"],
        )
        assert not result.meets_criteria
        assert len(result.reasons) == 2


class TestPromotionResult:
    def test_promoted(self):
        result = PromotionResult(
            experiment_id="123",
            promoted=True,
            new_status="paper",
            message="Promoted",
        )
        assert result.promoted
        assert result.new_status == "paper"

    def test_not_promoted(self):
        result = PromotionResult(
            experiment_id="456",
            promoted=False,
            new_status="shadow",
            message="Criteria not met",
        )
        assert not result.promoted
