"""Tests for Impact Measurer and Rollback System - Wave 4c"""

import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import patch

from backend.ai.impact_measurer import ImpactMeasurer
from backend.services.rollback_manager import RollbackManager
from backend.models.database import Trade, StrategyProposal, StrategyConfig
import backend.models.database as _db_mod


@pytest.fixture
def db_session():
    session = _db_mod.SessionLocal()
    yield session
    session.close()


@pytest.fixture
def sample_trades_before():
    """Create sample trades before proposal execution."""
    trades = []
    base_time = datetime.now(timezone.utc) - timedelta(days=10)

    for i in range(25):
        trade = Trade(
            id=i + 1,
            market_ticker="BTC-USD",
            platform="polymarket",
            direction="up" if i % 2 == 0 else "down",
            entry_price=50000 + i * 100,
            size=1.0,
            timestamp=base_time + timedelta(hours=i),
            settled=True,
            result="win" if i % 3 != 0 else "loss",
            pnl=10.0 if i % 3 != 0 else -5.0,
            model_probability=0.65,
            market_price_at_entry=0.60,
            edge_at_entry=0.05,
            trading_mode="paper"
        )
        trades.append(trade)

    return trades


@pytest.fixture
def sample_trades_after():
    """Create sample trades after proposal execution (improved performance)."""
    trades = []
    base_time = datetime.now(timezone.utc) - timedelta(days=5)

    for i in range(25):
        trade = Trade(
            id=i + 100,
            market_ticker="BTC-USD",
            platform="polymarket",
            direction="up" if i % 2 == 0 else "down",
            entry_price=51000 + i * 100,
            size=1.0,
            timestamp=base_time + timedelta(hours=i),
            settled=True,
            result="win" if i % 2 == 0 else "loss",
            pnl=15.0 if i % 2 == 0 else -3.0,
            model_probability=0.70,
            market_price_at_entry=0.60,
            edge_at_entry=0.10,
            trading_mode="paper"
        )
        trades.append(trade)

    return trades


class TestImpactMeasurer:
    """Test suite for ImpactMeasurer."""

    def test_initialization(self):
        """Test ImpactMeasurer initializes correctly."""
        measurer = ImpactMeasurer()
        assert measurer is not None
        assert measurer.MIN_SAMPLE_SIZE == 20

    def test_insufficient_trades_before(self, sample_trades_after):
        """Test impact measurement fails with insufficient before trades."""
        measurer = ImpactMeasurer()
        trades_before = sample_trades_after[:10]

        impact = measurer.measure_proposal_impact(
            proposal_id=1,
            trades_before=trades_before,
            trades_after=sample_trades_after
        )

        assert impact is None

    def test_insufficient_trades_after(self, sample_trades_before):
        """Test impact measurement fails with insufficient after trades."""
        measurer = ImpactMeasurer()
        trades_after = sample_trades_before[:10]

        impact = measurer.measure_proposal_impact(
            proposal_id=1,
            trades_before=sample_trades_before,
            trades_after=trades_after
        )

        assert impact is None

    def test_calculate_metrics_empty_trades(self):
        """Test metrics calculation with empty trade list."""
        measurer = ImpactMeasurer()
        metrics = measurer._calculate_metrics([])

        assert metrics['sharpe_ratio'] == 0.0
        assert metrics['win_rate'] == 0.0
        assert metrics['avg_pnl'] == 0.0
        assert metrics['avg_edge'] == 0.0
        assert metrics['total_pnl'] == 0.0

    def test_calculate_metrics_valid_trades(self, sample_trades_before):
        """Test metrics calculation with valid trades."""
        measurer = ImpactMeasurer()
        metrics = measurer._calculate_metrics(sample_trades_before)

        assert metrics['sharpe_ratio'] != 0.0
        assert 0.0 <= metrics['win_rate'] <= 1.0
        assert metrics['avg_pnl'] != 0.0
        assert metrics['avg_edge'] > 0.0
        assert metrics['total_pnl'] != 0.0

    def test_measure_proposal_impact_positive(self, sample_trades_before, sample_trades_after):
        """Test impact measurement with positive improvement."""
        measurer = ImpactMeasurer()

        with patch.object(measurer, '_store_impact'):
            impact = measurer.measure_proposal_impact(
                proposal_id=1,
                trades_before=sample_trades_before,
                trades_after=sample_trades_after
            )

        assert impact is not None
        assert impact.proposal_id == 1
        assert impact.avg_pnl_delta > 0
        assert impact.edge_improvement > 0
        assert impact.total_trades_before == 25
        assert impact.total_trades_after == 25
        assert 0 <= impact.impact_score <= 100

    def test_measure_proposal_impact_negative(self, sample_trades_before):
        """Test impact measurement with negative performance."""
        measurer = ImpactMeasurer()

        trades_after_worse = []
        base_time = datetime.now(timezone.utc) - timedelta(days=2)

        for i in range(25):
            trade = Trade(
                id=i + 200,
                market_ticker="BTC-USD",
                platform="polymarket",
                direction="up",
                entry_price=52000,
                size=1.0,
                timestamp=base_time + timedelta(hours=i),
                settled=True,
                result="loss",
                pnl=-10.0,
                model_probability=0.55,
                market_price_at_entry=0.60,
                edge_at_entry=0.02,
                trading_mode="paper"
            )
            trades_after_worse.append(trade)

        with patch.object(measurer, '_store_impact'):
            impact = measurer.measure_proposal_impact(
                proposal_id=2,
                trades_before=sample_trades_before,
                trades_after=trades_after_worse
            )

        assert impact is not None
        assert impact.win_rate_delta < 0
        assert impact.avg_pnl_delta < 0
        assert impact.impact_score < 50

    def test_calculate_impact_score(self):
        """Test composite impact score calculation."""
        measurer = ImpactMeasurer()

        score = measurer._calculate_impact_score(
            sharpe_delta=0.5,
            win_rate_delta=0.1,
            avg_pnl_delta=5.0,
            edge_delta=0.05
        )

        assert 0 <= score <= 100
        assert score > 50

    def test_calculate_impact_score_negative(self):
        """Test impact score with negative deltas."""
        measurer = ImpactMeasurer()

        score = measurer._calculate_impact_score(
            sharpe_delta=-0.5,
            win_rate_delta=-0.2,
            avg_pnl_delta=-10.0,
            edge_delta=-0.1
        )

        assert 0 <= score <= 100
        assert score < 50


class TestRollbackManager:
    """Test suite for RollbackManager."""

    @pytest.fixture(autouse=True)
    def cleanup_test_strategy(self, db_session):
        for model in (StrategyProposal, StrategyConfig):
            db_session.query(model).filter(
                model.strategy_name == "test_strategy"
            ).delete(synchronize_session=False)
        db_session.commit()
        yield
        for model in (StrategyProposal, StrategyConfig):
            db_session.query(model).filter(
                model.strategy_name == "test_strategy"
            ).delete(synchronize_session=False)
        db_session.commit()

    def test_initialization(self):
        """Test RollbackManager initializes correctly."""
        manager = RollbackManager()
        assert manager is not None

    def test_create_snapshot_success(self, db_session):
        """Test snapshot creation for valid proposal and strategy."""
        manager = RollbackManager()

        config = StrategyConfig(
            strategy_name="test_strategy",
            enabled=True,
            interval_seconds=300,
            params='{"threshold": 0.7}'
        )
        db_session.add(config)

        proposal = StrategyProposal(
            strategy_name="test_strategy",
            change_details={},
            expected_impact="Test impact",
            admin_decision="pending"
        )
        db_session.add(proposal)
        db_session.commit()

        success = manager.create_snapshot(proposal.id, "test_strategy")

        assert success is True

        db_session.refresh(proposal)
        assert 'config_snapshot' in proposal.change_details
        assert proposal.change_details['config_snapshot']['strategy_name'] == "test_strategy"

        db_session.delete(proposal)
        db_session.delete(config)
        db_session.commit()

    def test_create_snapshot_strategy_not_found(self, db_session):
        """Test snapshot creation fails for non-existent strategy."""
        manager = RollbackManager()

        proposal = StrategyProposal(
            strategy_name="nonexistent",
            change_details={},
            expected_impact="Test",
            admin_decision="pending"
        )
        db_session.add(proposal)
        db_session.commit()

        success = manager.create_snapshot(proposal.id, "nonexistent")

        assert success is False

        db_session.delete(proposal)
        db_session.commit()

    def test_rollback_proposal_success(self, db_session):
        """Test successful proposal rollback."""
        manager = RollbackManager()

        config = StrategyConfig(
            strategy_name="rollback_test",
            enabled=True,
            interval_seconds=300,
            params='{"threshold": 0.8}'
        )
        db_session.add(config)

        proposal = StrategyProposal(
            strategy_name="rollback_test",
            change_details={
                'config_snapshot': {
                    'strategy_name': 'rollback_test',
                    'config_snapshot': {
                        'enabled': True,
                        'interval_seconds': 300,
                        'params': '{"threshold": 0.7}',
                        'mode': None
                    },
                    'snapshot_at': datetime.now(timezone.utc).isoformat(),
                    'proposal_id': 1
                }
            },
            expected_impact="Test rollback",
            admin_decision="approved"
        )
        db_session.add(proposal)
        db_session.commit()

        config.params = '{"threshold": 0.9}'
        db_session.commit()

        success = manager.rollback_proposal(proposal.id)

        assert success is True

        db_session.refresh(config)
        import json
        assert json.loads(config.params)['threshold'] == 0.7

        db_session.refresh(proposal)
        assert proposal.admin_decision == "rolled_back"
        assert 'rollback_history' in proposal.change_details

        db_session.delete(proposal)
        db_session.delete(config)
        db_session.commit()

    def test_rollback_proposal_not_approved(self, db_session):
        """Test rollback fails for non-approved proposal."""
        manager = RollbackManager()

        proposal = StrategyProposal(
            strategy_name="test",
            change_details={},
            expected_impact="Test",
            admin_decision="pending"
        )
        db_session.add(proposal)
        db_session.commit()

        success = manager.rollback_proposal(proposal.id)

        assert success is False

        db_session.delete(proposal)
        db_session.commit()

    def test_can_rollback_valid(self, db_session):
        """Test can_rollback returns True for valid proposal."""
        manager = RollbackManager()

        proposal = StrategyProposal(
            strategy_name="test",
            change_details={
                'config_snapshot': {
                    'strategy_name': 'test',
                    'config_snapshot': {}
                }
            },
            expected_impact="Test",
            admin_decision="approved"
        )
        db_session.add(proposal)
        db_session.commit()

        can_rollback = manager.can_rollback(proposal.id)

        assert can_rollback is True

        db_session.delete(proposal)
        db_session.commit()

    def test_can_rollback_no_snapshot(self, db_session):
        """Test can_rollback returns False without snapshot."""
        manager = RollbackManager()

        proposal = StrategyProposal(
            strategy_name="test",
            change_details={},
            expected_impact="Test",
            admin_decision="approved"
        )
        db_session.add(proposal)
        db_session.commit()

        can_rollback = manager.can_rollback(proposal.id)

        assert can_rollback is False

        db_session.delete(proposal)
        db_session.commit()

    def test_get_rollback_history(self, db_session):
        """Test retrieving rollback history."""
        manager = RollbackManager()

        proposal = StrategyProposal(
            strategy_name="test",
            change_details={
                'rollback_history': [
                    {
                        'rolled_back_at': datetime.now(timezone.utc).isoformat(),
                        'strategy_name': 'test'
                    }
                ]
            },
            expected_impact="Test",
            admin_decision="rolled_back"
        )
        db_session.add(proposal)
        db_session.commit()

        history = manager.get_rollback_history(proposal.id)

        assert history is not None
        assert len(history) == 1
        assert history[0]['strategy_name'] == 'test'

        db_session.delete(proposal)
        db_session.commit()
