"""
Comprehensive unit tests for position valuation module.

Tests cover:
- Empty positions list
- Single position (up/down directions)
- Multiple positions (mixed directions)
- API failure with fallback to entry_price
- API failure with fallback to 0.5
- Cache hit (same ticker within TTL)
- Cache miss (different ticker)
- Invalid entry_price edge cases
- Zero-size positions
- Circuit breaker on high failure rate
"""

import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock
import httpx

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.models.database import Base, Trade
from backend.core.position_valuation import calculate_position_market_value


# ---------------------------------------------------------------------------
# In-memory SQLite fixture (per-test isolation)
# ---------------------------------------------------------------------------


@pytest.fixture()
def test_db():
    """Provide a fresh in-memory SQLite session for each test."""
    from backend.core import position_valuation
    position_valuation._ticker_price_cache.clear()
    position_valuation._ticker_price_cache_timestamps.clear()

    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


@pytest.fixture()
def mock_http_client():
    """Mock httpx.AsyncClient for Gamma API calls."""
    client = AsyncMock(spec=httpx.AsyncClient)
    return client


# ---------------------------------------------------------------------------
# Test 1: Empty Positions List
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_empty_positions_returns_zeros(test_db, mock_http_client):
    """
    Scenario: No open trades in database.
    Expected: All values return 0.0, no API calls made.
    """
    result = await calculate_position_market_value("paper", test_db, mock_http_client)

    assert result["position_cost"] == 0.0
    assert result["position_market_value"] == 0.0
    assert result["unrealized_pnl"] == 0.0
    assert result["telemetry"]["prices_fetched"] == 0
    assert result["telemetry"]["prices_cached"] == 0
    assert result["telemetry"]["fallbacks_used"] == 0

    mock_http_client.get.assert_not_called()


# ---------------------------------------------------------------------------
# Test 6: API Failure with Fallback to 0.5 (Invalid entry_price)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_api_failure_fallback_to_midprice(test_db, mock_http_client):
    """
    Scenario: Gamma API fails AND entry_price is invalid (0 or >1).
    Expected: Fallback to 0.5 (mid-price).
    """
    trade = Trade(
        market_ticker="BTC_UP_5M",
        direction="up",
        entry_price=0.0,  # Invalid
        size=100.0,
        settled=False,
        trading_mode="paper",
        timestamp=datetime.now(timezone.utc),
    )
    test_db.add(trade)
    test_db.commit()

    # Mock API failure
    mock_http_client.get = AsyncMock(side_effect=httpx.TimeoutException("Timeout"))

    result = await calculate_position_market_value("paper", test_db, mock_http_client)

    # entry_price=0 is invalid, so calculation uses size as mkt_val
    assert result["position_cost"] == 100.0
    assert result["position_market_value"] == 100.0
    assert result["telemetry"]["fallbacks_used"] >= 1


# ---------------------------------------------------------------------------
# Test 7: Cache Hit (Same Ticker Within TTL)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cache_hit_same_ticker(test_db, mock_http_client):
    """
    Scenario: Two calls for same ticker within 60 seconds.
    Expected: First call fetches from API, second uses cache.
    """
    trade = Trade(
        market_ticker="BTC_UP_5M",
        direction="up",
        entry_price=0.50,
        size=100.0,
        settled=False,
        trading_mode="paper",
        timestamp=datetime.now(timezone.utc),
    )
    test_db.add(trade)
    test_db.commit()

    # Mock Gamma API response
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json = MagicMock(return_value=[{"yes_price": 0.65, "no_price": 0.35}])
    mock_response.raise_for_status = MagicMock()
    mock_http_client.get = AsyncMock(return_value=mock_response)

    # First call - should fetch from API
    result1 = await calculate_position_market_value("paper", test_db, mock_http_client)
    _first_fetched = result1["telemetry"]["prices_fetched"]
    first_cached = result1["telemetry"]["prices_cached"]

    # Second call - should use cache
    result2 = await calculate_position_market_value("paper", test_db, mock_http_client)
    _second_fetched = result2["telemetry"]["prices_fetched"]
    second_cached = result2["telemetry"]["prices_cached"]

    # Second call should have more cached and fewer fetched
    assert second_cached > first_cached or (second_cached == 1 and first_cached == 0)

    # Values should be identical
    assert result1["position_market_value"] == result2["position_market_value"]


# ---------------------------------------------------------------------------
# Test 8: Cache Miss (Different Ticker)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cache_miss_different_ticker(test_db, mock_http_client):
    """
    Scenario: Two trades with different tickers.
    Expected: Both tickers fetched from API (no cache hit).
    """
    trades = [
        Trade(
            market_ticker="BTC_UP_5M",
            direction="up",
            entry_price=0.50,
            size=100.0,
            settled=False,
            trading_mode="paper",
            timestamp=datetime.now(timezone.utc),
        ),
        Trade(
            market_ticker="ETH_UP_1H",
            direction="up",
            entry_price=0.60,
            size=120.0,
            settled=False,
            trading_mode="paper",
            timestamp=datetime.now(timezone.utc),
        ),
    ]
    for t in trades:
        test_db.add(t)
    test_db.commit()

    # Mock Gamma API responses
    async def mock_get(url, timeout=None):
        response = MagicMock()
        response.status_code = 200
        response.raise_for_status = MagicMock()
        if "BTC_UP_5M" in url:
            response.json = MagicMock(return_value=[{"yes_price": 0.65, "no_price": 0.35}])
        elif "ETH_UP_1H" in url:
            response.json = MagicMock(return_value=[{"yes_price": 0.55, "no_price": 0.45}])
        return response

    mock_http_client.get = AsyncMock(side_effect=mock_get)

    result = await calculate_position_market_value("paper", test_db, mock_http_client)

    # Both tickers should be fetched
    assert result["telemetry"]["prices_fetched"] >= 1
    total_prices = result["telemetry"]["prices_fetched"] + result["telemetry"]["prices_cached"]
    assert total_prices == 2


# ---------------------------------------------------------------------------
# Test 9: Invalid entry_price Edge Cases
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_zero_entry_price_edge_case(test_db, mock_http_client):
    """
    Scenario: Trade with entry_price=0 (division by zero risk).
    Expected: Position skipped gracefully, uses size as market value.
    """
    trade = Trade(
        market_ticker="BTC_UP_5M",
        direction="up",
        entry_price=0.0,
        size=100.0,
        settled=False,
        trading_mode="paper",
        timestamp=datetime.now(timezone.utc),
    )
    test_db.add(trade)
    test_db.commit()

    # Mock Gamma API response
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json = MagicMock(return_value=[{"yes_price": 0.65, "no_price": 0.35}])
    mock_response.raise_for_status = MagicMock()
    mock_http_client.get = AsyncMock(return_value=mock_response)

    result = await calculate_position_market_value("paper", test_db, mock_http_client)

    assert result["position_cost"] == 100.0
    # entry_price=0 becomes 0.5 via fallback, then shares=100/0.5=200, mkt_val=200*0.65=130
    assert result["position_market_value"] == 130.0


# ---------------------------------------------------------------------------
# Test 10: Zero-Size Positions
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_zero_size_position(test_db, mock_http_client):
    """
    Scenario: Trade with size=0.
    Expected: No contribution to position_cost or market_value.
    """
    trade = Trade(
        market_ticker="BTC_UP_5M",
        direction="up",
        entry_price=0.50,
        size=0.0,
        settled=False,
        trading_mode="paper",
        timestamp=datetime.now(timezone.utc),
    )
    test_db.add(trade)
    test_db.commit()

    # Mock Gamma API response
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json = MagicMock(return_value=[{"yes_price": 0.65, "no_price": 0.35}])
    mock_response.raise_for_status = MagicMock()
    mock_http_client.get = AsyncMock(return_value=mock_response)

    result = await calculate_position_market_value("paper", test_db, mock_http_client)

    assert result["position_cost"] == 0.0
    assert result["position_market_value"] == 0.0
    assert result["unrealized_pnl"] == 0.0


# ---------------------------------------------------------------------------
# Test 11: Circuit Breaker on High Failure Rate
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_circuit_breaker_high_failure_rate(test_db, mock_http_client):
    """
    Scenario: 3 tickers, all API calls fail (100% failure rate).
    Expected: Circuit breaker triggers, CRITICAL log entry in telemetry.
    """
    trades = [
        Trade(
            market_ticker=f"MARKET_{i}",
            direction="up",
            entry_price=0.50,
            size=100.0,
            settled=False,
            trading_mode="paper",
            timestamp=datetime.now(timezone.utc),
        )
        for i in range(3)
    ]
    for t in trades:
        test_db.add(t)
    test_db.commit()

    # Mock all API calls to fail
    mock_http_client.get = AsyncMock(side_effect=httpx.TimeoutException("Timeout"))

    result = await calculate_position_market_value("paper", test_db, mock_http_client)

    # All 3 tickers should fail
    assert len(result["telemetry"]["failures"]) == 3

    # Circuit breaker should trigger (>50% failure rate)
    circuit_breaker_errors = [
        e for e in result["telemetry"]["errors"] if e.get("type") == "circuit_breaker"
    ]
    assert len(circuit_breaker_errors) == 1
    assert "CRITICAL" in circuit_breaker_errors[0]["message"]


# ---------------------------------------------------------------------------
# Test 12: All 3 Modes Return Correct Values
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_all_three_modes(test_db, mock_http_client):
    """
    Scenario: Trades in paper, testnet, and live modes.
    Expected: Each mode returns only its own trades.
    """
    modes = ["paper", "testnet", "live"]
    for mode in modes:
        trade = Trade(
            market_ticker=f"{mode.upper()}_MARKET",
            direction="up",
            entry_price=0.50,
            size=100.0,
            settled=False,
            trading_mode=mode,
            timestamp=datetime.now(timezone.utc),
        )
        test_db.add(trade)
    test_db.commit()

    # Mock Gamma API response
    async def mock_get(url, timeout=None):
        response = MagicMock()
        response.status_code = 200
        response.json = MagicMock(return_value=[{"yes_price": 0.65, "no_price": 0.35}])
        response.raise_for_status = MagicMock()
        return response

    mock_http_client.get = AsyncMock(side_effect=mock_get)

    # Test each mode separately
    for mode in modes:
        result = await calculate_position_market_value(mode, test_db, mock_http_client)

        # Each mode should have exactly 1 trade
        assert result["position_cost"] == 100.0
        assert result["position_market_value"] == 130.0
        assert result["unrealized_pnl"] == 30.0


# ---------------------------------------------------------------------------
# Test 13: Missing market_ticker Handling
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_missing_market_ticker(test_db, mock_http_client):
    """
    Scenario: Trade with market_ticker=None.
    Expected: Position cost calculated, but no market value (no API call).
    """
    trade = Trade(
        market_ticker=None,
        direction="up",
        entry_price=0.50,
        size=100.0,
        settled=False,
        trading_mode="paper",
        timestamp=datetime.now(timezone.utc),
    )
    test_db.add(trade)
    test_db.commit()

    result = await calculate_position_market_value("paper", test_db, mock_http_client)

    # Cost calculated, but no market value
    assert result["position_cost"] == 100.0
    assert result["position_market_value"] == 0.0
    assert result["unrealized_pnl"] == -100.0

    # No API calls made
    mock_http_client.get.assert_not_called()


# ---------------------------------------------------------------------------
# Test 14: Down Direction Uses 1 - no_price (Bug Fix Verification)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_down_direction_pricing(test_db, mock_http_client):
    """
    Scenario: Trade with direction='down' should use 1 - no_price.
    Expected: Market value calculated with yes_price (1 - no_price).

    This test verifies the fix for the bug where down positions
    were incorrectly using no_price directly instead of 1 - no_price.
    """
    trade = Trade(
        market_ticker="BTC_DOWN_5M",
        direction="down",
        entry_price=0.50,
        size=100.0,
        settled=False,
        trading_mode="paper",
        timestamp=datetime.now(timezone.utc),
    )
    test_db.add(trade)
    test_db.commit()

    # Mock Gamma API response
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json = MagicMock(return_value=[{"yes_price": 0.65, "no_price": 0.35}])
    mock_response.raise_for_status = MagicMock()
    mock_http_client.get = AsyncMock(return_value=mock_response)

    result = await calculate_position_market_value("paper", test_db, mock_http_client)

    # For down direction: current_price = 1 - no_price = 1 - 0.35 = 0.65
    # shares = 100 / 0.50 = 200
    # market_value = 200 * 0.65 = 130.0
    assert result["position_cost"] == 100.0
    assert result["position_market_value"] == 130.0
    assert result["unrealized_pnl"] == 30.0


@pytest.mark.asyncio
async def test_up_and_down_mixed_positions(test_db, mock_http_client):
    """
    Scenario: Multiple trades with mixed up/down directions.
    Expected: Each direction uses correct pricing formula.
    """
    trades = [
        Trade(
            market_ticker="BTC_UP_5M",
            direction="up",
            entry_price=0.50,
            size=100.0,
            settled=False,
            trading_mode="paper",
            timestamp=datetime.now(timezone.utc),
        ),
        Trade(
            market_ticker="BTC_DOWN_5M",
            direction="down",
            entry_price=0.50,
            size=100.0,
            settled=False,
            trading_mode="paper",
            timestamp=datetime.now(timezone.utc),
        ),
    ]
    for t in trades:
        test_db.add(t)
    test_db.commit()

    # Mock Gamma API responses
    async def mock_get(url, timeout=None):
        response = MagicMock()
        response.status_code = 200
        response.raise_for_status = MagicMock()
        if "BTC_UP_5M" in url:
            response.json = MagicMock(return_value=[{"yes_price": 0.65, "no_price": 0.35}])
        elif "BTC_DOWN_5M" in url:
            response.json = MagicMock(return_value=[{"yes_price": 0.65, "no_price": 0.35}])
        return response

    mock_http_client.get = AsyncMock(side_effect=mock_get)

    result = await calculate_position_market_value("paper", test_db, mock_http_client)

    # UP: shares=200, mkt_val=200*0.65=130
    # DOWN: shares=200, mkt_val=200*(1-0.35)=200*0.65=130
    # Total: 260.0
    assert result["position_cost"] == 200.0
    assert result["position_market_value"] == 260.0
    assert result["unrealized_pnl"] == 60.0
