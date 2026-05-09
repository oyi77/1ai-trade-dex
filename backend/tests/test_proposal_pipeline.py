"""T18: Proposal column name validation + schema fix [#50]."""
import pytest

from backend.models.database import Base, StrategyProposal


@pytest.fixture
def test_db():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    db = Session()
    yield db
    db.close()


class TestProposalSchema:
    def test_strategy_proposal_has_required_columns(self, test_db):
        cols = {c.name for c in StrategyProposal.__table__.columns}
        assert "admin_decision" in cols, "Missing admin_decision column"
        assert "status" in cols, "Missing status column"
        assert "auto_promotable" in cols, "Missing auto_promotable column"
        assert "backtest_passed" in cols, "Missing backtest_passed column"

    def test_proposal_defaults(self, test_db):
        p = StrategyProposal(
            strategy_name="btc_oracle",
            change_details={"threshold": 0.05},
            expected_impact="Improve win rate",
        )
        test_db.add(p)
        test_db.commit()
        assert p.admin_decision == "pending"
        assert p.status == "pending"
        assert p.auto_promotable is False
        assert p.backtest_passed is False

    def test_query_by_status_no_error(self, test_db):
        results = test_db.query(StrategyProposal).filter(
            StrategyProposal.status == "pending",
            StrategyProposal.auto_promotable == True,
            StrategyProposal.backtest_passed == False,
        ).all()
        assert isinstance(results, list)
