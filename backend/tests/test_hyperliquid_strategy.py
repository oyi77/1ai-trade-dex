"""Tests for HyperliquidStrategy — Hyperliquid prediction market strategy."""

import pytest
from unittest.mock import AsyncMock, MagicMock
from dataclasses import dataclass, field
from typing import List

from backend.strategies.hyperliquid_strategy import HyperliquidStrategy
from backend.strategies.base import StrategyContext, CycleResult, MarketInfo

# Import HyperliquidClient for spec (to make isinstance checks work in tests)
try:
    from backend.data.hyperliquid_client import HyperliquidClient
except Exception:
    HyperliquidClient = type(None)  # fallback if import fails


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@dataclass
class _FakeHlMarket:
    market_id: str = "hl_market_1"
    status: str = "active"
    outcome_prices: List[float] = field(default_factory=lambda: [0.50, 0.50])


def _make_ctx(providers=None, params=None, mode="paper"):
    return StrategyContext(
        db=MagicMock(),
        clob=None,
        settings=MagicMock(),
        logger=MagicMock(),
        params=params or {},
        mode=mode,
        providers=providers or {},
    )


def _make_hl_market(market_id="hl_1", status="active", yes=0.50, no=0.50):
    return _FakeHlMarket(
        market_id=status and market_id, status=status, outcome_prices=[yes, no]
    )


def _make_mock_client(markets=None):
    """Create a mock client that passes isinstance(hl_provider, HyperliquidClient)."""
    mock_client = MagicMock(spec=HyperliquidClient)
    mock_client.get_markets = AsyncMock(return_value=markets or [])
    return mock_client


# ---------------------------------------------------------------------------
# Metadata
# ---------------------------------------------------------------------------


class TestHyperliquidMeta:
    def test_name(self):
        s = HyperliquidStrategy()
        assert s.name == "hyperliquid"

    def test_category(self):
        s = HyperliquidStrategy()
        assert s.category == "hyperliquid"

    def test_default_params(self):
        params = HyperliquidStrategy.default_params
        assert params["min_edge"] == 0.04
        assert params["max_entry_price"] == 0.80
        assert params["max_trade_usd"] == 50.0
        assert params["kelly_fraction"] == 0.25


# ---------------------------------------------------------------------------
# Market filter
# ---------------------------------------------------------------------------


class TestMarketFilter:
    @pytest.mark.asyncio
    async def test_filters_hyperliquid_only(self):
        s = HyperliquidStrategy()
        markets = [
            MarketInfo(
                ticker="hl",
                slug="hl",
                category="crypto",
                end_date=None,
                volume=5000,
                liquidity=2000,
                metadata={"platform": "hyperliquid"},
            ),
            MarketInfo(
                ticker="pm",
                slug="pm",
                category="crypto",
                end_date=None,
                volume=5000,
                liquidity=2000,
                metadata={"platform": "polymarket"},
            ),
            MarketInfo(
                ticker="hl2",
                slug="hl2",
                category="crypto",
                end_date=None,
                volume=5000,
                liquidity=2000,
                metadata={"platform": "hyperliquid"},
            ),
        ]
        filtered = await s.market_filter(markets)
        assert len(filtered) == 2
        assert all(m.metadata.get("platform") == "hyperliquid" for m in filtered)

    @pytest.mark.asyncio
    async def test_empty_markets(self):
        s = HyperliquidStrategy()
        filtered = await s.market_filter([])
        assert filtered == []

    @pytest.mark.asyncio
    async def test_no_platform_metadata_excluded(self):
        s = HyperliquidStrategy()
        markets = [
            MarketInfo(
                ticker="x",
                slug="x",
                category="crypto",
                end_date=None,
                volume=5000,
                liquidity=2000,
                metadata={},
            ),
        ]
        filtered = await s.market_filter(markets)
        assert len(filtered) == 0


# ---------------------------------------------------------------------------
# run_cycle — no provider
# ---------------------------------------------------------------------------


class TestRunCycleNoProvider:
    @pytest.mark.asyncio
    async def test_no_provider_returns_error(self):
        """Without Hyperliquid provider, returns error CycleResult."""
        strategy = HyperliquidStrategy()
        ctx = _make_ctx(providers={})
        result = await strategy.run_cycle(ctx)

        assert isinstance(result, CycleResult)
        assert result.decisions_recorded == 0
        assert len(result.errors) > 0
        assert (
            "provider" in result.errors[0].lower()
            or "not configured" in result.errors[0].lower()
        )


# ---------------------------------------------------------------------------
# run_cycle — with mocked client
# ---------------------------------------------------------------------------


class TestRunCycleWithClient:
    @pytest.mark.asyncio
    async def test_no_markets_returns_empty(self):
        """Client returns no markets -> empty result."""
        strategy = HyperliquidStrategy()
        mock_client = _make_mock_client(markets=[])
        ctx = _make_ctx(providers={"hyperliquid": mock_client})
        result = await strategy.run_cycle(ctx)
        assert result.decisions_recorded == 0
        assert result.trades_placed == 0

    @pytest.mark.asyncio
    async def test_detects_mispriced_market(self):
        """Market with YES+NO far from 1.0 triggers a signal."""
        strategy = HyperliquidStrategy()
        mispriced = _make_hl_market(yes=0.30, no=0.30, status="active")
        mock_client = _make_mock_client(markets=[mispriced])
        ctx = _make_ctx(providers={"hyperliquid": mock_client})
        result = await strategy.run_cycle(ctx)
        assert result.decisions_recorded >= 1
        assert result.trades_attempted >= 1

    @pytest.mark.asyncio
    async def test_fair_market_no_signal(self):
        """Market with YES+NO near 1.0 produces no signal."""
        strategy = HyperliquidStrategy()
        fair = _make_hl_market(yes=0.50, no=0.50, status="active")
        mock_client = _make_mock_client(markets=[fair])
        ctx = _make_ctx(providers={"hyperliquid": mock_client})
        result = await strategy.run_cycle(ctx)
        assert result.decisions_recorded == 0

    @pytest.mark.asyncio
    async def test_inactive_markets_skipped(self):
        """Inactive markets are skipped."""
        strategy = HyperliquidStrategy()
        inactive = _make_hl_market(yes=0.30, no=0.30, status="inactive")
        mock_client = _make_mock_client(markets=[inactive])
        ctx = _make_ctx(providers={"hyperliquid": mock_client})
        result = await strategy.run_cycle(ctx)
        assert result.decisions_recorded == 0

    @pytest.mark.asyncio
    async def test_edge_below_threshold_skipped(self):
        """Market with small mispricing below min_edge is skipped."""
        strategy = HyperliquidStrategy()
        # edge = abs(1.0 - 0.98) / 2 = 0.01 < min_edge 0.04
        small_edge = _make_hl_market(yes=0.49, no=0.49, status="active")
        mock_client = _make_mock_client(markets=[small_edge])
        ctx = _make_ctx(providers={"hyperliquid": mock_client})
        result = await strategy.run_cycle(ctx)
        assert result.decisions_recorded == 0

    @pytest.mark.asyncio
    async def test_max_entry_price_filter(self):
        """Market with both outcome prices > max_entry_price is skipped."""
        strategy = HyperliquidStrategy()
        # YES=0.95, NO=0.95 => sum=1.90, edge=0.45 > min_edge
        # Both YES and NO > max_entry (0.80) => target_price > max_entry => skipped
        high_entry = _make_hl_market(yes=0.95, no=0.95, status="active")
        mock_client = _make_mock_client(markets=[high_entry])
        ctx = _make_ctx(providers={"hyperliquid": mock_client})
        result = await strategy.run_cycle(ctx)
        assert result.decisions_recorded == 0

    @pytest.mark.asyncio
    async def test_exception_in_client_returns_error(self):
        """Client exception is caught and returned as error."""
        strategy = HyperliquidStrategy()
        mock_client = _make_mock_client(markets=[])
        mock_client.get_markets = AsyncMock(side_effect=RuntimeError("HL API down"))
        ctx = _make_ctx(providers={"hyperliquid": mock_client})
        result = await strategy.run_cycle(ctx)
        assert len(result.errors) > 0

    @pytest.mark.asyncio
    async def test_paper_mode_signal(self):
        """Paper mode still records trades_placed."""
        strategy = HyperliquidStrategy()
        mispriced = _make_hl_market(yes=0.30, no=0.30, status="active")
        mock_client = _make_mock_client(markets=[mispriced])
        ctx = _make_ctx(providers={"hyperliquid": mock_client}, mode="paper")
        result = await strategy.run_cycle(ctx)
        assert result.trades_placed >= 1


# ---------------------------------------------------------------------------
# run() wrapper
# ---------------------------------------------------------------------------


class TestRunWrapper:
    @pytest.mark.asyncio
    async def test_run_returns_cycle_result(self):
        strategy = HyperliquidStrategy()
        ctx = _make_ctx()
        result = await strategy.run(ctx)
        assert isinstance(result, CycleResult)
        assert result.cycle_duration_ms >= 0
