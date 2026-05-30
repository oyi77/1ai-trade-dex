"""Tests for BtcMomentumStrategy — deprecated/disabled strategy."""

import pytest
from unittest.mock import MagicMock

from backend.strategies.btc_momentum import BtcMomentumStrategy, EXPERIMENTAL_WARNING
from backend.strategies.base import StrategyContext, CycleResult


def _make_ctx():
    return StrategyContext(
        db=MagicMock(),
        clob=None,
        settings=MagicMock(),
        logger=MagicMock(),
        params={},
        mode="paper",
    )


# ---------------------------------------------------------------------------
# Metadata
# ---------------------------------------------------------------------------


class TestBtcMomentumMeta:
    def test_name(self):
        s = BtcMomentumStrategy()
        assert s.name == "btc_momentum"

    def test_category(self):
        s = BtcMomentumStrategy()
        assert s.category == "experimental"

    def test_description_contains_experimental_warning(self):
        s = BtcMomentumStrategy()
        assert "EXPERIMENTAL" in s.description

    def test_default_params_force_disabled(self):
        assert BtcMomentumStrategy.default_params["_force_disabled"] is True

    def test_experimental_warning_constant(self):
        assert "-49.5%" in EXPERIMENTAL_WARNING
        assert "4W/11L" in EXPERIMENTAL_WARNING


# ---------------------------------------------------------------------------
# Market filter
# ---------------------------------------------------------------------------


class TestMarketFilter:
    @pytest.mark.asyncio
    async def test_filters_btc_5m_markets(self):
        from backend.strategies.base import MarketInfo

        s = BtcMomentumStrategy()
        markets = [
            MarketInfo(ticker="btc-5m-yes", slug="btc-5m-yes", category="crypto", end_date=None, volume=5000, liquidity=2000),
            MarketInfo(ticker="eth-15m", slug="eth-15m-yes", category="crypto", end_date=None, volume=5000, liquidity=2000),
            MarketInfo(ticker="sol-5m", slug="sol-5m-yes", category="crypto", end_date=None, volume=5000, liquidity=2000),
        ]
        filtered = await s.market_filter(markets)
        # Only "btc-5m-yes" contains both "btc" and "5m"
        assert len(filtered) == 1
        assert filtered[0].slug == "btc-5m-yes"

    @pytest.mark.asyncio
    async def test_empty_markets(self):
        s = BtcMomentumStrategy()
        filtered = await s.market_filter([])
        assert filtered == []


# ---------------------------------------------------------------------------
# run_cycle — always disabled
# ---------------------------------------------------------------------------


class TestRunCycle:
    @pytest.mark.asyncio
    async def test_always_returns_empty_result(self):
        """Strategy is disabled; run_cycle returns zero trades."""
        strategy = BtcMomentumStrategy()
        ctx = _make_ctx()
        result = await strategy.run_cycle(ctx)

        assert isinstance(result, CycleResult)
        assert result.decisions_recorded == 0
        assert result.trades_attempted == 0
        assert result.trades_placed == 0

    @pytest.mark.asyncio
    async def test_run_cycle_never_crashes(self):
        """run_cycle must not raise even with minimal context."""
        strategy = BtcMomentumStrategy()
        ctx = _make_ctx()
        # Should complete without exception
        result = await strategy.run_cycle(ctx)
        assert result is not None

    @pytest.mark.asyncio
    async def test_run_wrapper_returns_result(self):
        """Base run() wrapper returns a valid CycleResult."""
        strategy = BtcMomentumStrategy()
        ctx = _make_ctx()
        result = await strategy.run(ctx)
        assert isinstance(result, CycleResult)
        assert result.errors == []
