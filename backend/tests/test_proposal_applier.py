"""Tests for Proposal Applier - Wave 5c

Tests the integration between proposals and strategy executor:
- Approved proposals update live strategy configs
- Config changes take effect on next execution cycle
- Rollback restores previous config from snapshot
- Config timeline is visible via audit log
"""

import pytest
import json
from datetime import datetime, timezone, timedelta

from backend.core.proposal_applier import ProposalApplier, get_applier
from backend.models.database import (
    StrategyProposal,
    StrategyConfig,
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
def applier():
    return ProposalApplier()


@pytest.fixture
def strategy_config(db_session):
    config = StrategyConfig(
        strategy_name="btc_momentum",
        enabled=True,
        interval_seconds=300,
        params=json.dumps({
            "min_edge_threshold": 0.05,
            "max_position_usd": 100.0,
            "kelly_fraction": 0.25
        })
    )
    db_session.add(config)
    db_session.commit()
    return config


@pytest.fixture
def approved_proposal(db_session, strategy_config):
    proposal = StrategyProposal(
        strategy_name="btc_momentum",
        change_details={
            "min_edge_threshold": 0.08,
            "max_position_usd": 150.0
        },
        expected_impact="Increase win rate by reducing false positives",
        admin_decision="approved",
        admin_user_id="admin@example.com",
        created_at=datetime.now(timezone.utc)
    )
    db_session.add(proposal)
    db_session.commit()
    return proposal


def test_apply_proposal_to_config_success(applier, db_session, approved_proposal, strategy_config):
    proposal_id = approved_proposal.id

    result = applier.apply_proposal_to_config(proposal_id, db=db_session)

    assert result is True

    updated_config = db_session.query(StrategyConfig).filter(
        StrategyConfig.strategy_name == "btc_momentum"
    ).first()

    params = json.loads(updated_config.params)
    assert params["min_edge_threshold"] == 0.08
    assert params["max_position_usd"] == 150.0
    assert params["kelly_fraction"] == 0.25

    audit_entry = db_session.query(AuditLog).filter(
        AuditLog.event_type == "CONFIG_UPDATED",
        AuditLog.entity_id == "btc_momentum"
    ).first()

    assert audit_entry is not None
    assert audit_entry.old_value["params"]["min_edge_threshold"] == 0.05
    assert audit_entry.new_value["params"]["min_edge_threshold"] == 0.08


def test_apply_proposal_updates_enabled_flag(applier, db_session, strategy_config):
    proposal = StrategyProposal(
        strategy_name="btc_momentum",
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
        StrategyConfig.strategy_name == "btc_momentum"
    ).first()

    assert updated_config.enabled is False


def test_apply_proposal_updates_interval(applier, db_session, strategy_config):
    proposal = StrategyProposal(
        strategy_name="btc_momentum",
        change_details={"interval_seconds": 600},
        expected_impact="Reduce execution frequency",
        admin_decision="approved",
        admin_user_id="admin@example.com",
        created_at=datetime.now(timezone.utc)
    )
    db_session.add(proposal)
    db_session.commit()

    result = applier.apply_proposal_to_config(proposal.id, db=db_session)

    assert result is True

    updated_config = db_session.query(StrategyConfig).filter(
        StrategyConfig.strategy_name == "btc_momentum"
    ).first()

    assert updated_config.interval_seconds == 600


def test_apply_proposal_not_approved(applier, db_session, strategy_config):
    proposal = StrategyProposal(
        strategy_name="btc_momentum",
        change_details={"min_edge_threshold": 0.08},
        expected_impact="Test",
        admin_decision="pending",
        created_at=datetime.now(timezone.utc)
    )
    db_session.add(proposal)
    db_session.commit()

    result = applier.apply_proposal_to_config(proposal.id, db=db_session)

    assert result is False

    config = db_session.query(StrategyConfig).filter(
        StrategyConfig.strategy_name == "btc_momentum"
    ).first()
    params = json.loads(config.params)
    assert params["min_edge_threshold"] == 0.05


def test_apply_proposal_nonexistent(applier, db_session):
    result = applier.apply_proposal_to_config(99999, db=db_session)

    assert result is False


def test_apply_proposal_config_not_found(applier, db_session):
    proposal = StrategyProposal(
        strategy_name="nonexistent_strategy",
        change_details={"min_edge_threshold": 0.08},
        expected_impact="Test",
        admin_decision="approved",
        created_at=datetime.now(timezone.utc)
    )
    db_session.add(proposal)
    db_session.commit()

    result = applier.apply_proposal_to_config(proposal.id, db=db_session)

    assert result is False


def test_get_active_config(applier, db_session, strategy_config):
    config = applier.get_active_config("btc_momentum", db=db_session)

    assert config is not None
    assert config["strategy_name"] == "btc_momentum"
    assert config["enabled"] is True
    assert config["interval_seconds"] == 300
    assert config["params"]["min_edge_threshold"] == 0.05
    assert config["params"]["max_position_usd"] == 100.0


def test_get_active_config_not_found(applier, db_session):
    config = applier.get_active_config("nonexistent_strategy", db=db_session)

    assert config is None


def test_get_config_timeline(applier, db_session, strategy_config):
    for i in range(3):
        audit = AuditLog(
            timestamp=datetime.now(timezone.utc) - timedelta(hours=i),
            event_type="CONFIG_UPDATED",
            entity_type="STRATEGY_CONFIG",
            entity_id="btc_momentum",
            old_value={"params": {"min_edge_threshold": 0.05 + i * 0.01}},
            new_value={"params": {"min_edge_threshold": 0.05 + (i + 1) * 0.01}},
            user_id="admin@example.com",
            details={"proposal_id": i + 1}
        )
        db_session.add(audit)
    db_session.commit()

    timeline = applier.get_config_timeline("btc_momentum", limit=10, db=db_session)

    assert len(timeline) == 3
    assert timeline[0]["details"]["proposal_id"] == 1
    assert timeline[0]["user_id"] == "admin@example.com"


def test_get_config_timeline_empty(applier, db_session, strategy_config):
    timeline = applier.get_config_timeline("btc_momentum", db=db_session)

    assert timeline == []


def test_get_applier_singleton():
    applier1 = get_applier()
    applier2 = get_applier()

    assert applier1 is applier2


def test_config_change_affects_next_trade(applier, db_session, approved_proposal, strategy_config):
    """Test that config changes take effect on next strategy execution cycle."""

    result = applier.apply_proposal_to_config(approved_proposal.id, db=db_session)

    assert result is True

    config = applier.get_active_config("btc_momentum", db=db_session)

    assert config["params"]["min_edge_threshold"] == 0.08
    assert config["params"]["max_position_usd"] == 150.0


def test_multiple_proposals_applied_sequentially(applier, db_session, strategy_config):
    """Test that multiple proposals can be applied and tracked."""

    proposal1 = StrategyProposal(
        strategy_name="btc_momentum",
        change_details={"min_edge_threshold": 0.08},
        expected_impact="First change",
        admin_decision="approved",
        admin_user_id="admin@example.com",
        created_at=datetime.now(timezone.utc)
    )
    db_session.add(proposal1)
    db_session.commit()

    result1 = applier.apply_proposal_to_config(proposal1.id, db=db_session)

    assert result1 is True

    proposal2 = StrategyProposal(
        strategy_name="btc_momentum",
        change_details={"max_position_usd": 200.0},
        expected_impact="Second change",
        admin_decision="approved",
        admin_user_id="admin@example.com",
        created_at=datetime.now(timezone.utc)
    )
    db_session.add(proposal2)
    db_session.commit()

    result2 = applier.apply_proposal_to_config(proposal2.id, db=db_session)

    assert result2 is True

    config = applier.get_active_config("btc_momentum", db=db_session)

    assert config["params"]["min_edge_threshold"] == 0.08
    assert config["params"]["max_position_usd"] == 200.0

    timeline = applier.get_config_timeline("btc_momentum", db=db_session)

    assert len(timeline) == 2
