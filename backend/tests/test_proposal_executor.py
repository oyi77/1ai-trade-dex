"""Tests for Proposal Executor - Wave 4e

Tests the proposal execution, impact measurement, and auto-rollback functionality.
"""

import pytest
import json
from datetime import datetime, timezone, timedelta
from unittest.mock import Mock, patch

from backend.core.proposal_executor import (
    ProposalExecutor,
    ExecutionResult,
    ImpactResult,
    execute_approved_proposals_job,
    measure_impact_and_rollback_job
)
from backend.models.database import (
    SessionLocal,
    StrategyProposal,
    StrategyConfig,
    Trade,
    AuditLog,
    Base
)


@pytest.fixture
def db_session():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    
    yield session
    
    session.close()


@pytest.fixture
def executor():
    return ProposalExecutor()


@pytest.fixture
def sample_strategy_config(db_session):
    config = StrategyConfig(
        strategy_name="test_strategy",
        enabled=True,
        interval_seconds=60,
        params=json.dumps({"min_edge": 0.05, "max_position_usd": 100})
    )
    db_session.add(config)
    db_session.commit()
    return config


@pytest.fixture
def approved_proposal(db_session, sample_strategy_config):
    proposal = StrategyProposal(
        strategy_name="test_strategy",
        change_details={"min_edge": 0.08, "max_position_usd": 150},
        expected_impact="Increase win rate by 5%",
        admin_decision="approved",
        admin_user_id="admin123",
        created_at=datetime.now(timezone.utc)
    )
    db_session.add(proposal)
    db_session.commit()
    return proposal


@pytest.fixture
def executed_proposal(db_session, sample_strategy_config):
    proposal = StrategyProposal(
        strategy_name="test_strategy",
        change_details={"min_edge": 0.08},
        expected_impact="Test impact",
        admin_decision="executed",
        admin_user_id="admin123",
        created_at=datetime.now(timezone.utc) - timedelta(hours=50),
        executed_at=datetime.now(timezone.utc) - timedelta(hours=48)
    )
    db_session.add(proposal)
    db_session.commit()
    
    audit = AuditLog(
        timestamp=proposal.executed_at,
        event_type="PROPOSAL_EXECUTED",
        entity_type="STRATEGY_CONFIG",
        entity_id=str(proposal.id),
        old_value={
            "strategy_name": "test_strategy",
            "enabled": True,
            "interval_seconds": 60,
            "params": {"min_edge": 0.05, "max_position_usd": 100}
        },
        new_value={
            "strategy_name": "test_strategy",
            "enabled": True,
            "interval_seconds": 60,
            "params": {"min_edge": 0.08, "max_position_usd": 100}
        },
        user_id="admin123"
    )
    db_session.add(audit)
    db_session.commit()
    
    return proposal


def test_execute_proposal_success(executor, db_session, approved_proposal, sample_strategy_config):
    proposal_id = approved_proposal.id
    
    with patch('backend.db.utils.SessionLocal', return_value=db_session):
        result = executor.execute_proposal(proposal_id)
    
    assert result is True
    
    updated_proposal = db_session.get(StrategyProposal, proposal_id)
    assert updated_proposal.admin_decision == "executed"
    assert updated_proposal.executed_at is not None
    
    updated_config = db_session.query(StrategyConfig).filter(
        StrategyConfig.strategy_name == "test_strategy"
    ).first()
    params = json.loads(updated_config.params)
    assert params["min_edge"] == 0.08
    assert params["max_position_usd"] == 150
    
    audit_log = db_session.query(AuditLog).filter(
        AuditLog.event_type == "PROPOSAL_EXECUTED"
    ).first()
    assert audit_log is not None
    assert audit_log.entity_id == str(proposal_id)


def test_execute_proposal_not_found(executor, db_session):
    with patch('backend.db.utils.SessionLocal', return_value=db_session):
        result = executor.execute_proposal(99999)
    
    assert result is False


def test_execute_proposal_wrong_status(executor, db_session, sample_strategy_config):
    proposal = StrategyProposal(
        strategy_name="test_strategy",
        change_details={"min_edge": 0.08},
        expected_impact="Test",
        admin_decision="pending",
        created_at=datetime.now(timezone.utc)
    )
    db_session.add(proposal)
    db_session.commit()
    
    with patch('backend.db.utils.SessionLocal', return_value=db_session):
        result = executor.execute_proposal(proposal.id)
    
    assert result is False


def test_execute_proposal_already_executed(executor, db_session, sample_strategy_config):
    proposal = StrategyProposal(
        strategy_name="test_strategy",
        change_details={"min_edge": 0.08},
        expected_impact="Test",
        admin_decision="approved",
        executed_at=datetime.now(timezone.utc),
        created_at=datetime.now(timezone.utc)
    )
    db_session.add(proposal)
    db_session.commit()
    
    with patch('backend.db.utils.SessionLocal', return_value=db_session):
        result = executor.execute_proposal(proposal.id)
    
    assert result is False


def test_execute_proposal_config_not_found(executor, db_session):
    proposal = StrategyProposal(
        strategy_name="nonexistent_strategy",
        change_details={"min_edge": 0.08},
        expected_impact="Test",
        admin_decision="approved",
        created_at=datetime.now(timezone.utc)
    )
    db_session.add(proposal)
    db_session.commit()
    
    with patch('backend.db.utils.SessionLocal', return_value=db_session):
        result = executor.execute_proposal(proposal.id)
    
    assert result is False


def create_trades(db_session, strategy_name, count, base_time, pnl_values):
    trades = []
    for i in range(count):
        trade = Trade(
            market_ticker="TEST-MARKET",
            platform="polymarket",
            direction="up",
            entry_price=0.5,
            size=10.0,
            timestamp=base_time + timedelta(hours=i),
            strategy=strategy_name,
            pnl=pnl_values[i] if i < len(pnl_values) else 5.0,
            model_probability=0.6,
            market_price_at_entry=0.5,
            edge_at_entry=0.1
        )
        trades.append(trade)
        db_session.add(trade)
    db_session.commit()
    return trades


def test_measure_impact_positive(executor, db_session, executed_proposal):
    execution_time = executed_proposal.executed_at
    
    before_pnls = [-5, -3, 2, 3, 4]
    after_pnls = [8, 10, 12, 9, 11]
    
    create_trades(
        db_session, "test_strategy", 5,
        execution_time - timedelta(hours=10),
        before_pnls
    )
    create_trades(
        db_session, "test_strategy", 5,
        execution_time + timedelta(hours=1),
        after_pnls
    )
    
    with patch('backend.db.utils.SessionLocal', return_value=db_session):
        result = executor.measure_impact(executed_proposal.id)
    
    assert result is not None
    assert result.sharpe_ratio_delta > 0
    assert result.trade_count == 5


def test_measure_impact_negative(executor, db_session, executed_proposal):
    execution_time = executed_proposal.executed_at
    
    before_pnls = [8, 10, 12, 9, 11]
    after_pnls = [-5, -3, -8, -2, -4]
    
    create_trades(
        db_session, "test_strategy", 5,
        execution_time - timedelta(hours=10),
        before_pnls
    )
    create_trades(
        db_session, "test_strategy", 5,
        execution_time + timedelta(hours=1),
        after_pnls
    )
    
    with patch('backend.db.utils.SessionLocal', return_value=db_session):
        result = executor.measure_impact(executed_proposal.id)
    
    assert result is not None
    assert result.sharpe_ratio_delta < 0
    assert result.pnl_delta < 0


def test_measure_impact_not_enough_trades(executor, db_session, executed_proposal):
    execution_time = executed_proposal.executed_at
    
    create_trades(
        db_session, "test_strategy", 2,
        execution_time + timedelta(hours=1),
        [5, 10]
    )
    
    with patch('backend.db.utils.SessionLocal', return_value=db_session):
        result = executor.measure_impact(executed_proposal.id)
    
    assert result is None


def test_measure_impact_proposal_not_executed(executor, db_session, approved_proposal):
    with patch('backend.db.utils.SessionLocal', return_value=db_session):
        result = executor.measure_impact(approved_proposal.id)
    
    assert result is None


def test_auto_rollback_negative_impact(executor, db_session, executed_proposal, sample_strategy_config):
    execution_time = executed_proposal.executed_at
    proposal_id = executed_proposal.id
    
    before_pnls = [8, 10, 12, 9, 11]
    after_pnls = [-10, -12, -15, -8, -11]
    
    create_trades(
        db_session, "test_strategy", 5,
        execution_time - timedelta(hours=10),
        before_pnls
    )
    create_trades(
        db_session, "test_strategy", 5,
        execution_time + timedelta(hours=1),
        after_pnls
    )
    
    with patch('backend.db.utils.SessionLocal', return_value=db_session):
        rolled_back = executor.auto_rollback_if_negative(proposal_id)
    
    assert rolled_back is True
    
    updated_proposal = db_session.get(StrategyProposal, proposal_id)
    assert updated_proposal.admin_decision == "rolled_back"
    
    updated_config = db_session.query(StrategyConfig).filter(
        StrategyConfig.strategy_name == "test_strategy"
    ).first()
    params = json.loads(updated_config.params)
    assert params["min_edge"] == 0.05
    assert params["max_position_usd"] == 100
    
    rollback_log = db_session.query(AuditLog).filter(
        AuditLog.event_type == "PROPOSAL_ROLLED_BACK"
    ).first()
    assert rollback_log is not None


def test_auto_rollback_positive_impact(executor, db_session, executed_proposal):
    execution_time = executed_proposal.executed_at
    proposal_id = executed_proposal.id
    
    before_pnls = [-5, -3, 2, 3, 4]
    after_pnls = [8, 10, 12, 9, 11]
    
    create_trades(
        db_session, "test_strategy", 5,
        execution_time - timedelta(hours=10),
        before_pnls
    )
    create_trades(
        db_session, "test_strategy", 5,
        execution_time + timedelta(hours=1),
        after_pnls
    )
    
    with patch('backend.db.utils.SessionLocal', return_value=db_session):
        rolled_back = executor.auto_rollback_if_negative(proposal_id)
    
    assert rolled_back is False
    
    updated_proposal = db_session.get(StrategyProposal, proposal_id)
    assert updated_proposal.admin_decision == "executed"


def test_auto_rollback_no_audit_log(executor, db_session, sample_strategy_config):
    proposal = StrategyProposal(
        strategy_name="test_strategy",
        change_details={"min_edge": 0.08},
        expected_impact="Test",
        admin_decision="executed",
        executed_at=datetime.now(timezone.utc) - timedelta(hours=48),
        created_at=datetime.now(timezone.utc) - timedelta(hours=50)
    )
    db_session.add(proposal)
    db_session.commit()
    
    execution_time = proposal.executed_at
    
    before_pnls = [8, 10, 12, 9, 11]
    after_pnls = [-10, -12, -15, -8, -11]
    
    create_trades(
        db_session, "test_strategy", 5,
        execution_time - timedelta(hours=10),
        before_pnls
    )
    create_trades(
        db_session, "test_strategy", 5,
        execution_time + timedelta(hours=1),
        after_pnls
    )
    
    with patch('backend.db.utils.SessionLocal', return_value=db_session):
        rolled_back = executor.auto_rollback_if_negative(proposal.id)
    
    assert rolled_back is False


def test_get_executed_proposals(executor, db_session, executed_proposal):
    with patch('backend.db.utils.SessionLocal', return_value=db_session):
        proposals = executor.get_executed_proposals(limit=10)
    
    assert len(proposals) == 1
    assert proposals[0]["id"] == executed_proposal.id
    assert proposals[0]["strategy_name"] == "test_strategy"


def test_calculate_sharpe_ratio(executor):
    trades = [
        Mock(pnl=5.0),
        Mock(pnl=10.0),
        Mock(pnl=-3.0),
        Mock(pnl=8.0),
        Mock(pnl=2.0)
    ]
    
    sharpe = executor._calculate_sharpe_ratio(trades)
    assert isinstance(sharpe, float)
    assert sharpe != 0.0


def test_calculate_sharpe_ratio_empty(executor):
    sharpe = executor._calculate_sharpe_ratio([])
    assert sharpe == 0.0


def test_calculate_sharpe_ratio_single_trade(executor):
    trades = [Mock(pnl=5.0)]
    sharpe = executor._calculate_sharpe_ratio(trades)
    assert sharpe == 0.0


def test_calculate_win_rate(executor):
    trades = [
        Mock(pnl=5.0),
        Mock(pnl=-3.0),
        Mock(pnl=8.0),
        Mock(pnl=-2.0),
        Mock(pnl=10.0)
    ]
    
    win_rate = executor._calculate_win_rate(trades)
    assert win_rate == 0.6


def test_calculate_win_rate_empty(executor):
    win_rate = executor._calculate_win_rate([])
    assert win_rate == 0.0


def test_calculate_avg_pnl(executor):
    trades = [
        Mock(pnl=5.0),
        Mock(pnl=10.0),
        Mock(pnl=-3.0),
        Mock(pnl=8.0),
        Mock(pnl=2.0)
    ]
    
    avg_pnl = executor._calculate_avg_pnl(trades)
    assert avg_pnl == 4.4


def test_calculate_avg_pnl_empty(executor):
    avg_pnl = executor._calculate_avg_pnl([])
    assert avg_pnl == 0.0


@pytest.mark.asyncio
async def test_execute_approved_proposals_job(db_session, approved_proposal, sample_strategy_config):
    proposal_id = approved_proposal.id
    
    with patch('backend.db.utils.SessionLocal', return_value=db_session):
        await execute_approved_proposals_job()
    
    updated_proposal = db_session.get(StrategyProposal, proposal_id)
    assert updated_proposal.admin_decision == "executed"


@pytest.mark.asyncio
async def test_measure_impact_and_rollback_job(db_session, executed_proposal, sample_strategy_config):
    execution_time = executed_proposal.executed_at
    proposal_id = executed_proposal.id
    
    before_pnls = [8, 10, 12, 9, 11]
    after_pnls = [-10, -12, -15, -8, -11]
    
    create_trades(
        db_session, "test_strategy", 5,
        execution_time - timedelta(hours=10),
        before_pnls
    )
    create_trades(
        db_session, "test_strategy", 5,
        execution_time + timedelta(hours=1),
        after_pnls
    )
    
    with patch('backend.db.utils.SessionLocal', return_value=db_session):
        with patch('backend.core.proposal_executor.ProposalExecutor.get_executed_proposals') as mock_get:
            mock_get.return_value = [{
                "id": proposal_id,
                "strategy_name": "test_strategy",
                "executed_at": execution_time.isoformat()
            }]
            
            await measure_impact_and_rollback_job()
    
    updated_proposal = db_session.get(StrategyProposal, proposal_id)
    assert updated_proposal.admin_decision == "rolled_back"
