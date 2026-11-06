import pytest
from fastapi.testclient import TestClient

from backend.api.main import app
from backend.config import settings
from backend.models.database import SessionLocal, JobQueue

import pytest
from fastapi.testclient import TestClient

from backend.api.main import app
from backend.config import settings
from backend.models.database import SessionLocal, JobQueue

PAYLOAD = {
    "token_address": "AbCdef1234567890",
    "network": "solana",
    "confidence": 0.9,
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


def test_anonymous_request_denied(client: TestClient) -> None:
    assert client.post("/api/v1/nexus/signal", json=PAYLOAD).status_code in (401, 403)


def test_invalid_key_denied(client: TestClient) -> None:
    assert client.post(
        "/api/v1/nexus/signal",
        headers={"Authorization": "Bearer wrong-key"},
        json=PAYLOAD,
    ).status_code == 401


def test_valid_key_is_received_and_durable(client: TestClient) -> None:
    headers = {"Authorization": "Bearer key1"}
    response = client.post("/api/v1/nexus/signal", headers=headers, json=PAYLOAD)
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "received"
    assert body["job_id"]

    db = SessionLocal()
    try:
        row = db.query(JobQueue).filter(JobQueue.id == int(body["job_id"])).first()
        assert row is not None
        assert row.job_type == "nexus_signal"
        assert row.idempotency_key == f"nexus:{PAYLOAD['network']}:{PAYLOAD['token_address']}"
        assert row.payload["token_address"] == PAYLOAD["token_address"]
        assert row.payload["network"] == PAYLOAD["network"]
    finally:
        db.close()


def test_repeated_signal_is_idempotent(client: TestClient) -> None:
    headers = {"Authorization": "Bearer key1"}
    first = client.post("/api/v1/nexus/signal", headers=headers, json=PAYLOAD)
    second = client.post("/api/v1/nexus/signal", headers=headers, json=PAYLOAD)
    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["job_id"] == second.json()["job_id"]


def test_x_nexus_key_header_authenticates(client: TestClient) -> None:
    assert client.post(
        "/api/v1/nexus/signal",
        headers={"X-Nexus-Key": "key1"},
        json=PAYLOAD,
    ).status_code == 200


def test_unsupported_network_rejected(client: TestClient) -> None:
    assert client.post(
        "/api/v1/nexus/signal",
        headers={"Authorization": "Bearer key1"},
        json={**PAYLOAD, "network": "polygon"},
    ).status_code == 422


def test_low_confidence_rejected(client: TestClient) -> None:
    response = client.post(
        "/api/v1/nexus/signal",
        headers={"Authorization": "Bearer key1"},
        json={**PAYLOAD, "confidence": 0.1},
    )
    assert response.status_code == 422
