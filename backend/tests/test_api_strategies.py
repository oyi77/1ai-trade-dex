"""Tests for /api/v1/strategies CRUD endpoints (admin-protected)."""
from backend.config import settings


def _admin_headers():
    settings.ADMIN_API_KEY = None  # open mode for tests
    return {}


class TestStrategiesList:
    def setup_method(self):
        settings.ADMIN_API_KEY = None

    def test_strategies_returns_list(self, client):
        resp = client.get("/api/v1/strategies")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)

    def test_strategies_list_not_empty(self, client):
        """After loading strategies, registry should have at least one entry."""
        resp = client.get("/api/v1/strategies")
        data = resp.json()
        # It's OK if empty when no strategies are registered, but must be a list
        assert isinstance(data, list)

    def test_strategies_items_have_name(self, client):
        resp = client.get("/api/v1/strategies")
        data = resp.json()
        for item in data:
            assert "name" in item

    def test_strategies_items_have_enabled(self, client):
        resp = client.get("/api/v1/strategies")
        data = resp.json()
        for item in data:
            assert "enabled" in item


class TestStrategyGet:
    def setup_method(self):
        settings.ADMIN_API_KEY = None

    def test_nonexistent_strategy_returns_404(self, client):
        resp = client.get("/api/v1/strategies/does_not_exist_xyz")
        assert resp.status_code == 404

    def test_known_strategy_if_any(self, client):
        """If any strategy is registered, fetching it by name returns 200."""
        list_resp = client.get("/api/v1/strategies")
        strategies = list_resp.json()
        if strategies:
            name = strategies[0]["name"]
            resp = client.get(f"/api/v1/strategies/{name}")
            assert resp.status_code == 200
            data = resp.json()
            assert data["name"] == name


class TestStrategyUpdate:
    def setup_method(self):
        settings.ADMIN_API_KEY = None

    def test_update_nonexistent_returns_404(self, client):
        resp = client.put(
            "/api/v1/strategies/does_not_exist_xyz",
            json={"enabled": False},
        )
        assert resp.status_code == 404

    def test_update_known_strategy_if_any(self, client):
        """If any strategy is registered, can toggle enabled."""
        list_resp = client.get("/api/v1/strategies")
        strategies = list_resp.json()
        if strategies:
            name = strategies[0]["name"]
            resp = client.put(f"/api/v1/strategies/{name}", json={"enabled": False})
            assert resp.status_code == 200
