"""Test connection limits: verify 11 WebSocket connections from same IP → 11th rejected."""

import asyncio
from unittest.mock import Mock
from backend.api.connection_limits import ConnectionLimiter
from fastapi import WebSocket


async def test_websocket_per_ip_limit():
    """Test WebSocket per-IP limit (10 connections)."""
    limiter = ConnectionLimiter()

    # Create mock WebSocket connections from same IP
    mock_websockets = []
    for i in range(12):
        ws = Mock(spec=WebSocket)
        ws.client = Mock()
        ws.client.host = "192.168.1.100"
        mock_websockets.append(ws)

    results = []
    for i, ws in enumerate(mock_websockets):
        allowed, error_msg = await limiter.check_ws_limit(ws)
        results.append((i + 1, allowed, error_msg))
        print(f"Connection {i + 1}: {'✓ Allowed' if allowed else '✗ Rejected'} - {error_msg or 'OK'}")

    # Verify first 10 allowed, 11th and 12th rejected
    assert results[0][1], "Connection 1 should be allowed"
    assert results[9][1], "Connection 10 should be allowed"
    assert not results[10][1], "Connection 11 should be rejected (per-IP limit)"
    assert not results[11][1], "Connection 12 should be rejected (per-IP limit)"

    print("\n✓ Per-IP limit test passed: 10 allowed, 11th+ rejected")

    # Release connections
    for ws in mock_websockets[:10]:
        await limiter.release_ws_connection(ws)


async def test_global_websocket_limit():
    """Test global WebSocket limit (1000 connections)."""
    limiter = ConnectionLimiter()

    # Create 1001 mock WebSocket connections from different IPs
    mock_websockets = []
    for i in range(1001):
        ws = Mock(spec=WebSocket)
        ws.client = Mock()
        ws.client.host = f"192.168.{i // 256}.{i % 256}"
        mock_websockets.append(ws)

    allowed_count = 0
    rejected_count = 0

    for i, ws in enumerate(mock_websockets):
        allowed, error_msg = await limiter.check_ws_limit(ws)
        if allowed:
            allowed_count += 1
        else:
            rejected_count += 1

        if i == 999 or i == 1000:
            print(f"Connection {i + 1}: {'✓ Allowed' if allowed else '✗ Rejected'} - {error_msg or 'OK'}")

    assert allowed_count == 1000, f"Expected 1000 allowed, got {allowed_count}"
    assert rejected_count == 1, f"Expected 1 rejected, got {rejected_count}"

    print(f"\n✓ Global limit test passed: {allowed_count} allowed, {rejected_count} rejected")


async def test_http_per_ip_limit():
    """Test HTTP per-IP limit (50 requests per minute)."""
    limiter = ConnectionLimiter()

    client_ip = "192.168.1.50"
    endpoint = "/api/trades"

    results = []
    for i in range(52):
        allowed, error_msg = limiter.check_http_limit(client_ip, endpoint)
        results.append((i + 1, allowed, error_msg))
        if i >= 48:
            print(f"Request {i + 1}: {'✓ Allowed' if allowed else '✗ Rejected'} - {error_msg or 'OK'}")

    # Verify first 50 allowed, 51st+ rejected
    assert results[0][1], "Request 1 should be allowed"
    assert results[49][1], "Request 50 should be allowed"
    assert not results[50][1], "Request 51 should be rejected (HTTP per-IP limit)"
    assert not results[51][1], "Request 52 should be rejected (HTTP per-IP limit)"

    print("\n✓ HTTP per-IP limit test passed: 50 allowed, 51st+ rejected")


async def test_connection_metrics():
    """Test connection metrics reporting."""
    limiter = ConnectionLimiter()

    # Add some connections
    ws1 = Mock(spec=WebSocket)
    ws1.client = Mock()
    ws1.client.host = "192.168.1.1"

    ws2 = Mock(spec=WebSocket)
    ws2.client = Mock()
    ws2.client.host = "192.168.1.2"

    await limiter.check_ws_limit(ws1)
    await limiter.check_ws_limit(ws1)
    await limiter.check_ws_limit(ws2)

    metrics = await limiter.get_metrics()

    assert metrics["websocket"]["per_ip"]["192.168.1.1"] == 2
    assert metrics["websocket"]["per_ip"]["192.168.1.2"] == 1
    assert metrics["websocket"]["global"] == 3
    assert metrics["websocket"]["per_ip_limit"] == 10
    assert metrics["websocket"]["global_limit"] == 1000

    print("✓ Connection metrics test passed")
    print(f"  - Per-IP connections: {metrics['websocket']['per_ip']}")
    print(f"  - Global connections: {metrics['websocket']['global']}")


async def main():
    """Run all tests."""
    print("=" * 60)
    print("CONNECTION LIMITS TEST SUITE")
    print("=" * 60)
    print()

    try:
        await test_websocket_per_ip_limit()
        print()
        await test_global_websocket_limit()
        print()
        await test_http_per_ip_limit()
        print()
        await test_connection_metrics()
        print()
        print("=" * 60)
        print("✓ ALL TESTS PASSED")
        print("=" * 60)
    except AssertionError as e:
        print(f"\n✗ TEST FAILED: {e}")
        return 1
    except Exception as e:
        print(f"\n✗ ERROR: {e}")
        import traceback
        traceback.print_exc()
        return 1

    return 0


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    exit(exit_code)
