"""Tests for backend/strategies/cex_pm_leadlag.py."""

from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from datetime import datetime, timezone

from backend.strategies.base import StrategyContext
from backend.strategies.cex_pm_leadlag import CexPmLeadLagStrategy
from backend.data.btc_markets import CryptoMarket
from backend.data.crypto import CryptoMicrostructure


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
@patch("backend.strategies.cex_pm_leadlag.compute_crypto_microstructure")
@patch("backend.strategies.cex_pm_leadlag.fetch_active_crypto_markets")
@patch("backend.core.auto_sell.check_strategy_positions_for_auto_sell")
@patch("backend.strategies.cex_pm_leadlag._fetch_pm_mid")
@patch("backend.strategies.cex_pm_leadlag.run_debate_with_routing")
@patch("backend.strategies.cex_pm_leadlag.record_decision_standalone")
async def test_cex_pm_leadlag_run_cycle(
    mock_record_decision,
    mock_debate,
    mock_fetch_mid,
    mock_auto_sell,
    mock_fetch_markets,
    mock_microstructure,
):
    """Verify that cex_pm_leadlag iterates over assets, runs auto-sell, and place BUY decisions."""
    # 1. Mock microstructures
    # btc: positive momentum (direction UP)
    btc_micro = CryptoMicrostructure(
        price=60000.0,
        volatility=0.01,
        rsi=50.0,
        momentum_1m=0.02, # high momentum to trigger raw_prob and edge
        momentum_5m=0.05,
        source="binance",
    )
    # eth: negative momentum (direction DOWN)
    eth_micro = CryptoMicrostructure(
        price=3000.0,
        volatility=0.015,
        rsi=45.0,
        momentum_1m=-0.02,
        momentum_5m=-0.04,
        source="binance",
    )
    # sol: too low momentum (skip)
    sol_micro = CryptoMicrostructure(
        price=150.0,
        volatility=0.005,
        rsi=50.0,
        momentum_1m=0.0001, # < 0.001 min_momentum
        momentum_5m=0.001,
        source="binance",
    )

    def side_effect_micro(asset):
        if asset == "bitcoin":
            return btc_micro
        elif asset == "ethereum":
            return eth_micro
        elif asset == "solana":
            return sol_micro
        return None

    mock_microstructure.side_effect = side_effect_micro

    # 2. Mock markets
    btc_market = _make_mock_market("btc-updown-5m-1", "btc_up_id", "btc_down_id")
    eth_market = _make_mock_market("eth-updown-5m-1", "eth_up_id", "eth_down_id")
    sol_market = _make_mock_market("sol-updown-5m-1", "sol_up_id", "sol_down_id")

    def side_effect_markets(asset):
        if asset == "btc":
            return [btc_market]
        elif asset == "eth":
            return [eth_market]
        elif asset == "sol":
            return [sol_market]
        return []

    mock_fetch_markets.side_effect = side_effect_markets

    # 3. Mock midpoint price from Polymarket
    # BTC mid = 0.40. Direction is up -> target_mid = 0.40. 
    # Sigmoid raw_prob based on 0.02 momentum -> maxed out at 0.65 implied_prob
    # edge = (0.65 - 0.40) - 0.03 (min_edge) - 0.04 (fees) = 0.18 > 0 -> BUY!
    # ETH mid = 0.40. Direction is down -> target_mid = 1 - 0.40 = 0.60.
    # Sigmoid raw_prob based on -0.02 -> implied_prob = 0.65.
    # edge = (0.65 - 0.60) - 0.03 - 0.04 = -0.02 < 0 -> SKIP!
    mock_fetch_mid.return_value = 0.40

    # 4. Mock debate router to pass validation
    mock_debate.return_value = MagicMock(confidence=0.7)

    # 5. Run strategy
    strategy = CexPmLeadLagStrategy()
    ctx = StrategyContext(
        db=MagicMock(),
        clob=MagicMock(),
        settings=MagicMock(),
        logger=MagicMock(),
        bankroll=100.0,
        mode="paper",
        params={
            "debate_enabled": True,
            "min_edge": 0.03,
            "fee_rate": 0.02,
        },
    )

    result = await strategy.run_cycle(ctx)

    # Verify auto-sell was checked
    mock_auto_sell.assert_called_once_with(
        "cex_pm_leadlag", clob_client=ctx.clob,
        profit_target_pct=0.08, stop_loss_pct=0.20, max_hold_seconds=240,
    )

    # Verify microstructure and markets were fetched for all three assets
    assert mock_microstructure.call_count == 3
    assert mock_fetch_markets.call_count == 2 # btc and eth fetched (sol skipped before fetching markets due to low momentum)

    # Check decisions and trades
    assert result.decisions_recorded == 2 # 1 for btc, 1 for eth
    assert result.trades_attempted == 1   # only btc is BUY
    assert len(result.decisions) == 1
    assert result.decisions[0]["market_ticker"] == "btc-updown-5m-1"
    assert result.decisions[0]["decision"] == "BUY"
    assert result.decisions[0]["token_id"] == "btc_up_id"
