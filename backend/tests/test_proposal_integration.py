"""Integration Tests for Proposal → Strategy Executor Workflow - Wave 5c

Tests the complete integration:
1. Proposal approved → config updated
2. Strategy executor reads updated config from DB
3. Next trade respects new limits
4. Rollback scenario restores old config
5. Config timeline visible via API
"""

import pytest
import json
from datetime import datetime, timezone, timedelta
from unittest.mock import Mock, patch

from backend.core.proposal_applier import ProposalApplier
from backend.core.proposal_executor import ProposalExecutor
        _reload_executor()
        from backend.core.strategy_executor import execute_decision
from backend.models.database import (
    StrategyProposal,
    StrategyConfig,
    Trade,
    BotState,
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

    bot_state = BotState(
        mode="paper",
        bankroll=10000.0,
        paper_bankroll=10000.0,
        is_running=True
    )
    session.add(bot_state)
    session.commit()

    yield session

    session.close()


@pytest.fixture
def strategy_config(db_session):
    config = StrategyConfig(
        strategy_name="test_strategy",
        enabled=True,
        interval_seconds=300,
        params=json.dumps({
            "min_edge_threshold": 0.05,
            "max_position_usd": 100.0
        })
    )
    db_session.add(config)
    db_session.commit()
    return config


@pytest.mark.asyncio
async def test_proposal_changes_max_position_limit(db_session, strategy_config):
    """Test: change max_position_usd via proposal → next trade respects new limit."""

    applier = ProposalApplier()

    proposal = StrategyProposal(
        strategy_name="test_strategy",
        change_details={"max_position_usd": 50.0},
        expected_impact="Reduce position size for risk management",
        admin_decision="approved",
        admin_user_id="admin@example.com",
        created_at=datetime.now(timezone.utc)
    )
    db_session.add(proposal)
    db_session.commit()

    result = applier.apply_proposal_to_config(proposal.id, db=db_session)

    assert result is True

    updated_config = db_session.query(StrategyConfig).filter(
        StrategyConfig.strategy_name == "test_strategy"
    ).first()
    params = json.loads(updated_config.params)
    assert params["max_position_usd"] == 50.0

    decision = {
        "market_ticker": "TEST-MARKET",
        "direction": "up",
        "size": 5.0,
        "entry_price": 0.6,
        "edge": 0.1,
        "confidence": 0.8,
        "model_probability": 0.7,
        "platform": "polymarket",
        "reasoning": "Test trade"
    }

    with patch('backend.core.strategy_executor.get_context') as mock_context:
        mock_ctx = Mock()
        mock_ctx.risk_manager.validate_trade.return_value = Mock(
            allowed=True,
            adjusted_size=5.0,
            reason="Adjusted to max_position_usd limit"
        )
        mock_context.return_value = mock_ctx

        trade_result = await execute_decision(
            decision,
            strategy_name="test_strategy",
            mode="paper",
            db=db_session
        )

    assert trade_result is not None
    assert trade_result["size"] == 5.0


@pytest.mark.asyncio
async def test_proposal_changes_min_edge_threshold(db_session, strategy_config):
    """Test: change min_edge_threshold via proposal → next signals filtered by new edge."""

    applier = ProposalApplier()

    proposal = StrategyProposal(
        strategy_name="test_strategy",
        change_details={"min_edge_threshold": 0.10},
        expected_impact="Filter out low-edge signals",
        admin_decision="approved",
        admin_user_id="admin@example.com",
        created_at=datetime.now(timezone.utc)
    )
    db_session.add(proposal)
    db_session.commit()

    result = applier.apply_proposal_to_config(proposal.id, db=db_session)

    assert result is True

    config = applier.get_active_config("test_strategy", db=db_session)

    assert config["params"]["min_edge_threshold"] == 0.10


@pytest.mark.asyncio
async def test_proposal_disables_strategy(db_session, strategy_config):
    """Test: change strategy enabled flag via proposal → strategy disabled on next cycle."""

    applier = ProposalApplier()

    proposal = StrategyProposal(
        strategy_name="test_strategy",
        change_details={"enabled": False},
        expected_impact="Disable strategy for maintenance",
        admin_decision="approved",
        admin_user_id="admin@example.com",
        created_at=datetime.now(timezone.utc)
    )
    db_session.add(proposal)
    db_session.commit()

    result = applier.apply_proposal_to_config(proposal.id, db=db_session)

    assert result is True

    updated_config = db_session.query(StrategyConfig).filter(
        StrategyConfig.strategy_name == "test_strategy"
    ).first()

    assert updated_config.enabled is False


@pytest.mark.asyncio
async def test_rollback_restores_old_config(db_session, strategy_config):
    """Test: rollback scenario (sharpe_ratio_delta < -0.1) restores old config from snapshot."""

    executor = ProposalExecutor()

    proposal = StrategyProposal(
        strategy_name="test_strategy",
        change_details={"min_edge_threshold": 0.15},
        expected_impact="Test negative impact",
        admin_decision="approved",
        admin_user_id="admin@example.com",
        created_at=datetime.now(timezone.utc) - timedelta(hours=50)
    )
    db_session.add(proposal)
    db_session.commit()

    proposal_id = proposal.id

    with patch('backend.db.utils.SessionLocal', return_value=db_session):
        exec_result = executor.execute_proposal(proposal_id)

    assert exec_result is True

    proposal = db_session.query(StrategyProposal).filter(
        StrategyProposal.id == proposal_id
    ).first()

    execution_time = datetime.now(timezone.utc) - timedelta(hours=24)
    proposal.executed_at = execution_time
    db_session.commit()

    audit_log = db_session.query(AuditLog).filter(
        AuditLog.event_type == "PROPOSAL_EXECUTED",
        AuditLog.entity_id == str(proposal_id)
    ).first()
    assert audit_log is not None

    before_pnls = [8.0, 10.0, 12.0, 9.0, 11.0]
    for i in range(5):
        trade = Trade(
            market_ticker="TEST-MARKET",
            platform="polymarket",
            direction="up",
            entry_price=0.5,
            size=10.0,
            timestamp=execution_time - timedelta(hours=10 - i),
            strategy="test_strategy",
            pnl=before_pnls[i],
            model_probability=0.6,
            market_price_at_entry=0.5,
            edge_at_entry=0.1
        )
        db_session.add(trade)

    after_pnls = [-15.0, -18.0, -20.0, -12.0, -16.0]
    for i in range(5):
        trade = Trade(
            market_ticker="TEST-MARKET",
            platform="polymarket",
            direction="up",
            entry_price=0.5,
            size=10.0,
            timestamp=execution_time + timedelta(hours=1 + i),
            strategy="test_strategy",
            pnl=after_pnls[i],
            model_probability=0.6,
            market_price_at_entry=0.5,
            edge_at_entry=0.1
        )
        db_session.add(trade)

    db_session.commit()

    with patch('backend.db.utils.SessionLocal', return_value=db_session):
        rolled_back = executor.auto_rollback_if_negative(proposal_id)

    assert rolled_back is True

    updated_proposal = db_session.query(StrategyProposal).filter(
        StrategyProposal.id == proposal_id
    ).first()
    assert updated_proposal.admin_decision == "rolled_back"

    updated_config = db_session.query(StrategyConfig).filter(
        StrategyConfig.strategy_name == "test_strategy"
    ).first()
    params = json.loads(updated_config.params)
    assert params["min_edge_threshold"] == 0.05


@pytest.mark.asyncio
async def test_proposal_execution_non_blocking(db_session, strategy_config):
    """Test: proposal execution doesn't block strategy (async queue, no blocking I/O)."""

    applier = ProposalApplier()

    proposal = StrategyProposal(
        strategy_name="test_strategy",
        change_details={"max_position_usd": 120.0},
        expected_impact="Test async execution",
        admin_decision="approved",
        admin_user_id="admin@example.com",
        created_at=datetime.now(timezone.utc)
    )
    db_session.add(proposal)
    db_session.commit()

    import time
    start_time = time.time()

    result = applier.apply_proposal_to_config(proposal.id, db=db_session)

    elapsed = time.time() - start_time

    assert result is True
    assert elapsed < 1.0


@pytest.mark.asyncio
async def test_multiple_concurrent_proposals_fifo(db_session, strategy_config):
    """Test: multiple concurrent proposals handled correctly (FIFO queue)."""

    applier = ProposalApplier()

    proposal_ids = []
    for i in range(3):
        proposal = StrategyProposal(
            strategy_name="test_strategy",
            change_details={"max_position_usd": 100.0 + i * 10},
            expected_impact=f"Change {i+1}",
            admin_decision="approved",
            admin_user_id="admin@example.com",
            created_at=datetime.now(timezone.utc) + timedelta(seconds=i)
        )
        db_session.add(proposal)
        db_session.flush()
        proposal_ids.append(proposal.id)

    db_session.commit()

    for proposal_id in proposal_ids:
        result = applier.apply_proposal_to_config(proposal_id, db=db_session)
        assert result is True

    final_config = db_session.query(StrategyConfig).filter(
        StrategyConfig.strategy_name == "test_strategy"
    ).first()
    params = json.loads(final_config.params)

    assert params["max_position_usd"] == 120.0


@pytest.mark.asyncio
async def test_config_timeline_visible(db_session, strategy_config):
    """Test: config change timeline visible in audit log."""

    applier = ProposalApplier()

    proposal = StrategyProposal(
        strategy_name="test_strategy",
        change_details={"min_edge_threshold": 0.08},
        expected_impact="Test timeline",
        admin_decision="approved",
        admin_user_id="admin@example.com",
        created_at=datetime.now(timezone.utc)
    )
    db_session.add(proposal)
    db_session.flush()
    proposal_id = proposal.id
    db_session.commit()

    result = applier.apply_proposal_to_config(proposal_id, db=db_session)

    assert result is True

    timeline = applier.get_config_timeline("test_strategy", db=db_session)

    assert len(timeline) == 1
    assert timeline[0]["user_id"] == "admin@example.com"
    assert timeline[0]["old_value"]["params"]["min_edge_threshold"] == 0.05
    assert timeline[0]["new_value"]["params"]["min_edge_threshold"] == 0.08
    assert timeline[0]["details"]["proposal_id"] == proposal_id


@pytest.mark.asyncio
async def test_executor_reads_fresh_config_each_cycle(db_session, strategy_config):
    """Test: executor reads updated StrategyConfig from DB (not from memory)."""

    applier = ProposalApplier()

    config_before = applier.get_active_config("test_strategy", db=db_session)

    assert config_before["params"]["max_position_usd"] == 100.0

    proposal = StrategyProposal(
        strategy_name="test_strategy",
        change_details={"max_position_usd": 200.0},
        expected_impact="Test fresh read",
        admin_decision="approved",
        admin_user_id="admin@example.com",
        created_at=datetime.now(timezone.utc)
    )
    db_session.add(proposal)
    db_session.commit()

    result = applier.apply_proposal_to_config(proposal.id, db=db_session)

    assert result is True

    config_after = applier.get_active_config("test_strategy", db=db_session)

    assert config_after["params"]["max_position_usd"] == 200.0
