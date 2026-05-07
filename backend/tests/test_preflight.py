"""Tests for backend.core.preflight — geoblock and connectivity checks."""
from unittest.mock import AsyncMock, MagicMock, patch

import httpx

from backend.core.preflight import check_geoblock


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mock_response(status_code: int = 200, json_data: dict | None = None) -> MagicMock:
    """Build a mock httpx.Response."""
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    resp.json.return_value = json_data or {}
    resp.raise_for_status = MagicMock()  # no-op for 200
    elapsed = MagicMock()
    elapsed.total_seconds.return_value = 0.05
    resp.elapsed = elapsed
    return resp


# ---------------------------------------------------------------------------
# check_geoblock
# ---------------------------------------------------------------------------

async def test_geoblock_not_blocked():
    """When Polymarket returns blocked=false the result status is OK."""
    mock_resp = _mock_response(json_data={"blocked": False, "country": "US"})

    with patch("backend.core.preflight.httpx.AsyncClient") as MockClient:
        instance = MockClient.return_value.__aenter__.return_value
        instance.get = AsyncMock(return_value=mock_resp)

        result = await check_geoblock()

    assert result["blocked"] is False
    assert result["country"] == "US"
    assert result["status"] == "OK"


async def test_geoblock_blocked():
    """When Polymarket returns blocked=true the result status is BLOCKED."""
    mock_resp = _mock_response(json_data={"blocked": True, "country": "IR"})

    with patch("backend.core.preflight.httpx.AsyncClient") as MockClient:
        instance = MockClient.return_value.__aenter__.return_value
        instance.get = AsyncMock(return_value=mock_resp)

        result = await check_geoblock()

    assert result["blocked"] is True
    assert result["country"] == "IR"
    assert result["status"] == "BLOCKED"


async def test_geoblock_connection_error():
    """Network timeout yields status CHECK_FAILED and blocked=None."""
    with patch("backend.core.preflight.httpx.AsyncClient") as MockClient:
        instance = MockClient.return_value.__aenter__.return_value
        instance.get = AsyncMock(side_effect=httpx.ConnectTimeout("timed out"))

        result = await check_geoblock()

    assert result["blocked"] is None
    assert result["status"] == "CHECK_FAILED"
    assert result["country"] == "unknown"
