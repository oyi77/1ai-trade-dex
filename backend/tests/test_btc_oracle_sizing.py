"""Tests for BTC Oracle autonomous sizing proposals."""

import pytest
from unittest.mock import AsyncMock, patch

from backend.strategies.base import StrategyContext
from backend.strategies.btc_oracle import BtcOracleStrategy, calculate_dynamic_size


def test_dynamic_size_scales_with_edge_and_confidence():
    small = calculate_dynamic_size(edge=0.02, confidence=0.50, max_position_usd=50)
    large = calculate_dynamic_size(edge=0.10, confidence=1.00, max_position_usd=50)

    assert small == pytest.approx(5.0)
    assert large == pytest.approx(50.0)
    assert small < large


def test_dynamic_size_never_exceeds_strategy_cap():
    size = calculate_dynamic_size(edge=0.50, confidence=1.00, max_position_usd=25)

    assert size == pytest.approx(25.0)


def test_dynamic_size_keeps_minimum_probe_when_cap_allows():
    size = calculate_dynamic_size(edge=0.001, confidence=0.01, max_position_usd=50)

    assert size == pytest.approx(5.0)


def test_dynamic_size_respects_zero_cap():
    size = calculate_dynamic_size(edge=0.10, confidence=1.00, max_position_usd=0)

    assert size == pytest.approx(0.0)


@pytest.mark.asyncio
async def test_btc_oracle_does_not_place_direct_clob_orders():
    class Market:
        market_id = "btc-5m-test"
        slug = "btc-5m-test"
        window_end = __import__("datetime").datetime.now(__import__("datetime").timezone.utc) + __import__("datetime").timedelta(minutes=1)
        up_price = 0.55
        down_price = 0.45
        up_token_id = "up-token"
        down_token_id = "down-token"

    from backend.data.crypto import BtcMicrostructure
    micro = BtcMicrostructure(rsi=70.0, momentum_5m=0.05, vwap_deviation=0.01, sma_crossover=0.01, price=100_000.0)

    clob = AsyncMock()
    ctx = StrategyContext(
        db=None,
        clob=clob,
        settings=None,
        logger=None,
        params={"min_edge": 0.01, "max_position_usd": 50},
        mode="live",
    )

    with (
        patch("backend.strategies.btc_oracle.fetch_btc_price", AsyncMock(return_value=100_000.0)),
        patch("backend.data.crypto.compute_btc_microstructure", AsyncMock(return_value=micro)),
        patch("backend.data.btc_markets.fetch_active_btc_markets", AsyncMock(return_value=[Market()])),
        patch("backend.core.market_scanner.fetch_markets_by_keywords", AsyncMock(return_value=[])),
        patch("backend.strategies.btc_oracle.record_decision_standalone"),
    ):
        result = await BtcOracleStrategy().run_cycle(ctx)

    assert result.trades_attempted >= 1
    assert result.trades_placed == 0
    clob.place_limit_order.assert_not_called()
