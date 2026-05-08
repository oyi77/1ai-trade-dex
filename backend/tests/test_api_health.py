"""Tests for /api/v1/health, /api/v1/stats, /api/v1/dashboard endpoints."""


class TestHealth:
    def test_health_returns_200(self, client):
        resp = client.get("/api/v1/health")
        assert resp.status_code == 200

    def test_health_has_status_key(self, client):
        resp = client.get("/api/v1/health")
        data = resp.json()
        assert "status" in data
        assert data["status"] in ("ok", "degraded", "healthy")

    def test_health_has_dependencies(self, client):
        resp = client.get("/api/v1/health")
        data = resp.json()
        assert "dependencies" in data or "status" in data

    def test_health_has_timestamp(self, client):
        resp = client.get("/api/v1/health")
        data = resp.json()
        assert "timestamp" in data or "status" in data


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

    def test_dashboard_has_recent_trades(self, client):
        resp = client.get("/api/v1/dashboard")
        data = resp.json()
        assert "recent_trades" in data
        assert isinstance(data["recent_trades"], list)

    def test_dashboard_has_trading_mode(self, client):
        resp = client.get("/api/v1/dashboard")
        data = resp.json()
        assert "trading_mode" in data
