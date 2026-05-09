import pytest
from unittest.mock import MagicMock

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.models.kg_models import Base, ExperimentRecord
from backend.core.experiment_runner import ExperimentRunner


@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


class TestShadowExperimentRealSignals:
    def test_no_fake_data_when_zero_trades(self, db_session):
        runner = ExperimentRunner(session=db_session)
        result = runner.run_shadow_experiment("test_strategy", duration_days=7)
        assert result.trades == 0
        assert result.win_rate == 0.0
        assert result.pnl == 0.0

    def test_uses_real_trade_data(self, db_session):
        mock_trade = MagicMock()
        mock_trade.result = "win"
        mock_trade.pnl = 5.0

        mock_query = MagicMock()
        mock_query.filter.return_value = mock_query
        mock_query.all.return_value = [mock_trade]

        db_session.query = MagicMock(return_value=mock_query)

        runner = ExperimentRunner(session=db_session)
        result = runner.run_shadow_experiment("test_strategy", duration_days=7)

        assert result.trades == 1
        assert result.win_rate == 1.0
        assert result.pnl == 5.0

    def test_shadow_experiment_persists_real_stats(self, db_session):
        runner = ExperimentRunner(session=db_session)
        runner.run_shadow_experiment("persist_strategy", duration_days=7)

        experiment = (
            db_session.query(ExperimentRecord)
            .filter_by(name="persist_strategy", status="shadow")
            .first()
        )
        assert experiment is not None
        assert experiment.shadow_trades == 0
        assert experiment.shadow_win_rate == 0.0

    def test_zero_trades_prevents_promotion(self, db_session):
        runner = ExperimentRunner(session=db_session)
        result = runner.run_shadow_experiment("no_promote_strategy", duration_days=7)
        experiment_id = result.experiment_id

        evaluation = runner.evaluate_experiment(experiment_id)
        assert not evaluation.meets_criteria
        assert any("Insufficient trades" in r for r in evaluation.reasons)
