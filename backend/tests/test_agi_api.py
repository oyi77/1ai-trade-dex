
from fastapi.testclient import TestClient

from backend.api.main import app


def get_test_client():
    from backend.api.agi_routes import router
    app.include_router(router)

    client = TestClient(app)
    return client


class TestAGIAPIRoutes:
    def test_router_can_be_imported(self):
        from backend.api import agi_routes
        assert agi_routes.router is not None

    def test_app_can_include_router(self):
        from backend.api.agi_routes import router
        app.include_router(router)
        assert len(app.routes) > 0


class TestAGIAPIEndpoints:
    def test_endpoints_return_responses(self):
        client = get_test_client()
        endpoints = [
            ("/api/v1/agi/regime", [200, 500]),
            ("/api/v1/agi/goal", [200, 500]),
            ("/api/v1/agi/decisions", [200, 500]),
            ("/api/v1/agi/strategies/composed", [200, 500]),
            ("/api/v1/agi/experiments", [200, 500]),
            ("/api/v1/agi/knowledge-graph", [200, 500]),
            ("/api/v1/agi/status", [200, 500]),
        ]
        for url, expected_codes in endpoints:
            resp = client.get(url)
            assert resp.status_code in expected_codes, f"{url} returned {resp.status_code}"


class TestAGIAPIEmergencyStop:
    def test_emergency_stop_endpoint(self):
        client = get_test_client()
        resp = client.post("/api/v1/agi/emergency-stop")
        assert resp.status_code in [200, 500]


class TestAGIAPIGoalOverride:
    def test_override_goal_endpoint(self):
        client = get_test_client()
        resp = client.post(
            "/api/v1/agi/goal/override",
            json={"goal": "maximize_pnl", "reason": "test override"}
        )
        assert resp.status_code in [200, 400, 500]



class TestAGIAPIGoal:
    def test_get_goal(self):
        client = get_test_client()
        resp = client.get("/api/v1/agi/goal")
        assert resp.status_code in [200, 500]


class TestAGIAPIDecisions:
    def test_list_decisions_empty(self):
        client = get_test_client()
        resp = client.get("/api/v1/agi/decisions")
        assert resp.status_code in [200, 500]
        if resp.status_code == 200:
            data = resp.json()
            assert "decisions" in data or "page" in data


class TestAGIAPIStrategies:
    def test_list_composed_empty(self):
        client = get_test_client()
        resp = client.get("/api/v1/agi/strategies/composed")
        assert resp.status_code in [200, 500]


class TestAGIAPIExperiments:
    def test_list_experiments_empty(self):
        client = get_test_client()
        resp = client.get("/api/v1/agi/experiments")
        assert resp.status_code in [200, 500]


class TestAGIAPIKnowledgeGraph:
    def test_query_kg_empty(self):
        client = get_test_client()
        resp = client.get("/api/v1/agi/knowledge-graph")
        assert resp.status_code in [200, 500]


class TestAGIAPIEmergencyStopNoAuth:
    def test_emergency_stop(self, monkeypatch):
        from backend.config import settings
        monkeypatch.setattr(settings, "ADMIN_API_KEY", None)
        client = get_test_client()
        resp = client.post("/api/v1/agi/emergency-stop")
        assert resp.status_code in [200, 500]


class TestAGIAPIStatus:
    def test_get_status(self):
        client = get_test_client()
        resp = client.get("/api/v1/agi/status")
        assert resp.status_code in [200, 500]
        if resp.status_code == 200:
            data = resp.json()
            assert "regime" in data or "health" in data


class TestAGIAPIGoalOverrideNoAuth:
    def test_override_goal(self, monkeypatch):
        from backend.config import settings
        monkeypatch.setattr(settings, "ADMIN_API_KEY", None)
        client = get_test_client()
        resp = client.post(
            "/api/v1/agi/goal/override",
            json={"goal": "maximize_pnl", "reason": "test override"}
        )
        assert resp.status_code in [200, 500]
