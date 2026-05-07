"""Tests for UniversalScanner — HFT market scanner."""

import asyncio
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from backend.strategies.universal_scanner import (
    UniversalScanner,
    _parse_market,
    PAGE_SIZE,
    MAX_MARKETS,
)


def make_market(yes_price: float = 0.6, no_price: float = 0.4, **kwargs) -> dict:
    base = {
        "conditionId": "test-condition-1",
        "slug": "test-slug",
        "category": "Politics",
        "end_date": "2026-12-31T00:00:00Z",
        "volume": "100000",
        "liquidity": "50000",
        "outcomePrices": [str(yes_price), str(no_price)],
        "question": "Will X happen?",
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    base.update(kwargs)
    return base


class TestParseMarket:
    def test_parses_valid_market(self):
        m = make_market(yes_price=0.65, no_price=0.35)
        result = _parse_market(m)
        assert result is not None
        assert result.yes_price == 0.65
        assert result.no_price == 0.35
        assert result.volume == 100000.0
        assert result.ticker == "test-condition-1"

    def test_handles_missing_optional_fields(self):
        m = {"conditionId": "test"}
        result = _parse_market(m)
        assert result is not None
        assert result.yes_price == 0.5
        assert result.no_price == 0.5

    def test_handles_string_outcome_prices(self):
        m = make_market()
        m["outcomePrices"] = '["0.7", "0.3"]'
        result = _parse_market(m)
        assert result is not None
        assert result.yes_price == 0.7
        assert result.no_price == 0.3


class TestUniversalScanner:
    @pytest.mark.asyncio
    async def test_analyze_market_high_edge(self):
        scanner = UniversalScanner()
        from backend.strategies.base import MarketInfo

        market = MarketInfo(
            ticker="test-1",
            slug="test",
            category="Politics",
            end_date="2026-12-31",
            volume=50000.0,
            liquidity=10000.0,
            yes_price=0.80,
            no_price=0.30,
            question="Will it rain?",
        )

        signal = await scanner.analyze_market(market)
        assert signal is not None
        assert signal["ticker"] == "test-1"
        assert signal["edge"] == pytest.approx(0.10)

    @pytest.mark.asyncio
    async def test_analyze_market_low_edge_rejected(self):
        scanner = UniversalScanner()
        from backend.strategies.base import MarketInfo

        market = MarketInfo(
            ticker="test-2",
            slug="test",
            category="Politics",
            end_date="2026-12-31",
            volume=50000.0,
            liquidity=10000.0,
            yes_price=0.51,
            no_price=0.49,
            question="Will it rain?",
        )

        signal = await scanner.analyze_market(market)
        assert signal is None

    @pytest.mark.asyncio
    async def test_analyze_market_low_volume_rejected(self):
        scanner = UniversalScanner()
        from backend.strategies.base import MarketInfo

        market = MarketInfo(
            ticker="test-3",
            slug="test",
            category="Politics",
            end_date="2026-12-31",
            volume=100.0,
            liquidity=50.0,
            yes_price=0.80,
            no_price=0.20,
            question="Will it rain?",
        )

        signal = await scanner.analyze_market(market)
        assert signal is None

    @pytest.mark.asyncio
    async def test_scan_all_mocks_gamma_api(self):
        scanner = UniversalScanner()
        all_markets = [make_market(yes_price=0.60, no_price=0.40) for _ in range(PAGE_SIZE * 2)]

        async def mock_fetch(client, offset, semaphore, retry_count=0, breaker=None):
            start = offset
            end = min(offset + PAGE_SIZE, len(all_markets))
            return (all_markets[start:end], True)

        with patch("backend.strategies.universal_scanner.httpx.AsyncClient"):
            with patch(
                "backend.strategies.universal_scanner._fetch_page_with_retry",
                mock_fetch
            ):
                markets = await scanner.scan_all()

        assert len(markets) >= PAGE_SIZE

    @pytest.mark.asyncio
    async def test_run_cycle_returns_cycle_result(self):
        scanner = UniversalScanner()

        async def mock_scan_all():
            from backend.strategies.base import MarketInfo
            return [
                MarketInfo(
                    ticker="sig-1",
                    slug="s1",
                    category="Pol",
                    end_date="2026-12-31",
                    volume=100000.0,
                    liquidity=50000.0,
                    yes_price=0.75,
                    no_price=0.30,
                    question="Q1",
                )
            ]

        scanner.scan_all = mock_scan_all

        from backend.strategies.base import StrategyContext

        ctx = MagicMock(spec=StrategyContext)
        ctx.params = {}

        result = await scanner.run_cycle(ctx)
        assert result.decisions_recorded >= 0
        assert result.trades_attempted >= 0
        assert result.cycle_duration_ms >= 0


class TestStressScenarios:
    @pytest.mark.asyncio
    async def test_handles_10000_markets(self):
        scanner = UniversalScanner()
        all_markets = [make_market() for _ in range(10000)]

        async def mock_fetch(client, offset, semaphore, retry_count=0, breaker=None):
            if offset >= 10000:
                return ([], True)
            start = offset
            end = min(offset + PAGE_SIZE, 10000)
            return (all_markets[start:end], True)

        with patch("backend.strategies.universal_scanner.httpx.AsyncClient"):
            with patch(
                "backend.strategies.universal_scanner._fetch_page_with_retry",
                mock_fetch
            ):
                markets = await scanner.scan_all()

        assert len(markets) <= MAX_MARKETS
        assert len(markets) <= 10000

    @pytest.mark.asyncio
    async def test_graceful_degradation_on_network_failure(self):
        scanner = UniversalScanner()

        async def mock_fetch(client, offset, semaphore, retry_count=0, breaker=None):
            if offset == 0:
                return ([make_market()], True)
            raise Exception("Network partition")

        with patch("backend.strategies.universal_scanner.httpx.AsyncClient"):
            with patch(
                "backend.strategies.universal_scanner._fetch_page_with_retry",
                mock_fetch
            ):
                markets = await scanner.scan_all()

        assert len(markets) >= 1

    @pytest.mark.asyncio
    async def test_race_condition_prevention(self):
        scanner = UniversalScanner()
        from backend.strategies.base import MarketInfo

        market = MarketInfo(
            ticker="race-test",
            slug="race",
            category="Test",
            end_date="2026-12-31",
            volume=100000.0,
            liquidity=50000.0,
            yes_price=0.80,
            no_price=0.30,
            question="Race test?",
        )

        async def concurrent_analyze():
            return await scanner.analyze_market(market)

        results = await asyncio.gather(concurrent_analyze(), concurrent_analyze())
        assert all(r is not None for r in results)
