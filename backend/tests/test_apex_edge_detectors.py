"""Tests for APEX edge scanners."""

from __future__ import annotations

from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock

import pytest

from backend.core.edge.scanners.resolution_timing import ResolutionTimingScanner, RISKY_KEYWORDS
from backend.core.edge.scanners.liquidity_gap import LiquidityGapScanner
from backend.core.edge.scanners.order_book_stale import OrderBookStaleScanner
from backend.data.polymarket_clob import OrderBook
from backend.core.edge.edge_model import EdgeType


def make_market(**overrides):
    """Create a test market dict."""
    base = {
        "question": "Will it rain in NYC tomorrow?",
        "volume": 5000,
        "endDate": (datetime.now(timezone.utc) + timedelta(days=2)).isoformat(),
        "slug": "will-it-rain-nyc",
        "conditionId": "cond123",
        "clobTokenIds": '["token1"]',
        "outcomePrices": '["0.92", "0.08"]',
        "outcomes": '["Yes", "No"]',
    }
    base.update(overrides)
    return base


class TestResolutionTimingScanner:
    def setup_method(self):
        self.scanner = ResolutionTimingScanner()
        # Override config-driven defaults for test determinism
        self.scanner.min_edge_pp = 0.005
        self.scanner.min_price = 0.85
        self.scanner.max_price = 0.99
        self.scanner.min_volume = 1000
        self.scanner.min_days = 0.1
        self.scanner.max_days = 10

    def test_skips_risky_markets(self):
        market = make_market(question="Will bitcoin reach $100k?")
        result = self.scanner._evaluate_market(market, datetime.now(timezone.utc), set())
        assert result is None

    def test_skips_low_volume(self):
        market = make_market(volume=100)
        result = self.scanner._evaluate_market(market, datetime.now(timezone.utc), set())
        assert result is None

    def test_skips_no_end_date(self):
        market = make_market(endDate=None, end_date_iso=None, endDateIso=None)
        result = self.scanner._evaluate_market(market, datetime.now(timezone.utc), set())
        assert result is None

    def test_skips_too_far_from_resolution(self):
        market = make_market(endDate=(datetime.now(timezone.utc) + timedelta(days=30)).isoformat())
        result = self.scanner._evaluate_market(market, datetime.now(timezone.utc), set())
        assert result is None

    def test_skips_existing_position(self):
        market = make_market()
        result = self.scanner._evaluate_market(market, datetime.now(timezone.utc), {"will-it-rain-nyc"})
        assert result is None

    def test_detects_edge(self):
        market = make_market()
        result = self.scanner._evaluate_market(market, datetime.now(timezone.utc), set())
        assert result is not None
        assert result.edge_type == EdgeType.RESOLUTION_TIMING
        assert result.edge_pp > 0

    def test_edge_pp_deduction(self):
        """Edge pp should have fee/slippage deduction (0.001 subtracted)."""
        market = make_market(outcomePrices='["0.92", "0.08"]')
        result = self.scanner._evaluate_market(market, datetime.now(timezone.utc), set())
        if result is not None:
            # Raw edge - 0.001 = edge_pp
            assert result.edge_pp > 0

    def test_risky_keywords_complete(self):
        expected = ["wti", "oil", "crypto", "bitcoin", "btc"]
        for kw in expected:
            assert kw in RISKY_KEYWORDS, f"Missing risky keyword: {kw}"

    def test_skips_no_token_id(self):
        market = make_market(clobTokenIds="[]")
        result = self.scanner._evaluate_market(market, datetime.now(timezone.utc), set())
        assert result is None

    def test_skips_price_below_min(self):
        market = make_market(outcomePrices='["0.50", "0.50"]')
        result = self.scanner._evaluate_market(market, datetime.now(timezone.utc), set())
        assert result is None


class TestLiquidityGapScanner:
    def setup_method(self):
        self.scanner = LiquidityGapScanner()
        self.scanner.min_edge_pp = 1.0
        self.scanner.min_spread = 0.03
        self.scanner.min_volume = 5000

    def test_skips_no_token_id(self):
        market = make_market(clobTokenIds="[]")
        result = self.scanner._evaluate_from_market_data(market, datetime.now(timezone.utc))
        assert result is None

    def test_detects_wide_spread(self):
        # yes=0.55, no=0.40 → spread=0.05
        market = make_market(outcomePrices='["0.55", "0.40"]', volume=10000)
        result = self.scanner._evaluate_from_market_data(market, datetime.now(timezone.utc))
        assert result is not None
        assert result.edge_type == EdgeType.LIQUIDITY_GAP

    def test_skips_narrow_spread(self):
        # yes=0.50, no=0.50 → spread≈0
        market = make_market(outcomePrices='["0.505", "0.495"]', volume=10000)
        result = self.scanner._evaluate_from_market_data(market, datetime.now(timezone.utc))
        assert result is None

    def test_skips_low_volume(self):
        market = make_market(outcomePrices='["0.55", "0.40"]', volume=100)
        result = self.scanner._evaluate_from_market_data(market, datetime.now(timezone.utc))
        assert result is None


class TestOrderBookStaleScanner:
    def setup_method(self):
        self.scanner = OrderBookStaleScanner()

    @pytest.mark.asyncio
    async def test_skips_no_token_id(self):
        market = {"slug": "test", "token_id": None, "clob_token_id": None}
        clob = AsyncMock()
        result = await self.scanner._evaluate_market(market, clob, datetime.now(timezone.utc))
        assert result is None

    @pytest.mark.asyncio
    async def test_detects_stale_divergence(self):
        market = {"slug": "test", "token_id": "token1", "volume": 5000}
        clob = AsyncMock()
        clob.get_order_book = AsyncMock(return_value=OrderBook(
            token_id="token1",
            bids=[{"price": "0.45", "size": "10"}],
            asks=[{"price": "0.55", "size": "10"}],
        ))
        # divergence = |0.54 - 0.50| = 0.04, within (min, max] bounds
        clob.get_last_trade_price = AsyncMock(return_value=0.54)
        result = await self.scanner._evaluate_market(market, clob, datetime.now(timezone.utc))
        assert result is not None
        assert result.edge_type == EdgeType.ORDER_BOOK_STALE

    @pytest.mark.asyncio
    async def test_skips_small_divergence(self):
        market = {"slug": "test", "token_id": "token1", "volume": 5000}
        clob = AsyncMock()
        clob.get_order_book = AsyncMock(return_value=OrderBook(
            token_id="token1",
            bids=[{"price": "0.49", "size": "10"}],
            asks=[{"price": "0.51", "size": "10"}],
        ))
        clob.get_last_trade_price = AsyncMock(return_value=0.50)
        result = await self.scanner._evaluate_market(market, clob, datetime.now(timezone.utc))
        assert result is None

    @pytest.mark.asyncio
    async def test_skips_excessive_divergence(self):
        """A huge gap between last trade and current mid means the *last
        trade* is stale (an old fill in a thin market), not the order book —
        this should be skipped, not treated as a high-confidence edge."""
        market = {"slug": "test", "token_id": "token1", "volume": 5000}
        clob = AsyncMock()
        clob.get_order_book = AsyncMock(return_value=OrderBook(
            token_id="token1",
            bids=[{"price": "0.45", "size": "10"}],
            asks=[{"price": "0.55", "size": "10"}],
        ))
        # divergence = |0.65 - 0.50| = 0.15, beyond max_divergence_pp
        clob.get_last_trade_price = AsyncMock(return_value=0.65)
        result = await self.scanner._evaluate_market(market, clob, datetime.now(timezone.utc))
        assert result is None

    @pytest.mark.asyncio
    async def test_skips_low_volume(self):
        """Thin markets trade rarely, so a stale 'last trade' is the norm,
        not a signal — require minimum volume before considering staleness."""
        market = {"slug": "test", "token_id": "token1", "volume": 100}
        clob = AsyncMock()
        clob.get_order_book = AsyncMock(return_value=OrderBook(
            token_id="token1",
            bids=[{"price": "0.45", "size": "10"}],
            asks=[{"price": "0.55", "size": "10"}],
        ))
        clob.get_last_trade_price = AsyncMock(return_value=0.54)
        result = await self.scanner._evaluate_market(market, clob, datetime.now(timezone.utc))
        assert result is None

    @pytest.mark.asyncio
    async def test_no_direction_uses_no_token_scale(self):
        """For 'no' edges, entry/fair price and token id must be in the NO
        token's own scale, so risk_manager's edge_pp = (fair-entry)*100 is
        positive and matches the scanner's own (sign-agnostic) edge_pp."""
        market = {
            "slug": "test",
            "token_id": "yes_token",
            "volume": 5000,
            "clobTokenIds": '["yes_token", "no_token"]',
        }
        clob = AsyncMock()
        # mid_price = (0.45 + 0.59) / 2 = 0.52
        clob.get_order_book = AsyncMock(return_value=OrderBook(
            token_id="yes_token",
            bids=[{"price": "0.45", "size": "10"}],
            asks=[{"price": "0.59", "size": "10"}],
        ))
        # last_price (0.47) < mid_price (0.52) -> direction = "no";
        # divergence = 0.05, within (min, max] bounds
        clob.get_last_trade_price = AsyncMock(return_value=0.47)
        result = await self.scanner._evaluate_market(market, clob, datetime.now(timezone.utc))
        assert result is not None
        assert result.direction == "no"
        assert result.token_id == "no_token"
        # NO-scale: entry = 1 - mid, fair = 1 - last
        assert abs(result.entry_price - (1.0 - 0.52)) < 1e-9
        assert abs(result.fair_price - (1.0 - 0.47)) < 1e-9
        # Edge is positive in the traded token's own scale
        assert (result.fair_price - result.entry_price) * 100 > 0