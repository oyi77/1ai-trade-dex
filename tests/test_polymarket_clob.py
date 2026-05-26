"""
Extended tests for PolymarketCLOB client — order placement, balance, positions, error handling.

All HTTP calls are mocked. Tests cover success paths, API errors, timeouts,
rate limits, auth failures, and network errors.
"""

import httpx
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from backend.data.polymarket_clob import (
    PolymarketCLOB,
    ensure_token_id,
    _inflight_keys,
)

# ============================================================================
# Helpers
# ============================================================================


def _mock_http_response(json_data, status_code=200):
    """Create a mock httpx.Response."""
    resp = MagicMock()
    resp.json.return_value = json_data
    resp.status_code = status_code
    resp.raise_for_status = MagicMock()
    if status_code >= 400:
        resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            message=f"HTTP {status_code}",
            request=MagicMock(),
            response=resp,
        )
    return resp


def _make_live_clob():
    """Create a CLOB client in live mode with mock credentials."""
    pk = "0x" + "a" * 64
    clob = PolymarketCLOB(
        private_key=pk,
        api_key="test_key",
        api_secret="dGVzdF9zZWNyZXQ=",  # base64
        api_passphrase="test_pass",
        mode="live",
    )
    # Mock the ClobClient so no real signing happens
    mock_client = MagicMock()
    mock_client.creds = MagicMock(
        api_key="test_key",
        api_secret="dGVzdF9zZWNyZXQ=",
        api_passphrase="test_pass",
    )
    clob._clob_client = mock_client
    return clob


# ============================================================================
# ensure_token_id
# ============================================================================


class TestEnsureTokenId:
    def test_hex_to_decimal(self):
        assert ensure_token_id("0xff") == "255"

    def test_decimal_passthrough(self):
        assert ensure_token_id("1234567890") == "1234567890"

    def test_empty_string(self):
        assert ensure_token_id("") == ""

    def test_invalid_hex_passthrough(self):
        assert ensure_token_id("0xZZZZ") == "0xZZZZ"


# ============================================================================
# Order placement — success path (live mode)
# ============================================================================


class TestPlaceLimitOrderLive:
    """Test live-mode order placement with mocked py-clob-client."""

    @pytest.mark.asyncio
    async def test_live_order_success(self):
        clob = _make_live_clob()
        clob._clob_client.create_order.return_value = MagicMock()
        clob._clob_client.post_order.return_value = {"orderID": "ord_123"}

        clob._http = AsyncMock()
        try:
            result = await clob.place_limit_order(
                "token1", "BUY", price=0.60, size=50.0
            )
            assert result.success
            assert result.order_id == "ord_123"
        finally:
            clob._http = None

    @pytest.mark.asyncio
    async def test_live_order_api_error(self):
        clob = _make_live_clob()
        clob._clob_client.create_order.side_effect = Exception(
            "API rejected: insufficient balance"
        )

        clob._http = AsyncMock()
        try:
            result = await clob.place_limit_order(
                "token1", "BUY", price=0.60, size=50.0
            )
            assert not result.success
            assert "insufficient balance" in result.error
        finally:
            clob._http = None

    @pytest.mark.asyncio
    async def test_live_order_below_minimum_rejected(self):
        clob = _make_live_clob()

        clob._http = AsyncMock()
        try:
            result = await clob.place_limit_order("token1", "BUY", price=0.50, size=0.5)
            assert not result.success
            assert "minimum" in result.error.lower()
        finally:
            clob._http = None

    @pytest.mark.asyncio
    async def test_live_order_no_creds_rejected(self):
        pk = "0x" + "b" * 64
        clob = PolymarketCLOB(private_key=pk, mode="live")
        clob._clob_client = MagicMock()
        clob._clob_client.creds = None

        clob._http = AsyncMock()
        try:
            result = await clob.place_limit_order(
                "token1", "BUY", price=0.60, size=50.0
            )
            assert not result.success
            assert "credentials" in result.error.lower()
        finally:
            clob._http = None

    @pytest.mark.asyncio
    async def test_circuit_breaker_open_rejects_order(self):
        clob = _make_live_clob()
        clob._clob_client.create_order.return_value = MagicMock()
        clob._clob_client.post_order.return_value = {"orderID": "ord_456"}

        clob._http = AsyncMock()
        from backend.data.polymarket_clob import clob_breaker

        original_state = clob_breaker.state
        clob_breaker._state = "OPEN"
        try:
            result = await clob.place_limit_order(
                "token1", "BUY", price=0.60, size=50.0
            )
            assert not result.success
            assert "circuit" in result.error.lower() or "OPEN" in result.error
        finally:
            clob_breaker._state = original_state
            clob._http = None


# ============================================================================
# Order placement — idempotency
# ============================================================================


class TestIdempotency:
    @pytest.mark.asyncio
    async def test_inflight_key_prevents_duplicate(self):
        """Manually adding a key to _inflight_keys should block the order."""
        clob = PolymarketCLOB(simulation=True)
        import hashlib
        import time

        # Compute the same idempotency key the code would use
        bucket = int(time.time()) // 300
        raw = f"tok1:BUY:20.0000:{bucket}"
        key = hashlib.sha256(raw.encode()).hexdigest()[:32]

        # Pre-claim the key
        _inflight_keys.add(key)
        try:
            async with clob:
                clob.get_mid_price = AsyncMock(return_value=0.55)
                result = await clob.place_limit_order(
                    "tok1", "BUY", price=0.55, size=20.0
                )
            assert not result.success
            assert "duplicate" in result.error.lower()
        finally:
            _inflight_keys.discard(key)


# ============================================================================
# Balance retrieval
# ============================================================================


class TestGetWalletBalance:
    @pytest.mark.asyncio
    async def test_paper_mode_returns_zero(self):
        clob = PolymarketCLOB(simulation=True)
        async with clob:
            result = await clob.get_wallet_balance()
        assert result["usdc_balance"] == 0.0
        assert result["error"] is not None

    @pytest.mark.asyncio
    async def test_live_rpc_success(self):
        """RPC balance fetch succeeds with mocked httpx."""
        clob = _make_live_clob()

        # 3 tokens each returning 100 USDC via RPC
        rpc_response = MagicMock()
        rpc_response.status_code = 200
        rpc_response.json.return_value = {"result": "0x05f5e100"}  # 100 USDC

        mock_http_client = AsyncMock()
        mock_http_client.post = AsyncMock(return_value=rpc_response)
        mock_http_client.__aenter__ = AsyncMock(return_value=mock_http_client)
        mock_http_client.__aexit__ = AsyncMock(return_value=False)

        clob._http = AsyncMock()
        try:
            with patch(
                "backend.data.polymarket_clob.httpx.AsyncClient",
                return_value=mock_http_client,
            ):
                with patch("backend.data.polymarket_clob.settings") as mock_settings:
                    mock_settings.USDC_E_ADDRESS = "0xUSDC_E"
                    mock_settings.USDC_NATIVE_ADDRESS = "0xUSDC_N"
                    mock_settings.PUSD_ADDRESS = "0xPUSD"
                    mock_settings.POLYGON_RPC_URL = "https://rpc.example.com"

                    result = await clob.get_wallet_balance()

            assert result["error"] is None
            # 3 tokens * 100 USDC each = 300
            assert result["usdc_balance"] == 300.0
        finally:
            clob._http = None

    @pytest.mark.asyncio
    async def test_live_rpc_timeout_returns_zero(self):
        """RPC timeout returns zero balance (individual token failures are caught)."""
        clob = _make_live_clob()

        mock_http_client = AsyncMock()
        mock_http_client.post = AsyncMock(side_effect=httpx.TimeoutException("timeout"))
        mock_http_client.__aenter__ = AsyncMock(return_value=mock_http_client)
        mock_http_client.__aexit__ = AsyncMock(return_value=False)

        clob._http = AsyncMock()
        try:
            with patch(
                "backend.data.polymarket_clob.httpx.AsyncClient",
                return_value=mock_http_client,
            ):
                with patch("backend.data.polymarket_clob.settings") as mock_settings:
                    mock_settings.USDC_E_ADDRESS = "0xUSDC_E"
                    mock_settings.USDC_NATIVE_ADDRESS = "0xUSDC_N"
                    mock_settings.PUSD_ADDRESS = "0xPUSD"
                    mock_settings.POLYGON_RPC_URL = "https://rpc.example.com"

                    result = await clob.get_wallet_balance()

            # Individual token failures are caught per-token, total_balance stays 0
            assert result["usdc_balance"] == 0.0
            assert result["error"] is None
        finally:
            clob._http = None


# ============================================================================
# Position tracking
# ============================================================================


class TestPositionTracking:
    @pytest.mark.asyncio
    async def test_get_trader_positions_success(self):
        clob = PolymarketCLOB(simulation=True)
        positions = [
            {"slug": "btc-5m", "size": "50.0", "outcome": "Yes"},
            {"slug": "eth-5m", "size": "30.0", "outcome": "No"},
        ]
        async with clob:
            clob._http.get = AsyncMock(return_value=_mock_http_response(positions))
            result = await clob.get_trader_positions("0xwallet")

        assert len(result) == 2
        assert result[0]["slug"] == "btc-5m"

    @pytest.mark.asyncio
    async def test_get_trader_trades_success(self):
        clob = PolymarketCLOB(simulation=True)
        trades = [{"id": "t1", "side": "BUY", "price": "0.65"}]
        async with clob:
            clob._http.get = AsyncMock(return_value=_mock_http_response(trades))
            result = await clob.get_trader_trades("0xwallet", limit=50)

        assert len(result) == 1
        assert result[0]["id"] == "t1"

    @pytest.mark.asyncio
    async def test_get_wallet_trades_pagination(self):
        """Wallet trades should paginate correctly."""
        clob = PolymarketCLOB(simulation=True)
        page1 = [
            {"id": f"t{i}", "price": "0.5", "shares": "10", "timestamp": 1000}
            for i in range(100)
        ]
        page2 = [
            {"id": f"t{i+100}", "price": "0.5", "shares": "10", "timestamp": 1000}
            for i in range(5)
        ]

        call_count = 0

        async def mock_get(url, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return _mock_http_response(page1)
            return _mock_http_response(page2)

        async with clob:
            clob._http.get = mock_get
            trades = await clob.get_wallet_trades(
                wallet_address="0xabc", limit=100, max_pages=5
            )

        assert len(trades) == 105

    @pytest.mark.asyncio
    async def test_get_wallet_trades_no_address_raises(self):
        """Should raise ValueError when no wallet address is available."""
        clob = PolymarketCLOB(simulation=True)
        clob.builder_address = None
        clob._account = None

        async with clob:
            with pytest.raises(ValueError, match="No wallet address"):
                await clob.get_wallet_trades()


# ============================================================================
# Error handling — rate limit, auth, network
# ============================================================================


class TestErrorHandling:
    @pytest.mark.asyncio
    async def test_rate_limit_error_propagates(self):
        clob = PolymarketCLOB(simulation=True)
        rate_resp = MagicMock(status_code=429)
        rate_err = httpx.HTTPStatusError(
            message="Rate limited",
            request=MagicMock(),
            response=rate_resp,
        )

        async with clob:
            clob._http.get = AsyncMock(side_effect=rate_err)
            with pytest.raises(httpx.HTTPStatusError):
                await clob.get_trader_trades("0xwallet")

    @pytest.mark.asyncio
    async def test_auth_failure_on_positions(self):
        clob = PolymarketCLOB(simulation=True)
        auth_err = httpx.HTTPStatusError(
            message="Unauthorized",
            request=MagicMock(),
            response=MagicMock(status_code=401),
        )

        async with clob:
            clob._http.get = AsyncMock(side_effect=auth_err)
            with pytest.raises(httpx.HTTPStatusError):
                await clob.get_trader_positions("0xwallet")

    @pytest.mark.asyncio
    async def test_network_error_on_order_book(self):
        clob = PolymarketCLOB(simulation=True)

        async with clob:
            clob._http.get = AsyncMock(
                side_effect=httpx.ConnectError("connection refused")
            )
            with pytest.raises(httpx.ConnectError):
                await clob.get_order_book("token1")

    @pytest.mark.asyncio
    async def test_get_order_returns_none_on_404(self):
        clob = PolymarketCLOB(simulation=True)
        resp_404 = MagicMock()
        resp_404.status_code = 404
        resp_404.raise_for_status.side_effect = httpx.HTTPStatusError(
            message="Not Found",
            request=MagicMock(),
            response=resp_404,
        )

        async with clob:
            clob._http.get = AsyncMock(
                side_effect=resp_404.raise_for_status.side_effect
            )
            result = await clob.get_order("nonexistent_order")

        assert result is None

    @pytest.mark.asyncio
    async def test_get_leaderboard_returns_empty_on_error(self):
        clob = PolymarketCLOB(simulation=True)

        async with clob:
            clob._http.get = AsyncMock(side_effect=Exception("network down"))
            result = await clob.get_leaderboard()

        assert result == []

    @pytest.mark.asyncio
    async def test_cancel_order_live_returns_false_on_error(self):
        clob = _make_live_clob()
        clob._clob_client.cancel_order.side_effect = Exception("cancel failed")

        async with clob:
            result = await clob.cancel_order("ord_123")

        assert result is False

    @pytest.mark.asyncio
    async def test_get_open_orders_live_returns_empty_on_error(self):
        clob = _make_live_clob()
        clob._clob_client.get_open_orders.side_effect = Exception("timeout")

        async with clob:
            result = await clob.get_open_orders()

        assert result == []


# ============================================================================
# Context manager lifecycle
# ============================================================================


class TestLifecycle:
    @pytest.mark.asyncio
    async def test_aenter_creates_http_client(self):
        clob = PolymarketCLOB(simulation=True)
        async with clob:
            assert clob._http is not None
        assert clob._http is None

    @pytest.mark.asyncio
    async def test_simulation_property(self):
        clob_live = PolymarketCLOB(mode="live")
        clob_paper = PolymarketCLOB(mode="paper")
        assert not clob_live.simulation
        assert clob_paper.simulation
        assert clob_paper.is_paper
        assert not clob_live.is_paper
