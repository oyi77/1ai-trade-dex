"""
Crash Audit — Deterministic mock-based test suite.
Mocks ALL external HTTP calls via respx, then fires malicious
payloads at every mutable endpoint. Runs in <10s, no hanging.
"""
import os, re

os.environ.setdefault("TRADING_MODE", "paper")
os.environ.setdefault("REDIS_ENABLED", "False")
os.environ.setdefault("POLYMARKET_WS_ENABLED", "False")
os.environ.setdefault("POLYMARKET_USER_WS_ENABLED", "False")
os.environ.setdefault("LOG_LEVEL", "ERROR")

import pytest
from fastapi.testclient import TestClient
from backend.api.main import app


# ─── Fixture: mock all external HTTP ─────────────────────────────────

@pytest.fixture(autouse=True)
def mock_external_http():
    """Mock ALL external HTTP requests so no endpoint ever hangs."""
    import respx
    from httpx import Response

    router = respx.mock(
        assert_all_called=False,
        assert_all_mocked=False,  # Don't fail on unmocked — just let it 500 fast
    )

    # Catch-all: any external HTTP request returns 503 instantly
    router.route(
        host="__any__", method="__any__",
    ).mock(Response(503, json={"error": "mocked — external service unavailable"}))

    with router:
        yield


# ─── Route enumeration ───────────────────────────────────────────────

@pytest.fixture(scope="session")
def all_routes():
    routes = set()
    for r in app.routes:
        if hasattr(r, "path"):
            for m in (getattr(r, "methods", None) or {"GET"}):
                routes.add((m, r.path))
        elif hasattr(r, "original_router"):
            ctx = getattr(r, "include_context", None)
            prefix = getattr(ctx, "prefix", "") if ctx else ""
            for sub in getattr(r.original_router, "routes", []):
                for m in (getattr(sub, "methods", None) or {"GET"}):
                    fp = prefix + getattr(sub, "path", "")
                    routes.add((m, fp.rstrip("/") if fp != "/" else "/"))
    return sorted(routes, key=lambda x: x[1])


@pytest.fixture(scope="session")
def client():
    return TestClient(app)


PAYLOADS = [
    pytest.param(("", "empty"), id="empty"),
    pytest.param(("not json", "raw text"), id="raw-text"),
    pytest.param(("{}", "empty obj"), id="empty-obj"),
]


# ─── Tests ───────────────────────────────────────────────────────────

class TestCrashAudit:
    """Every mutable endpoint must survive malicious payloads."""

    @pytest.mark.parametrize("body_label", PAYLOADS)
    def test_post_put_patch_survives_bad_input(self, client, all_routes, body_label):
        body, label = body_label
        mutable = [(m, p) for m, p in all_routes if m in ("POST", "PUT", "PATCH")]
        failures = []

        for method, path in mutable:
            try:
                resp = client.request(
                    method, path,
                    data=body,
                    headers={"Content-Type": "application/json"},
                    timeout=5,
                )
                if resp.status_code == 500:
                    failures.append(f"500 {method} {path} ({label})")
                if resp.status_code not in (
                    200, 201, 204, 400, 401, 403, 404, 409, 422, 504, 503,
                ):
                    failures.append(f"UNEXPECTED {resp.status_code} {method} {path} ({label})")
            except Exception as e:
                failures.append(f"EXCEPTION {method} {path}: {e}")

        assert not failures, "\n".join(failures[:20])

    def test_delete_survives(self, client, all_routes):
        deletable = [(m, p) for m, p in all_routes if m == "DELETE"]
        failures = []

        for method, path in deletable:
            inj_path = re.sub(r"\{[^}]+\}", "99999", path)
            try:
                resp = client.request("DELETE", inj_path, timeout=5)
                if resp.status_code == 500:
                    failures.append(f"500 DELETE {path}")
            except Exception as e:
                failures.append(f"EXCEPTION DELETE {path}: {e}")

        assert not failures, "\n".join(failures[:20])

    @pytest.mark.parametrize("injection", [
        pytest.param(("../../../etc/passwd", "path-traversal"), id="path-traversal"),
        pytest.param(("1;DROP TABLE", "sql-injection"), id="sql-injection"),
        pytest.param(("9999999999999999999999", "overflow"), id="overflow"),
    ])
    def test_path_injection_survives(self, client, all_routes, injection):
        inj_value, label = injection
        path_params = [(m, p) for m, p in all_routes if "{" in p]
        failures = []

        for method, path in path_params:
            inj_path = re.sub(r"\{[^}]+\}", inj_value, path)
            try:
                resp = client.request("GET", inj_path, timeout=5)
                if resp.status_code == 500:
                    failures.append(f"500 {method} {path} ({label})")
            except Exception as e:
                failures.append(f"EXCEPTION {method} {path}: {e}")

        assert not failures, "\n".join(failures[:20])


# ─── Report ──────────────────────────────────────────────────────────

def test_crash_audit_summary(client, all_routes):
    """Summarise crash audit results."""
    mutable = [(m, p) for m, p in all_routes if m in ("POST", "PUT", "PATCH")]
    deletable = [(m, p) for m, p in all_routes if m == "DELETE"]
    path_params = [(m, p) for m, p in all_routes if "{" in p]

    print(f"\n{'='*60}")
    print(f"CRASH AUDIT SUMMARY")
    print(f"{'='*60}")
    print(f"Total routes:     {len(all_routes)}")
    print(f"POST/PUT/PATCH:   {len(mutable)}")
    print(f"DELETE:           {len(deletable)}")
    print(f"With path params: {len(path_params)}")
    print(f"Timeout:          {os.environ.get('API_REQUEST_TIMEOUT', '15s')}")
    print(f"External mocks:   respx (catch-all 503)")
    print(f"{'='*60}")
    print(f"Tests: ~{len(mutable) * 3 + len(deletable) + len(path_params) * 3} assertions")
    print(f"VERDICT: Computed by test results above")
