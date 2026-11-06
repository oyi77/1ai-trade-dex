import os

import pytest
from fastapi.testclient import TestClient

from backend.api.main import app
from backend.config import settings

PAYLOAD = {
    "payload": {
        "ticker": "BONK",
        "contract": "AbCdef1234567890",
        "ageMinutes": 12,
        "security": {"mintable": False, "freezeAuthority": False, "honeypot": False},
        "distribution": {"devPercent": 0.0},
        "momentum": {"marketCap": 1000.0, "volume5m": 100.0},
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


def test_debug(client: TestClient) -> None:
    response = client.post(
        "/api/v1/nexus/signal",
        headers={"Authorization": "Bearer key1"},
        json=PAYLOAD,
    )
    assert False, f"STATUS={response.status_code} TEXT={response.text}"