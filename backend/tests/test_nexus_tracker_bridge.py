import pytest
from fastapi.testclient import TestClient

from backend.api.main import app
from backend.config import settings
from backend.models.database import SessionLocal, JobQueue

# Minimal tracker-style payload — same as route.ts POST body
TRACKER_PAYLOAD = {
    "payload": {
        "ticker": "BONK",
        "contract": "AbCdef1234567890",
        "ageMinutes": 12,
        "security": {
            "mintable": False,
            "freezeAuthority": False,
        },
        "distribution": {
            "devPercent": 0.0,
            "sniperPercent": 1.0,
        },
        "momentum": {
            "marketCap": 1000.0,
            "volume5m": 100.0,
        },
        "chain": "solana",
    },
    "deliver": True,
}


@pytest.fixture(autouse=True)
def nexus_config(monkeypatch):
    monkeypatch.setattr(settings, "NEXUS_INBOUND_API_KEYS", "key1", raising=False)
    monkeypatch.setenv("NEXUS_INBOUND_API_KEYS", "key1")
    yield
    monkeypatch.delattr(settings, "NEXUS_INBOUND_API_KEYS", raising=False)
    monkeypatch.delenv("NEXUS_INBOUND_API_KEYS", raising=False)


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def test_tracker_payload_forwarding(client: TestClient) -> None:
    headers = {"Authorization": "Bearer key1"}
    response = client.post(
        "/api/v1/nexus/signal",
        headers=headers,
        json=TRACKER_PAYLOAD,
    )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "received"
    assert data["job_id"]

    # Verify job contains mapped fields
    db = SessionLocal()
    try:
        row = db.query(JobQueue).filter(JobQueue.id == int(data["job_id"])).first()
        assert row is not None
        assert row.job_type == "nexus_signal"
        assert row.payload["token_address"] == "AbCdef1234567890"
        assert row.payload["network"] == "solana"
        assert row.payload["confidence"] == 0.75
        assert "source_payload" in row.payload["metadata"]
        assert "deliver" in row.payload["metadata"]
    finally:
        db.close()


def test_tracker_payload_with_missing_contract_fails(client: TestClient) -> None:
    headers = {"Authorization": "Bearer key1"}
    bad_payload = {**TRACKER_PAYLOAD, "payload": {**TRACKER_PAYLOAD["payload"], "contract": None}}
    response = client.post(
        "/api/v1/nexus/signal",
        headers=headers,
        json=bad_payload,
    )
    assert response.status_code == 422


def test_tracker_payload_network_fallback(client: TestClient) -> None:
    headers = {"Authorization": "Bearer key1"}
    fallback_payload = {**TRACKER_PAYLOAD, "payload": {**TRACKER_PAYLOAD["payload"], "chain": "polygon"}}
    response = client.post(
        "/api/v1/nexus/signal",
        headers=headers,
        json=fallback_payload,
    )
    assert response.status_code == 422
