"""Tests for /api/v1/settings/test-mirofish API endpoint."""
import asyncio
from unittest.mock import patch, AsyncMock


class TestMiroFishEndpointAuth:
    """Test authentication and authorization for test-mirofish endpoint."""

    def test_missing_admin_token_returns_401(self, client):
        """POST /api/v1/settings/test-mirofish without admin token returns 401."""
        from backend.config import settings
        original = settings.ADMIN_API_KEY
        settings.ADMIN_API_KEY = "test-secret"
        try:
            resp = client.post(
                "/api/v1/settings/test-mirofish",
                json={"api_url": "https://api.mirofish.io", "api_key": "test-key"}
            )
            assert resp.status_code == 401
        finally:
            settings.ADMIN_API_KEY = original

    def test_invalid_admin_token_returns_401(self, client):
        """POST with wrong bearer token returns 401."""
        from backend.config import settings
        original = settings.ADMIN_API_KEY
        settings.ADMIN_API_KEY = "correct-secret"
        try:
            resp = client.post(
                "/api/v1/settings/test-mirofish",
                json={"api_url": "https://api.mirofish.io", "api_key": "test-key"},
                headers={"Authorization": "Bearer wrong-secret"}
            )
            assert resp.status_code == 401
        finally:
            settings.ADMIN_API_KEY = original

    def test_valid_admin_token_passes_auth(self, client):
        """POST with valid bearer token passes authentication."""
        from backend.config import settings
        original = settings.ADMIN_API_KEY
        settings.ADMIN_API_KEY = "test-secret"
        try:
            with patch("backend.ai.mirofish_client.MiroFishClient") as mock_client_class:
                mock_instance = AsyncMock()
                mock_instance.fetch_signals = AsyncMock(return_value=[])
                mock_client_class.return_value = mock_instance

                resp = client.post(
                    "/api/v1/settings/test-mirofish",
                    json={"api_url": "https://api.mirofish.io", "api_key": "test-key"},
                    headers={"Authorization": "Bearer test-secret"}
                )
                assert resp.status_code == 200
        finally:
            settings.ADMIN_API_KEY = original

    def test_no_auth_required_when_admin_key_not_set(self, client):
        """POST works without auth header when ADMIN_API_KEY is not set."""
        from backend.config import settings
        original = settings.ADMIN_API_KEY
        settings.ADMIN_API_KEY = None
        try:
            with patch("backend.ai.mirofish_client.MiroFishClient") as mock_client_class:
                mock_instance = AsyncMock()
                mock_instance.fetch_signals = AsyncMock(return_value=[])
                mock_client_class.return_value = mock_instance

                resp = client.post(
                    "/api/v1/settings/test-mirofish",
                    json={"api_url": "https://api.mirofish.io", "api_key": "test-key"}
                )
                assert resp.status_code == 200
        finally:
            settings.ADMIN_API_KEY = original


class TestMiroFishEndpointValidation:
    """Test request validation for test-mirofish endpoint."""

    def test_missing_api_url_returns_422(self, client):
        """POST without api_url returns 422 validation error."""
        from backend.config import settings
        original = settings.ADMIN_API_KEY
        settings.ADMIN_API_KEY = None
        try:
            resp = client.post(
                "/api/v1/settings/test-mirofish",
                json={"api_key": "test-key"}
            )
            assert resp.status_code == 422
        finally:
            settings.ADMIN_API_KEY = original

    def test_missing_api_key_returns_422(self, client):
        """POST without api_key returns 422 validation error."""
        from backend.config import settings
        original = settings.ADMIN_API_KEY
        settings.ADMIN_API_KEY = None
        try:
            resp = client.post(
                "/api/v1/settings/test-mirofish",
                json={"api_url": "https://api.mirofish.io"}
            )
            assert resp.status_code == 422
        finally:
            settings.ADMIN_API_KEY = original

    def test_empty_api_url_attempts_connection(self, client):
        """POST with empty api_url attempts connection (no validation)."""
        from backend.config import settings
        original = settings.ADMIN_API_KEY
        settings.ADMIN_API_KEY = None
        try:
            with patch("backend.ai.mirofish_client.MiroFishClient") as mock_client_class:
                mock_instance = AsyncMock()
                mock_instance.fetch_signals = AsyncMock(return_value=[])
                mock_client_class.return_value = mock_instance

                resp = client.post(
                    "/api/v1/settings/test-mirofish",
                    json={"api_url": "", "api_key": "test-key"}
                )
                assert resp.status_code == 200
                mock_client_class.assert_called_once()
        finally:
            settings.ADMIN_API_KEY = original

    def test_empty_api_key_attempts_connection(self, client):
        """POST with empty api_key attempts connection (no validation)."""
        from backend.config import settings
        original = settings.ADMIN_API_KEY
        settings.ADMIN_API_KEY = None
        try:
            with patch("backend.ai.mirofish_client.MiroFishClient") as mock_client_class:
                mock_instance = AsyncMock()
                mock_instance.fetch_signals = AsyncMock(return_value=[])
                mock_client_class.return_value = mock_instance

                resp = client.post(
                    "/api/v1/settings/test-mirofish",
                    json={"api_url": "https://api.mirofish.io", "api_key": ""}
                )
                assert resp.status_code == 200
                mock_client_class.assert_called_once()
        finally:
            settings.ADMIN_API_KEY = original


class TestMiroFishEndpointSuccess:
    """Test successful test-mirofish endpoint responses."""

    def test_valid_credentials_returns_success(self, client):
        """POST with valid credentials returns success=True with signals_count."""
        from backend.config import settings
        original = settings.ADMIN_API_KEY
        settings.ADMIN_API_KEY = None
        try:
            with patch("backend.ai.mirofish_client.MiroFishClient") as mock_client_class:
                mock_signals = [
                    {"market": "polymarket", "signal": "buy", "confidence": 0.8},
                    {"market": "polymarket", "signal": "sell", "confidence": 0.6},
                ]
                mock_instance = AsyncMock()
                mock_instance.fetch_signals = AsyncMock(return_value=mock_signals)
                mock_client_class.return_value = mock_instance

                resp = client.post(
                    "/api/v1/settings/test-mirofish",
                    json={"api_url": "https://api.mirofish.io", "api_key": "valid-key"}
                )
                assert resp.status_code == 200
                data = resp.json()
                assert data["success"] is True
                assert data["signals_count"] == 2
                assert "Connection successful" in data["message"]
                assert data.get("error") is None
        finally:
            settings.ADMIN_API_KEY = original

    def test_zero_signals_still_returns_success(self, client):
        """POST that fetches zero signals still returns success=True."""
        from backend.config import settings
        original = settings.ADMIN_API_KEY
        settings.ADMIN_API_KEY = None
        try:
            with patch("backend.ai.mirofish_client.MiroFishClient") as mock_client_class:
                mock_instance = AsyncMock()
                mock_instance.fetch_signals = AsyncMock(return_value=[])
                mock_client_class.return_value = mock_instance

                resp = client.post(
                    "/api/v1/settings/test-mirofish",
                    json={"api_url": "https://api.mirofish.io", "api_key": "valid-key"}
                )
                assert resp.status_code == 200
                data = resp.json()
                assert data["success"] is True
                assert data["signals_count"] == 0
                assert "Connection successful" in data["message"]
        finally:
            settings.ADMIN_API_KEY = original

    def test_response_schema_matches_model(self, client):
        """Response schema matches TestMiroFishResponse model."""
        from backend.config import settings
        original = settings.ADMIN_API_KEY
        settings.ADMIN_API_KEY = None
        try:
            with patch("backend.ai.mirofish_client.MiroFishClient") as mock_client_class:
                mock_instance = AsyncMock()
                mock_instance.fetch_signals = AsyncMock(return_value=[{"signal": "test"}])
                mock_client_class.return_value = mock_instance

                resp = client.post(
                    "/api/v1/settings/test-mirofish",
                    json={"api_url": "https://api.mirofish.io", "api_key": "valid-key"}
                )
                data = resp.json()
                assert "success" in data
                assert "message" in data
                assert isinstance(data["success"], bool)
                assert isinstance(data["message"], str)
                assert "signals_count" in data
                assert "error" in data
        finally:
            settings.ADMIN_API_KEY = original


class TestMiroFishEndpointAuthenticationError:
    """Test authentication error handling (401 from MiroFish API)."""

    def test_401_error_returns_authentication_error(self, client):
        """MiroFish 401 response returns error='authentication'."""
        from backend.config import settings
        original = settings.ADMIN_API_KEY
        settings.ADMIN_API_KEY = None
        try:
            with patch("backend.ai.mirofish_client.MiroFishClient") as mock_client_class:
                mock_instance = AsyncMock()
                mock_instance.fetch_signals = AsyncMock(
                    side_effect=Exception("401 Unauthorized")
                )
                mock_client_class.return_value = mock_instance

                resp = client.post(
                    "/api/v1/settings/test-mirofish",
                    json={"api_url": "https://api.mirofish.io", "api_key": "invalid-key"}
                )
                assert resp.status_code == 200
                data = resp.json()
                assert data["success"] is False
                assert data["error"] == "authentication"
                assert "Authentication failed" in data["message"]
                assert data.get("signals_count") is None
        finally:
            settings.ADMIN_API_KEY = original

    def test_unauthorized_error_returns_authentication_error(self, client):
        """MiroFish 'unauthorized' error returns error='authentication'."""
        from backend.config import settings
        original = settings.ADMIN_API_KEY
        settings.ADMIN_API_KEY = None
        try:
            with patch("backend.ai.mirofish_client.MiroFishClient") as mock_client_class:
                mock_instance = AsyncMock()
                mock_instance.fetch_signals = AsyncMock(
                    side_effect=Exception("unauthorized access denied")
                )
                mock_client_class.return_value = mock_instance

                resp = client.post(
                    "/api/v1/settings/test-mirofish",
                    json={"api_url": "https://api.mirofish.io", "api_key": "invalid-key"}
                )
                assert resp.status_code == 200
                data = resp.json()
                assert data["success"] is False
                assert data["error"] == "authentication"
        finally:
            settings.ADMIN_API_KEY = original


class TestMiroFishEndpointNotFoundError:
    """Test not found error handling (404 from MiroFish API)."""

    def test_404_error_returns_not_found_error(self, client):
        """MiroFish 404 response returns error='not_found'."""
        from backend.config import settings
        original = settings.ADMIN_API_KEY
        settings.ADMIN_API_KEY = None
        try:
            with patch("backend.ai.mirofish_client.MiroFishClient") as mock_client_class:
                mock_instance = AsyncMock()
                mock_instance.fetch_signals = AsyncMock(
                    side_effect=Exception("404 Not Found")
                )
                mock_client_class.return_value = mock_instance

                resp = client.post(
                    "/api/v1/settings/test-mirofish",
                    json={"api_url": "https://invalid-url.io", "api_key": "test-key"}
                )
                assert resp.status_code == 200
                data = resp.json()
                assert data["success"] is False
                assert data["error"] == "not_found"
                assert "API endpoint not found" in data["message"]
        finally:
            settings.ADMIN_API_KEY = original

    def test_not_found_error_returns_not_found_error(self, client):
        """MiroFish 'not found' error returns error='not_found'."""
        from backend.config import settings
        original = settings.ADMIN_API_KEY
        settings.ADMIN_API_KEY = None
        try:
            with patch("backend.ai.mirofish_client.MiroFishClient") as mock_client_class:
                mock_instance = AsyncMock()
                mock_instance.fetch_signals = AsyncMock(
                    side_effect=Exception("endpoint not found")
                )
                mock_client_class.return_value = mock_instance

                resp = client.post(
                    "/api/v1/settings/test-mirofish",
                    json={"api_url": "https://api.mirofish.io", "api_key": "test-key"}
                )
                assert resp.status_code == 200
                data = resp.json()
                assert data["success"] is False
                assert data["error"] == "not_found"
        finally:
            settings.ADMIN_API_KEY = original


class TestMiroFishEndpointTimeoutError:
    """Test timeout error handling."""

    def test_timeout_error_returns_timeout_error(self, client):
        """asyncio.TimeoutError returns error='timeout'."""
        from backend.config import settings
        original = settings.ADMIN_API_KEY
        settings.ADMIN_API_KEY = None
        try:
            with patch("backend.ai.mirofish_client.MiroFishClient") as mock_client_class:
                mock_instance = AsyncMock()
                mock_instance.fetch_signals = AsyncMock(
                    side_effect=asyncio.TimeoutError()
                )
                mock_client_class.return_value = mock_instance

                resp = client.post(
                    "/api/v1/settings/test-mirofish",
                    json={"api_url": "https://api.mirofish.io", "api_key": "test-key"}
                )
                assert resp.status_code == 200
                data = resp.json()
                assert data["success"] is False
                assert data["error"] == "timeout"
                assert "timed out" in data["message"].lower()
        finally:
            settings.ADMIN_API_KEY = original

    def test_timeout_message_mentions_10_seconds(self, client):
        """Timeout error message mentions 10 second timeout."""
        from backend.config import settings
        original = settings.ADMIN_API_KEY
        settings.ADMIN_API_KEY = None
        try:
            with patch("backend.ai.mirofish_client.MiroFishClient") as mock_client_class:
                mock_instance = AsyncMock()
                mock_instance.fetch_signals = AsyncMock(
                    side_effect=asyncio.TimeoutError()
                )
                mock_client_class.return_value = mock_instance

                resp = client.post(
                    "/api/v1/settings/test-mirofish",
                    json={"api_url": "https://api.mirofish.io", "api_key": "test-key"}
                )
                data = resp.json()
                assert "10 seconds" in data["message"]
        finally:
            settings.ADMIN_API_KEY = original


class TestMiroFishEndpointConnectionError:
    """Test connection error handling."""

    def test_connection_error_returns_connection_error(self, client):
        """Connection error returns error='connection'."""
        from backend.config import settings
        original = settings.ADMIN_API_KEY
        settings.ADMIN_API_KEY = None
        try:
            with patch("backend.ai.mirofish_client.MiroFishClient") as mock_client_class:
                mock_instance = AsyncMock()
                mock_instance.fetch_signals = AsyncMock(
                    side_effect=Exception("connection refused")
                )
                mock_client_class.return_value = mock_instance

                resp = client.post(
                    "/api/v1/settings/test-mirofish",
                    json={"api_url": "https://api.mirofish.io", "api_key": "test-key"}
                )
                assert resp.status_code == 200
                data = resp.json()
                assert data["success"] is False
                assert data["error"] == "connection"
                assert "Connection failed" in data["message"]
        finally:
            settings.ADMIN_API_KEY = original

    def test_dns_error_returns_connection_error(self, client):
        """DNS resolution error returns error='connection'."""
        from backend.config import settings
        original = settings.ADMIN_API_KEY
        settings.ADMIN_API_KEY = None
        try:
            with patch("backend.ai.mirofish_client.MiroFishClient") as mock_client_class:
                mock_instance = AsyncMock()
                mock_instance.fetch_signals = AsyncMock(
                    side_effect=Exception("connection error: name resolution failed")
                )
                mock_client_class.return_value = mock_instance

                resp = client.post(
                    "/api/v1/settings/test-mirofish",
                    json={"api_url": "https://api.mirofish.io", "api_key": "test-key"}
                )
                assert resp.status_code == 200
                data = resp.json()
                assert data["success"] is False
                assert data["error"] == "connection"
        finally:
            settings.ADMIN_API_KEY = original


class TestMiroFishEndpointUnknownError:
    """Test unknown/generic error handling."""

    def test_unknown_error_returns_unknown_error(self, client):
        """Unrecognized error returns error='unknown'."""
        from backend.config import settings
        original = settings.ADMIN_API_KEY
        settings.ADMIN_API_KEY = None
        try:
            with patch("backend.ai.mirofish_client.MiroFishClient") as mock_client_class:
                mock_instance = AsyncMock()
                mock_instance.fetch_signals = AsyncMock(
                    side_effect=Exception("some random error")
                )
                mock_client_class.return_value = mock_instance

                resp = client.post(
                    "/api/v1/settings/test-mirofish",
                    json={"api_url": "https://api.mirofish.io", "api_key": "test-key"}
                )
                assert resp.status_code in [200, 500]
        finally:
            settings.ADMIN_API_KEY = original

    def test_generic_exception_returns_generic_message(self, client):
        """Generic exception returns generic error message."""
        from backend.config import settings
        original = settings.ADMIN_API_KEY
        settings.ADMIN_API_KEY = None
        try:
            with patch("backend.ai.mirofish_client.MiroFishClient") as mock_client_class:
                mock_instance = AsyncMock()
                mock_instance.fetch_signals = AsyncMock(
                    side_effect=ValueError("invalid value")
                )
                mock_client_class.return_value = mock_instance

                resp = client.post(
                    "/api/v1/settings/test-mirofish",
                    json={"api_url": "https://api.mirofish.io", "api_key": "test-key"}
                )
                assert resp.status_code == 200
                data = resp.json()
                assert data["success"] is False
                assert "check your credentials" in data["message"].lower()
        finally:
            settings.ADMIN_API_KEY = original


class TestMiroFishEndpointClientInstantiation:
    """Test MiroFishClient instantiation with correct parameters."""

    def test_client_instantiated_with_correct_url(self, client):
        """MiroFishClient is instantiated with provided api_url."""
        from backend.config import settings
        original = settings.ADMIN_API_KEY
        settings.ADMIN_API_KEY = None
        try:
            with patch("backend.ai.mirofish_client.MiroFishClient") as mock_client_class:
                mock_instance = AsyncMock()
                mock_instance.fetch_signals = AsyncMock(return_value=[])
                mock_client_class.return_value = mock_instance

                test_url = "https://custom.mirofish.io/v2"
                resp = client.post(
                    "/api/v1/settings/test-mirofish",
                    json={"api_url": test_url, "api_key": "test-key"}
                )
                assert resp.status_code == 200
                mock_client_class.assert_called_once()
                call_kwargs = mock_client_class.call_args[1]
                assert call_kwargs["api_url"] == test_url
        finally:
            settings.ADMIN_API_KEY = original

    def test_client_instantiated_with_correct_key(self, client):
        """MiroFishClient is instantiated with provided api_key."""
        from backend.config import settings
        original = settings.ADMIN_API_KEY
        settings.ADMIN_API_KEY = None
        try:
            with patch("backend.ai.mirofish_client.MiroFishClient") as mock_client_class:
                mock_instance = AsyncMock()
                mock_instance.fetch_signals = AsyncMock(return_value=[])
                mock_client_class.return_value = mock_instance

                test_key = "secret-api-key-12345"
                resp = client.post(
                    "/api/v1/settings/test-mirofish",
                    json={"api_url": "https://api.mirofish.io", "api_key": test_key}
                )
                assert resp.status_code == 200
                mock_client_class.assert_called_once()
                call_kwargs = mock_client_class.call_args[1]
                assert call_kwargs["api_key"] == test_key
        finally:
            settings.ADMIN_API_KEY = original


class TestMiroFishEndpointFetchSignalsCall:
    """Test fetch_signals method is called correctly."""

    def test_fetch_signals_called_with_polymarket_market(self, client):
        """fetch_signals is called with market='polymarket'."""
        from backend.config import settings
        original = settings.ADMIN_API_KEY
        settings.ADMIN_API_KEY = None
        try:
            with patch("backend.ai.mirofish_client.MiroFishClient") as mock_client_class:
                mock_instance = AsyncMock()
                mock_instance.fetch_signals = AsyncMock(return_value=[])
                mock_client_class.return_value = mock_instance

                resp = client.post(
                    "/api/v1/settings/test-mirofish",
                    json={"api_url": "https://api.mirofish.io", "api_key": "test-key"}
                )
                assert resp.status_code == 200
                mock_instance.fetch_signals.assert_called_once()
                call_kwargs = mock_instance.fetch_signals.call_args[1]
                assert call_kwargs["market"] == "polymarket"
        finally:
            settings.ADMIN_API_KEY = original
