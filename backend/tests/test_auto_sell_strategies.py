"""Tests verifying that target strategies call check_strategy_positions_for_auto_sell twice per cycle with overrides."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from backend.strategies.base import StrategyContext, CycleResult
from backend.strategies.crypto_oracle import CryptoOracleStrategy
from backend.strategies.general_market_scanner import GeneralMarketScanner
from backend.strategies.bond_scanner import BondScannerStrategy
from backend.strategies.longshot_bias import LongshotBiasStrategy


@pytest.mark.asyncio
async def test_strategies_call_auto_sell_twice(monkeypatch):
    # Setup mocks for check_strategy_positions_for_auto_sell
    calls = []

    async def mock_check(
        strategy_name,
        clob_client=None,
        profit_target_pct=None,
        stop_loss_pct=None,
        max_hold_seconds=None,
    ):
        calls.append(
            {
                "strategy": strategy_name,
                "clob": clob_client,
                "profit_target": profit_target_pct,
                "stop_loss": stop_loss_pct,
                "max_hold": max_hold_seconds,
            }
        )
        return []

    monkeypatch.setattr(
        "backend.core.auto_sell.check_strategy_positions_for_auto_sell",
        mock_check,
    )

    # Globally mock httpx.AsyncClient.get to avoid real HTTP requests
    class MockResponse:

        def raise_for_status(self):
            pass

        def json(self):
            return []

    async def mock_get(*args, **kwargs):
        return MockResponse()

    monkeypatch.setattr("httpx.AsyncClient.get", mock_get)

    # Set up basic context with complete mock settings
    mock_db = MagicMock()
    mock_clob = MagicMock()
    mock_settings = MagicMock()
    mock_settings.AI_ENABLED = True
    mock_settings.DEFAULT_VENUE = "polymarket"
    mock_settings.KELLY_FRACTION = 0.25
    mock_settings.MIN_ORDER_USDC = 1.0
    mock_settings.MAX_POSITION_FRACTION = 0.30
    mock_settings.PAPER_CLOB_FEE_RATE = 0.02
    mock_logger = MagicMock()

    ctx = StrategyContext(
        db=mock_db,
        clob=mock_clob,
        settings=mock_settings,
        logger=mock_logger,
        params={
            "auto_sell_profit_target_pct": 0.05,
            "auto_sell_stop_loss_pct": 0.08,
            "auto_sell_max_hold_seconds": 600,
        },
        mode="paper",
        bankroll=1000.0,
    )



    # Test CryptoOracleStrategy
    calls.clear()
    crypto_strat = CryptoOracleStrategy()
    crypto_strat._tokens_populated = True

    async def mock_fetch_crypto_price(asset):
        return 95000.0

    monkeypatch.setattr(
        "backend.strategies.crypto_oracle.fetch_crypto_price_for_asset",
        mock_fetch_crypto_price,
    )

    async def mock_fetch_active_crypto(asset=None):
        return []

    monkeypatch.setattr(
        "backend.data.btc_markets.fetch_active_crypto_markets",
        mock_fetch_active_crypto,
    )

    await crypto_strat.run_cycle(ctx)
    assert len(calls) == 2
    for call in calls:
        assert call["strategy"] == "crypto_oracle"
        assert call["profit_target"] == 0.05
        assert call["stop_loss"] == 0.08
        assert call["max_hold"] == 600

    # Test GeneralMarketScanner
    calls.clear()
    general_strat = GeneralMarketScanner()
    ctx.params.update(
        {
            "min_volume": 100,
            "min_edge": 0.01,
            "max_price": 0.99,
            "min_price": 0.01,
            "skip_hours": [],
        }
    )
    mock_provider = AsyncMock()
    mock_provider.get_markets.return_value = []
    ctx.providers = {"polymarket": mock_provider}

    await general_strat.run_cycle(ctx)
    assert len(calls) == 2
    for call in calls:
        assert call["strategy"] == "general_scanner"
        assert call["profit_target"] == 0.05
        assert call["stop_loss"] == 0.08
        assert call["max_hold"] == 600

    # Test BondScannerStrategy
    calls.clear()
    bond_strat = BondScannerStrategy()

    ctx.params.update(
        {
            "min_price": 0.85,
            "max_price": 0.99,
            "min_volume": 1000,
            "max_days_to_resolution": 10,
            "min_days_to_resolution": 1,
            "max_position_size": 20,
            "max_concurrent_bonds": 5,
        }
    )

    await bond_strat.run_cycle(ctx)
    assert len(calls) == 2
    for call in calls:
        assert call["strategy"] == "bond_scanner"
        assert call["profit_target"] == 0.05
        assert call["stop_loss"] == 0.08
        assert call["max_hold"] == 600

    # Test LongshotBiasStrategy
    calls.clear()
    longshot_strat = LongshotBiasStrategy()
    mock_provider = AsyncMock()
    mock_provider.get_markets.return_value = []
    ctx.providers = {"polymarket": mock_provider}

    ctx.params.update(
        {
            "max_price": 0.30,
            "min_ev": 0.05,
            "max_position_usd": 20.0,
            "kelly_fraction": 0.25,
        }
    )

    await longshot_strat.run_cycle(ctx)
    assert len(calls) == 2
    for call in calls:
        assert call["strategy"] == "longshot_bias"
        assert call["profit_target"] == 0.05
        assert call["stop_loss"] == 0.08
        assert call["max_hold"] == 600
