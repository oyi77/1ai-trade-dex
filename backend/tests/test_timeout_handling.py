"""Tests for request timeout handling."""

import asyncio
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api.timeout_middleware import TimeoutMiddleware
from backend.config import settings


@pytest.fixture
def app_with_timeout():
    app = FastAPI()
    app.add_middleware(TimeoutMiddleware)

    @app.get("/fast")
    async def fast_endpoint():
        return {"status": "ok"}

    @app.get("/slow")
    async def slow_endpoint():
        await asyncio.sleep(35)
        return {"status": "ok"}

    return app


def test_fast_request_succeeds(app_with_timeout):
    client = TestClient(app_with_timeout)
    response = client.get("/fast")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_slow_request_times_out(app_with_timeout, monkeypatch):
    monkeypatch.setattr(settings, "API_REQUEST_TIMEOUT", 1.0)

    client = TestClient(app_with_timeout)
    response = client.get("/slow")

    assert response.status_code == 504
    assert "timeout" in response.json()["error"].lower()
    assert response.json()["timeout_seconds"] == 1.0


@pytest.mark.asyncio
async def test_database_timeout():
    from backend.models.database import execute_with_timeout
    import time

    def slow_query():
        time.sleep(15)
        return "result"

    with pytest.raises(asyncio.TimeoutError):
        await execute_with_timeout(slow_query, timeout=1.0)


@pytest.mark.asyncio
async def test_external_api_timeout():
    from backend.core.timeout_helpers import execute_external_api_with_timeout

    async def slow_api_call():
        await asyncio.sleep(20)
        return {"data": "value"}

    with pytest.raises(asyncio.TimeoutError):
        await execute_external_api_with_timeout(
            slow_api_call,
            timeout=1.0,
            operation_name="test_api"
        )


@pytest.mark.asyncio
async def test_external_api_success():
    from backend.core.timeout_helpers import execute_external_api_with_timeout

    async def fast_api_call():
        await asyncio.sleep(0.1)
        return {"data": "value"}

    result = await execute_external_api_with_timeout(
        fast_api_call,
        timeout=5.0,
        operation_name="test_api"
    )

    assert result == {"data": "value"}
