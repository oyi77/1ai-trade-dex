"""Integration tests for Wave 4d - Proposal Approval UI + Workflows + Backend Enforcement."""

import pytest
from datetime import datetime, timezone

from backend.models.database import StrategyProposal
from backend.config import settings


@pytest.fixture
def admin_headers():
    """Create admin authorization headers."""
    if settings.ADMIN_API_KEY:
        return {"Authorization": f"Bearer {settings.ADMIN_API_KEY}"}
    return {}


@pytest.fixture
def sample_proposal(db):
    """Create a sample proposal in the database."""
    proposal = StrategyProposal(
        strategy_name="btc_oracle",
        change_details={"min_edge": 0.08, "max_position_usd": 150},
        expected_impact="Increase win rate by 5% and reduce drawdown",
        admin_decision="pending",
        created_at=datetime.now(timezone.utc)
    )
    db.add(proposal)
    db.commit()
    db.refresh(proposal)
    return proposal


def test_list_pending_proposals(client, admin_headers, sample_proposal):
    """Test listing pending proposals."""
    response = client.get("/api/v1/proposals?status=pending", headers=admin_headers)

    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["id"] == sample_proposal.id
    assert data[0]["strategy_name"] == "btc_oracle"
    assert data[0]["admin_decision"] == "pending"


def test_approve_proposal_as_admin(client, admin_headers, sample_proposal, db):
    """Test approving a proposal as admin."""
    response = client.post(
        f"/api/v1/proposals/{sample_proposal.id}/approve",
        json={"admin_user_id": "admin123", "reason": "Good improvement based on recent data"},
        headers=admin_headers
    )

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "approved"
    assert data["proposal_id"] == sample_proposal.id

    db.refresh(sample_proposal)
    assert sample_proposal.admin_decision == "approved"
    assert sample_proposal.admin_user_id == "admin123"
    assert sample_proposal.admin_decision_reason == "Good improvement based on recent data"
    assert sample_proposal.executed_at is not None


def test_reject_proposal_as_admin(client, admin_headers, sample_proposal, db):
    """Test rejecting a proposal as admin."""
    response = client.post(
        f"/api/v1/proposals/{sample_proposal.id}/reject",
        json={"admin_user_id": "admin123", "reason": "Not enough data to support this change"},
        headers=admin_headers
    )

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "rejected"
    assert data["proposal_id"] == sample_proposal.id

    db.refresh(sample_proposal)
    assert sample_proposal.admin_decision == "rejected"
    assert sample_proposal.admin_user_id == "admin123"
    assert sample_proposal.admin_decision_reason == "Not enough data to support this change"


def test_approve_proposal_without_admin_auth(client, sample_proposal):
    """Test that non-admin cannot approve proposals."""
    response = client.post(
        f"/api/v1/proposals/{sample_proposal.id}/approve",
        json={"admin_user_id": "user123", "reason": "Looks good"}
    )

    if settings.ADMIN_API_KEY:
        assert response.status_code == 401
    else:
        assert response.status_code in [200, 401]


def test_reject_proposal_without_admin_auth(client, sample_proposal):
    """Test that non-admin cannot reject proposals."""
    response = client.post(
        f"/api/v1/proposals/{sample_proposal.id}/reject",
        json={"admin_user_id": "user123", "reason": "Not good"}
    )

    if settings.ADMIN_API_KEY:
        assert response.status_code == 401
    else:
        assert response.status_code in [200, 401]


def test_approve_nonexistent_proposal(client, admin_headers):
    """Test approving a proposal that doesn't exist."""
    response = client.post(
        "/api/v1/proposals/99999/approve",
        json={"admin_user_id": "admin123", "reason": "Test"},
        headers=admin_headers
    )

    assert response.status_code == 404


def test_reject_nonexistent_proposal(client, admin_headers):
    """Test rejecting a proposal that doesn't exist."""
    response = client.post(
        "/api/v1/proposals/99999/reject",
        json={"admin_user_id": "admin123", "reason": "Test"},
        headers=admin_headers
    )

    assert response.status_code == 404


def test_approve_already_approved_proposal(client, admin_headers, sample_proposal, db):
    """Test that already approved proposals cannot be approved again."""
    sample_proposal.admin_decision = "approved"
    sample_proposal.admin_user_id = "admin123"
    db.commit()

    response = client.post(
        f"/api/v1/proposals/{sample_proposal.id}/approve",
        json={"admin_user_id": "admin456", "reason": "Approve again"},
        headers=admin_headers
    )

    assert response.status_code == 404


def test_reject_already_rejected_proposal(client, admin_headers, sample_proposal, db):
    """Test that already rejected proposals cannot be rejected again."""
    sample_proposal.admin_decision = "rejected"
    sample_proposal.admin_user_id = "admin123"
    db.commit()

    response = client.post(
        f"/api/v1/proposals/{sample_proposal.id}/reject",
        json={"admin_user_id": "admin456", "reason": "Reject again"},
        headers=admin_headers
    )

    assert response.status_code == 404


def test_proposal_workflow_state_transitions(client, admin_headers, db):
    """Test complete proposal workflow: Draft → Pending → Approved."""
    proposal = StrategyProposal(
        strategy_name="weather_emos",
        change_details={"min_temp_threshold": 32.5},
        expected_impact="Better temperature predictions",
        admin_decision="pending",
        created_at=datetime.now(timezone.utc)
    )
    db.add(proposal)
    db.commit()
    db.refresh(proposal)

    assert proposal.admin_decision == "pending"

    response = client.post(
        f"/api/v1/proposals/{proposal.id}/approve",
        json={"admin_user_id": "admin123", "reason": "Approved after review"},
        headers=admin_headers
    )

    assert response.status_code == 200

    db.refresh(proposal)
    assert proposal.admin_decision == "approved"
    assert proposal.admin_user_id == "admin123"
    assert proposal.executed_at is not None


def test_approval_requires_reason(client, admin_headers, sample_proposal):
    """Test that approval requires a reason."""
    response = client.post(
        f"/api/v1/proposals/{sample_proposal.id}/approve",
        json={"admin_user_id": "admin123", "reason": ""},
        headers=admin_headers
    )

    assert response.status_code in [400, 422]


def test_rejection_requires_reason(client, admin_headers, sample_proposal):
    """Test that rejection requires a reason."""
    response = client.post(
        f"/api/v1/proposals/{sample_proposal.id}/reject",
        json={"admin_user_id": "admin123", "reason": ""},
        headers=admin_headers
    )

    assert response.status_code in [400, 422]


def test_list_proposals_filters_by_status(client, admin_headers, db):
    """Test that listing proposals filters by status correctly."""
    pending_proposal = StrategyProposal(
        strategy_name="strategy1",
        change_details={},
        expected_impact="Impact 1",
        admin_decision="pending",
        created_at=datetime.now(timezone.utc)
    )
    approved_proposal = StrategyProposal(
        strategy_name="strategy2",
        change_details={},
        expected_impact="Impact 2",
        admin_decision="approved",
        created_at=datetime.now(timezone.utc)
    )
    db.add_all([pending_proposal, approved_proposal])
    db.commit()

    response = client.get("/api/v1/proposals?status=pending", headers=admin_headers)
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["admin_decision"] == "pending"

    response = client.get("/api/v1/proposals?status=approved", headers=admin_headers)
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["admin_decision"] == "approved"
