"""Integration tests for admin API endpoints."""

import sys
import pytest
from fastapi.testclient import TestClient
from unittest.mock import MagicMock

# Stub out apscheduler and backend.core.scheduler before importing the app
# so the startup event does not crash on the missing apscheduler package.
_sched_stub = MagicMock()
_sched_stub.start_scheduler = MagicMock()
_sched_stub.stop_scheduler = MagicMock()
_sched_stub.log_event = MagicMock()
_sched_stub.is_scheduler_running = MagicMock(return_value=False)
sys.modules.setdefault("apscheduler", MagicMock())
sys.modules.setdefault("apscheduler.schedulers", MagicMock())
sys.modules.setdefault("apscheduler.schedulers.asyncio", MagicMock())
sys.modules["backend.core.scheduler"] = _sched_stub

from backend.api.main import app
from backend.config import settings
from backend.models.database import init_db


@pytest.fixture(scope="module", autouse=True)
def _init_db_once():
    """Create tables once for the whole module (avoids no-such-table errors)."""
    init_db()


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def admin_client():
    """Client with admin key set."""
    original = settings.ADMIN_API_KEY
    settings.ADMIN_API_KEY = "test-secret-key"
    client = TestClient(app, headers={"Authorization": "Bearer test-secret-key"})
    yield client
    settings.ADMIN_API_KEY = original


class TestAdminAuth:
    """Test admin API key enforcement."""

    def test_settings_get_rejected_when_no_key_configured(self, client):
        """If ADMIN_API_KEY is not set, endpoint is rejected (403)."""
        original = settings.ADMIN_API_KEY
        settings.ADMIN_API_KEY = None
        try:
            resp = client.get("/api/v1/admin/settings")
            assert resp.status_code == 403
        finally:
            settings.ADMIN_API_KEY = original

    def test_settings_get_requires_auth_when_key_set(self, client):
        """If ADMIN_API_KEY is set, requests without token get 401."""
        original = settings.ADMIN_API_KEY
        settings.ADMIN_API_KEY = "secret"
        try:
            resp = client.get("/api/v1/admin/settings")
            assert resp.status_code == 401
        finally:
            settings.ADMIN_API_KEY = original

    def test_settings_get_accepts_valid_token(self, admin_client):
        """Valid bearer token returns 200."""
        resp = admin_client.get("/api/v1/admin/settings")
        assert resp.status_code == 200

    def test_settings_post_requires_auth(self, client):
        """POST /api/admin/settings needs auth when key is set."""
        original = settings.ADMIN_API_KEY
        settings.ADMIN_API_KEY = "secret"
        try:
            resp = client.post("/api/v1/admin/settings", json={"updates": {}})
            assert resp.status_code == 401
        finally:
            settings.ADMIN_API_KEY = original

    def test_bot_start_requires_auth(self, client):
        """POST /api/bot/start needs auth when key is set."""
        original = settings.ADMIN_API_KEY
        settings.ADMIN_API_KEY = "secret"
        try:
            resp = client.post("/api/v1/bot/start")
            assert resp.status_code == 401
        finally:
            settings.ADMIN_API_KEY = original


class TestAdminSettings:
    """Test GET/POST /api/admin/settings."""

    def test_get_returns_grouped_settings(self, admin_client):
        resp = admin_client.get("/api/v1/admin/settings")
        assert resp.status_code == 200
        data = resp.json()
        assert "trading" in data
        assert "weather" in data
        assert "api_keys" in data
        assert "telegram" in data

    def test_get_masks_secrets(self, admin_client):
        """Secret fields should be masked as ****."""
        original_key = settings.POLYMARKET_API_KEY
        settings.POLYMARKET_API_KEY = "real-api-key"
        try:
            resp = admin_client.get("/api/v1/admin/settings")
            data = resp.json()
            # POLYMARKET_API_KEY should be masked
            api_keys = data.get("api_keys", {})
            assert api_keys.get("POLYMARKET_API_KEY") == "****"
        finally:
            settings.POLYMARKET_API_KEY = original_key

    def test_get_empty_secret_not_masked(self, admin_client):
        """Empty/None secrets should not be masked as ****."""
        original = settings.POLYMARKET_API_KEY
        settings.POLYMARKET_API_KEY = None
        try:
            resp = admin_client.get("/api/v1/admin/settings")
            data = resp.json()
            api_keys = data.get("api_keys", {})
            assert api_keys.get("POLYMARKET_API_KEY") != "****"
        finally:
            settings.POLYMARKET_API_KEY = original

    def test_post_updates_non_secret_setting(self, admin_client):
        """POST updates a non-secret setting."""
        original = settings.KELLY_FRACTION
        try:
            resp = admin_client.post(
                "/api/v1/admin/settings", json={"updates": {"KELLY_FRACTION": "0.20"}}
            )
            assert resp.status_code == 200
            assert settings.KELLY_FRACTION == 0.20
        finally:
            settings.KELLY_FRACTION = original

    def test_post_ignores_placeholder_values(self, admin_client):
        """Sending **** for a secret should not overwrite it."""
        original = settings.POLYMARKET_API_KEY
        settings.POLYMARKET_API_KEY = "my-real-key"
        try:
            admin_client.post(
                "/api/v1/admin/settings",
                json={"updates": {"POLYMARKET_API_KEY": "****"}},
            )
            assert settings.POLYMARKET_API_KEY == "my-real-key"
        finally:
            settings.POLYMARKET_API_KEY = original

    def test_post_strips_newlines_from_values(self, admin_client):
        """Newline injection should not produce a standalone injected key."""
        import os
        import re

        env_path = ".env"
        # Save original value
        original_cities = None
        if os.path.exists(env_path):
            with open(env_path) as f:
                for line in f:
                    if line.startswith("WEATHER_CITIES="):
                        original_cities = line.strip()
                        break

        # Attempt newline injection: embed INJECTED_KEY=evil after a \n
        admin_client.post(
            "/api/v1/admin/settings",
            json={"updates": {"WEATHER_CITIES": "nyc\nINJECTED_KEY=evil"}},
        )
        if os.path.exists(env_path):
            with open(env_path) as f:
                content = f.read()
            # The server strips \n/\r so no line break can separate the injected key.
            # Assert INJECTED_KEY is never the start of a line (i.e., not a standalone key).
            assert not re.search(r"^INJECTED_KEY=", content, re.MULTILINE)

        # Restore original value
        if original_cities and os.path.exists(env_path):
            with open(env_path) as f:
                lines = f.readlines()
            with open(env_path, "w") as f:
                for line in lines:
                    if line.startswith("WEATHER_CITIES="):
                        f.write(original_cities + "\n")
                    else:
                        f.write(line)


class TestSystemStatus:
    """Test GET /api/admin/system."""

    def test_returns_system_info(self, admin_client):
        resp = admin_client.get("/api/v1/admin/system")
        assert resp.status_code == 200
        data = resp.json()
        assert "trading_mode" in data
        assert "bot_running" in data
        assert data["trading_mode"] == settings.TRADING_MODE
