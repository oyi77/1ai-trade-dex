"""Tests for backend/strategies/cex_pm_leadlag.py."""

from unittest.mock import AsyncMock, MagicMock, patch
import asyncio
import pytest
from datetime import datetime, timezone

from backend.strategies.base import StrategyContext, CycleResult
from backend.strategies.cex_pm_leadlag import CexPmLeadLagStrategy
from backend.data.btc_markets import CryptoMarket
from backend.data.crypto import CryptoMicrostructure


def _make_valid_slug(asset: str) -> str:
    ts = str(int(datetime.now(timezone.utc).timestamp()))
    return f"{asset}-updown-5m-{ts}"


def _make_mock_market(slug: str, up_token: str, down_token: str) -> CryptoMarket:
    from datetime import timedelta

    now = datetime.now(timezone.utc)
    return CryptoMarket(
        slug=slug,
        market_id=f"id-{slug}",
        up_price=0.5,
        down_price=0.5,
        window_start=now - timedelta(minutes=2),
        window_end=now + timedelta(minutes=3),
        volume=1000.0,
        closed=False,
        up_token_id=up_token,
        down_token_id=down_token,
        asset="btc",
    )


@pytest.mark.asyncio
@patch("backend.strategies.cex_pm_leadlag._fetch_pm_mid", new_callable=AsyncMock)
@patch("backend.strategies.cex_pm_leadlag.compute_crypto_microstructure", new_callable=AsyncMock)
@patch("backend.strategies.cex_pm_leadlag.fetch_active_crypto_markets", new_callable=AsyncMock)
@patch("backend.strategies.cex_pm_leadlag.get_shared_client")
async def test_cex_pm_leadlag_iterates_assets_and_fetches_markets_and_records(
    mock_shared_client,
    mock_fetch_markets,
    mock_microstructure,
    mock_fetch_mid,
):
    mock_markets = [
        _make_mock_market(_make_valid_slug("btc"), "btc_up_id", "btc_down_id"),
        _make_mock_market(_make_valid_slug("eth"), "eth_up_id", "eth_down_id"),
        _make_mock_market(_make_valid_slug("sol"), "sol_up_id", "sol_down_id"),
    ]

    def micro_side(asset):
        if asset == "bitcoin":
            return CryptoMicrostructure(
                price=60000.0,
                volatility=0.01,
                rsi=50.0,
                momentum_1m=0.02,
                momentum_5m=0.05,
                source="binance",
            )
        if asset == "ethereum":
            return CryptoMicrostructure(
                price=3000.0,
                volatility=0.015,
                rsi=45.0,
                momentum_1m=-0.012,
                momentum_5m=-0.024,
                source="binance",
            )
        if asset == "solana":
            return CryptoMicrostructure(
                price=150.0,
                volatility=0.005,
                rsi=50.0,
                momentum_1m=0.0001,
                momentum_5m=0.001,
                source="binance",
            )
        return None

    mock_microstructure.side_effect = micro_side
    mock_fetch_markets.return_value = mock_markets

    # Set PM mid such that BTC trade is not BUY, ETH trade is BUY, SOL filtered
    async def mid_fetch_side(client, token_id):
        if token_id == "btc_up_id":
            return 0.45  # mid too close to 50 for BTC
        if token_id == "eth_up_id":
            return 0.40  # strong UP edge
        return None

    mock_fetch_mid.side_effect = mid_fetch_side
    mock_shared_client.return_value = AsyncMock()

    strategy = CexPmLeadLagStrategy()
    ctx = StrategyContext(
        db=MagicMock(),
        clob=AsyncMock(),
        settings=MagicMock(),
        logger=MagicMock(),
        bankroll=100.0,
        mode="paper",
        params={
            "debate_enabled": False,
            "min_edge": 0.03,
            "fee_rate": 0.02,
            "min_market_distance": 0.0,
        },
    )

    result = await strategy.run_cycle(ctx)

    assert isinstance(result, CycleResult)
    assert result.markets_scanned >= 1
    assert result.decisions_recorded >= 1


@pytest.mark.asyncio
@patch("backend.strategies.cex_pm_leadlag._fetch_pm_mid", new_callable=AsyncMock)
@patch("backend.strategies.cex_pm_leadlag.compute_crypto_microstructure", new_callable=AsyncMock)
@patch("backend.strategies.cex_pm_leadlag.fetch_active_crypto_markets", new_callable=AsyncMock)
@patch("backend.strategies.cex_pm_leadlag.get_shared_client")
async def test_cex_pm_leadlag_strong_btc_signal_records_decision_and_buy(
    mock_shared_client,
    mock_fetch_markets,
    mock_microstructure,
    mock_fetch_mid,
):
    crypto_micro = CryptoMicrostructure(
        price=60000.0,
        volatility=0.01,
        rsi=50.0,
        momentum_1m=0.05,
        momentum_5m=0.02,
        source="binance",
    )
    mock_microstructure.return_value = crypto_micro
    market = _make_mock_market(_make_valid_slug("btc"), "btc_up_id", "btc_down_id")
    mock_fetch_markets.return_value = [market]

    # Strong UP signal should see market underpricing UP outcome, mid = 0.40
    mock_fetch_mid.return_value = 0.40
    mock_shared_client.return_value = AsyncMock()

    db = MagicMock()
    clob = AsyncMock()
    strategy = CexPmLeadLagStrategy()
    ctx = StrategyContext(
        db=db,
        clob=clob,
        settings=MagicMock(),
        logger=MagicMock(),
        bankroll=100.0,
        mode="paper",
        params={
            "debate_enabled": False,
            "min_edge": 0.03,
            "fee_rate": 0.02,
            "min_confidence": 0.70,
            "min_market_distance": 0.0,
        },
    )

    result = await strategy.run_cycle(ctx)

    assert isinstance(result, CycleResult)
    assert result.markets_scanned >= 1
    assert result.decisions_recorded >= 1
    assert any(decision.get("decision") == "BUY" for decision in result.decisions)
