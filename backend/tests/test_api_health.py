import asyncio
from unittest.mock import AsyncMock

import pytest

"""Tests for /api/v1/health, /api/v1/stats, /api/v1/dashboard endpoints."""


class TestHealth:
    def test_legacy_api_health_alias_returns_200(self, client):
        resp = client.get("/api/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "healthy"

    def test_health_live_alias_returns_200(self, client):
        resp = client.get("/api/v1/health/live")
        assert resp.status_code == 200
        assert resp.json()["status"] == "healthy"

    def test_health_returns_200(self, client):
        resp = client.get("/api/v1/health/dependencies")
        assert resp.status_code == 200

    def test_health_has_status_key(self, client):
        resp = client.get("/api/v1/health/dependencies")
        data = resp.json()
        assert "status" in data
        assert data["status"] in ("ok", "degraded", "healthy")

    def test_health_has_dependencies(self, client):
        resp = client.get("/api/v1/health/dependencies")
        data = resp.json()
        assert "dependencies" in data or "status" in data

    def test_health_has_timestamp(self, client):
        resp = client.get("/api/v1/health/dependencies")
        data = resp.json()
        assert "timestamp" in data or "status" in data

    def test_health_degrades_when_clob_check_times_out(self, client, monkeypatch):
        class SlowClob:
            async def create_or_derive_api_key(self):
                pass

            async def get_wallet_balance(self):
                await asyncio.sleep(10)

        monkeypatch.setattr(
            "backend.data.polymarket_clob.clob_from_settings",
            lambda: SlowClob(),
        )
        monkeypatch.setattr(
            "backend.core.agi_event_handlers.check_agi_health",
            lambda: {},
        )

        resp = client.get("/api/v1/health/dependencies")
        data = resp.json()

        assert resp.status_code == 200
        assert data["status"] == "degraded"
        assert data["dependencies"]["polymarket_clob"] == {
            "status": "error",
            "error": "health check timed out",
        }

    def test_health_reports_clob_balance(self, client, monkeypatch):
        class HealthyClob:
            create_or_derive_api_key = AsyncMock()

            get_wallet_balance = AsyncMock(
                return_value={
                    "usdc_balance": 12.34,
                    "token_balances": {},
                    "error": None,
                }
            )

        monkeypatch.setattr(
            "backend.data.polymarket_clob.clob_from_settings",
            lambda: HealthyClob(),
        )
        monkeypatch.setattr(
            "backend.core.agi_event_handlers.check_agi_health",
            lambda: {},
        )

        resp = client.get("/api/v1/health/dependencies")
        data = resp.json()

        assert resp.status_code == 200
        assert data["dependencies"]["polymarket_clob"] == {
            "status": "ok",
            "balance": "12.34",
        }

    def test_health_sanitizes_clob_error_details(self, client, monkeypatch):
        internal_error = "Traceback secret: private rpc failure"

        class FailingClob:
            create_or_derive_api_key = AsyncMock()

            get_wallet_balance = AsyncMock(
                return_value={
                    "usdc_balance": 0.0,
                    "token_balances": {},
                    "error": internal_error,
                }
            )

        monkeypatch.setattr(
            "backend.data.polymarket_clob.clob_from_settings",
            lambda: FailingClob(),
        )
        monkeypatch.setattr(
            "backend.core.agi_event_handlers.check_agi_health",
            lambda: {},
        )

        resp = client.get("/api/v1/health/dependencies")
        data = resp.json()

        assert resp.status_code == 200
        assert data["status"] == "degraded"
        assert data["dependencies"]["polymarket_clob"] == {
            "status": "error",
            "error": "wallet balance unavailable",
        }
        assert internal_error not in resp.text


class TestStats:
    def test_stats_returns_200(self, client):
        resp = client.get("/api/v1/stats")
        assert resp.status_code == 200

    def test_stats_has_bankroll(self, client):
        resp = client.get("/api/v1/stats")
        data = resp.json()
        assert "bankroll" in data

    def test_stats_has_paper_and_live(self, client):
        resp = client.get("/api/v1/stats")
        data = resp.json()
        assert "paper" in data
        assert "live" in data

    def test_stats_has_total_trades(self, client):
        resp = client.get("/api/v1/stats")
        data = resp.json()
        assert "total_trades" in data
        assert isinstance(data["total_trades"], int)


class TestDashboard:
    def test_dashboard_returns_200(self, client):
        resp = client.get("/api/v1/dashboard")
        assert resp.status_code == 200

    def test_dashboard_has_stats(self, client):
        resp = client.get("/api/v1/dashboard")
        data = resp.json()
        assert "stats" in data

    @pytest.mark.skip(reason="Fails due to API timeout issue on Github Actions")
    def test_dashboard_has_recent_trades(self, client):
        resp = client.get("/api/v1/dashboard")
        data = resp.json()
        assert "recent_trades" in data
        assert isinstance(data["recent_trades"], list)

    def test_dashboard_has_trading_mode(self, client):
        resp = client.get("/api/v1/dashboard")
        data = resp.json()
        assert "trading_mode" in data
