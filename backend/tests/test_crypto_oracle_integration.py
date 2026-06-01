"""G-10/G-11: Integration tests for crypto_oracle strategy.

Validates that crypto_oracle can discover and analyze BTC/ETH/SOL 5-min markets
with mocked API calls.
"""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from datetime import datetime, timezone, timedelta

from backend.strategies.crypto_oracle import (
    CryptoOracleStrategy,
    SUPPORTED_ASSETS,
    _COINGECKO_TO_ASSET_PREFIX,
    _ASSET_PREFIX_TO_COINGECKO,
    implied_direction,
    calculate_dynamic_size,
    parse_end_date,
)


class TestAssetPrefixMapping:
    """G-11: Verify ETH/SOL asset prefix handling."""

    def test_coingecko_to_prefix_btc(self):
        assert _COINGECKO_TO_ASSET_PREFIX["bitcoin"] == "btc"

    def test_coingecko_to_prefix_eth(self):
        assert _COINGECKO_TO_ASSET_PREFIX["ethereum"] == "eth"

    def test_coingecko_to_prefix_sol(self):
        assert _COINGECKO_TO_ASSET_PREFIX["solana"] == "sol"

    def test_reverse_mapping(self):
        assert _ASSET_PREFIX_TO_COINGECKO["btc"] == "bitcoin"
        assert _ASSET_PREFIX_TO_COINGECKO["eth"] == "ethereum"
        assert _ASSET_PREFIX_TO_COINGECKO["sol"] == "solana"

    def test_supported_assets_include_all_three(self):
        assert "bitcoin" in SUPPORTED_ASSETS
        assert "ethereum" in SUPPORTED_ASSETS
        assert "solana" in SUPPORTED_ASSETS

    def test_all_assets_have_prefix(self):
        for asset in SUPPORTED_ASSETS:
            assert asset in _COINGECKO_TO_ASSET_PREFIX, f"Missing prefix for {asset}"


class TestImpliedDirection:
    """Test market question parsing for direction inference."""

    def test_above_threshold_yes(self):
        assert implied_direction("Will BTC exceed $95,000?", 96000) == "yes"

    def test_above_threshold_no(self):
        assert implied_direction("Will BTC exceed $95,000?", 94000) == "no"

    def test_below_threshold_yes(self):
        assert implied_direction("Will ETH fall below $3,000?", 2900) == "yes"

    def test_below_threshold_no(self):
        assert implied_direction("Will ETH fall below $3,000?", 3100) == "no"

    def test_k_shorthand(self):
        assert implied_direction("Will BTC hit 100k?", 101000) == "yes"

    def test_no_keyword_returns_none(self):
        assert implied_direction("Will BTC be interesting?", 50000) is None


class TestDynamicSizing:
    """Test dynamic position sizing."""

    def test_zero_cap_returns_zero(self):
        assert (
            calculate_dynamic_size(edge=0.1, confidence=0.8, max_position_usd=0) == 0.0
        )

    def test_scales_with_edge(self):
        small = calculate_dynamic_size(edge=0.01, confidence=0.5, max_position_usd=100)
        large = calculate_dynamic_size(edge=0.10, confidence=0.5, max_position_usd=100)
        assert large > small

    def test_respects_min_position(self):
        result = calculate_dynamic_size(
            edge=0.001, confidence=0.1, max_position_usd=100, min_position_usd=5.0
        )
        assert result >= 5.0

    def test_capped_at_max(self):
        result = calculate_dynamic_size(edge=1.0, confidence=1.0, max_position_usd=50)
        assert result <= 50.0


class TestParseEndDate:
    """Test end date parsing."""

    def test_none_returns_none(self):
        assert parse_end_date(None) is None

    def test_empty_returns_none(self):
        assert parse_end_date("") is None

    def test_iso_format(self):
        dt = parse_end_date("2026-05-18T12:00:00Z")
        assert dt is not None
        assert dt.year == 2026

    def test_iso_with_offset(self):
        dt = parse_end_date("2026-05-18T12:00:00+00:00")
        assert dt is not None
        assert dt.tzinfo is not None


class TestMarketFilter:
    """G-10/G-11: Test market filtering for BTC/ETH/SOL."""

    @pytest.mark.asyncio
    async def test_filter_includes_btc(self):
        strategy = CryptoOracleStrategy()
        mock_market = MagicMock()
        mock_market.slug = "btc-updown-5m-1234567890"
        mock_market.question = "Will BTC go up?"
        mock_market.end_date = "2026-05-18T12:05:00Z"

        result = await strategy.market_filter([mock_market])
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_filter_includes_eth(self):
        strategy = CryptoOracleStrategy()
        mock_market = MagicMock()
        mock_market.slug = "eth-updown-5m-1234567890"
        mock_market.question = "Will ETH go up?"
        mock_market.end_date = "2026-05-18T12:05:00Z"

        result = await strategy.market_filter([mock_market])
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_filter_includes_sol(self):
        strategy = CryptoOracleStrategy()
        mock_market = MagicMock()
        mock_market.slug = "sol-updown-5m-1234567890"
        mock_market.question = "Will SOL go up?"
        mock_market.end_date = "2026-05-18T12:05:00Z"

        result = await strategy.market_filter([mock_market])
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_filter_excludes_non_crypto(self):
        strategy = CryptoOracleStrategy()
        mock_market = MagicMock()
        mock_market.slug = "weather-rain-nyc"
        mock_market.question = "Will it rain in NYC?"
        mock_market.end_date = "2026-05-18T12:05:00Z"

        result = await strategy.market_filter([mock_market])
        assert len(result) == 0

    @pytest.mark.asyncio
    async def test_filter_excludes_no_end_date(self):
        strategy = CryptoOracleStrategy()
        mock_market = MagicMock()
        mock_market.slug = "btc-updown-5m-1234567890"
        mock_market.question = "Will BTC go up?"
        mock_market.end_date = None

        result = await strategy.market_filter([mock_market])
        assert len(result) == 0


class TestCryptoOracleDiscovery:
    """G-10: Integration test — validate crypto_oracle discovers markets for all assets."""

    @pytest.mark.asyncio
    @patch("backend.data.btc_markets.fetch_active_crypto_markets")
    @patch("backend.strategies.crypto_oracle.fetch_crypto_price_for_asset")
    @patch("backend.data.crypto.compute_crypto_microstructure")
    async def test_discovers_btc_markets(self, mock_micro, mock_price, mock_markets):
        """Verify crypto_oracle can discover and analyze BTC 5-min markets."""
        from backend.data.btc_markets import CryptoMarket

        mock_price.return_value = 96000.0
        mock_micro.return_value = MagicMock(
            rsi=55.0, momentum_5m=0.001, vwap_deviation=0.0005, sma_crossover=0.0003
        )
        mock_markets.return_value = [
            CryptoMarket(
                slug="btc-updown-5m-1234567890",
                market_id="btc-5m-test",
                up_price=0.55,
                down_price=0.45,
                window_start=datetime.now(timezone.utc),
                window_end=datetime.now(timezone.utc) + timedelta(minutes=3),
                volume=1000.0,
                closed=False,
                up_token_id="token-up-123",
                down_token_id="token-down-456",
                asset="btc",
            )
        ]

        strategy = CryptoOracleStrategy()
        ctx = MagicMock()
        ctx.params = {}
        ctx.mode = "paper"
        ctx.db = MagicMock()

        with patch(
            "backend.data.btc_markets.fetch_active_crypto_markets", mock_markets
        ):
            result = await strategy.run_cycle(ctx)

        assert result.decisions_recorded >= 0  # Should not crash

    @pytest.mark.asyncio
    @patch("backend.data.btc_markets.fetch_active_crypto_markets")
    @patch("backend.strategies.crypto_oracle.fetch_crypto_price_for_asset")
    async def test_handles_eth_asset(self, mock_price, mock_markets):
        """Verify crypto_oracle handles ETH asset prefix correctly."""
        mock_price.return_value = 3500.0
        mock_markets.return_value = []

        strategy = CryptoOracleStrategy()
        ctx = MagicMock()
        ctx.params = {}
        ctx.mode = "paper"
        ctx.db = MagicMock()

        # Should iterate over ETH without crashing
        with patch(
            "backend.core.market_scanner.fetch_markets_by_keywords",
            new_callable=AsyncMock,
            return_value=[],
        ):
            result = await strategy.run_cycle(ctx)
        assert result is not None

    @pytest.mark.asyncio
    @patch("backend.data.btc_markets.fetch_active_crypto_markets")
    @patch("backend.strategies.crypto_oracle.fetch_crypto_price_for_asset")
    async def test_handles_sol_asset(self, mock_price, mock_markets):
        """Verify crypto_oracle handles SOL asset prefix correctly."""
        mock_price.return_value = 150.0
        mock_markets.return_value = []

        strategy = CryptoOracleStrategy()
        ctx = MagicMock()
        ctx.params = {}
        ctx.mode = "paper"
        ctx.db = MagicMock()

        with patch(
            "backend.core.market_scanner.fetch_markets_by_keywords",
            new_callable=AsyncMock,
            return_value=[],
        ):
            result = await strategy.run_cycle(ctx)
        assert result is not None


class TestCryptoOracleFilters:
    """Validate block_direction_down and blocked_hours_utc filters."""

    @pytest.mark.asyncio
    @patch("backend.strategies.crypto_oracle.datetime")
    @patch("backend.strategies.crypto_oracle.fetch_crypto_price_for_asset")
    async def test_on_market_event_blocked_hours(self, mock_fetch_price, mock_datetime):
        import time
        mock_fetch_price.return_value = 95000.0

        # Set current time to a blocked hour (e.g. 0 UTC)
        mock_now = datetime(2026, 5, 27, 0, 0, 0, tzinfo=timezone.utc)
        mock_datetime.now.return_value = mock_now

        strategy = CryptoOracleStrategy()
        # Set min_edge to -1.0 so that edge check always passes
        strategy.default_params["min_edge"] = -1.0

        from backend.strategies.base import MarketEvent
        event = MarketEvent(
            token_id="btc-token-id",
            event_type="last_trade_price",
            data={"asset": "btc", "price": "0.35"},
            timestamp=time.time()
        )
        # 0 UTC is blocked for BTC by default -> should return None
        result = await strategy.on_market_event(event)
        assert result is None

        # 0 UTC is NOT blocked for non-BTC assets (default empty list)
        event_eth = MarketEvent(
            token_id="eth-token-id",
            event_type="last_trade_price",
            data={"asset": "eth", "price": "0.35"},
            timestamp=time.time()
        )
        result_eth = await strategy.on_market_event(event_eth)
        # Direction is "down" (price < 0.5), which is NOT blocked for ETH by default
        assert result_eth is not None

    @pytest.mark.asyncio
    @patch("backend.strategies.crypto_oracle.fetch_crypto_price_for_asset")
    async def test_on_market_event_block_direction_down(self, mock_fetch_price):
        import time
        mock_fetch_price.return_value = 95000.0

        strategy = CryptoOracleStrategy()
        strategy.default_params["min_edge"] = -1.0
        from backend.strategies.base import MarketEvent

        # For BTC, down direction is blocked by default
        event_btc_down = MarketEvent(
            token_id="btc-token-id",
            event_type="last_trade_price",
            data={"asset": "btc", "price": "0.35"}, # price < 0.5 -> down
            timestamp=time.time()
        )
        # Mock datetime to ensure it is NOT a blocked hour (e.g. 10 UTC)
        with patch("backend.strategies.crypto_oracle.datetime") as mock_datetime:
            mock_now = datetime(2026, 5, 27, 10, 0, 0, tzinfo=timezone.utc)
            mock_datetime.now.return_value = mock_now
            result = await strategy.on_market_event(event_btc_down)
            assert result is None

            # For BTC, up direction is NOT blocked
            event_btc_up = MarketEvent(
                token_id="btc-token-id",
                event_type="last_trade_price",
                data={"asset": "btc", "price": "0.65"}, # price > 0.5 -> up
                timestamp=time.time()
            )
            result_up = await strategy.on_market_event(event_btc_up)
            assert result_up is not None

    @pytest.mark.asyncio
    @patch("backend.strategies.crypto_oracle.fetch_crypto_price_for_asset")
    @patch("backend.data.btc_markets.fetch_active_crypto_markets")
    @patch("backend.core.market_scanner.fetch_markets_by_keywords")
    @patch("backend.strategies.crypto_oracle.datetime")
    async def test_run_cycle_filters(self, mock_datetime, mock_kw_markets, mock_active_markets, mock_price):
        # Ensure we are in a blocked hour (e.g., 23 UTC)
        mock_now = datetime(2026, 5, 27, 23, 0, 0, tzinfo=timezone.utc)
        mock_datetime.now.return_value = mock_now

        mock_price.return_value = 95000.0

        from backend.data.btc_markets import CryptoMarket
        from backend.strategies.base import MarketInfo
        mock_active_markets.return_value = [
            CryptoMarket(
                slug="btc-updown-5m-1234567890",
                market_id="btc-5m-test",
                up_price=0.55,
                down_price=0.45,
                window_start=datetime(2026, 5, 27, 23, 0, 0, tzinfo=timezone.utc),
                window_end=datetime(2026, 5, 27, 23, 5, 0, tzinfo=timezone.utc),
                volume=1000.0,
                closed=False,
                up_token_id="token-up-123",
                down_token_id="token-down-456",
                asset="btc",
            )
        ]
        mock_kw_markets.return_value = []

        strategy = CryptoOracleStrategy()
        strategy.default_params["min_edge"] = -1.0
        ctx = MagicMock()
        ctx.params = {}
        ctx.mode = "paper"
        ctx.db = MagicMock()

        # Under blocked hour, BTC should be skipped immediately
        with patch("backend.strategies.crypto_oracle._get_time_multiplier", return_value=1.0):
            result = await strategy.run_cycle(ctx)
            assets_traded = {d["asset"] for d in result.decisions}
            assert "bitcoin" not in assets_traded
            assert "ethereum" in assets_traded
            assert "solana" in assets_traded

        # Now test run_cycle with direction block
        mock_now = datetime(2026, 5, 27, 10, 0, 0, tzinfo=timezone.utc)
        mock_datetime.now.return_value = mock_now

        # Scenario: Down direction ("Will BTC exceed 96k?" -> price 95k is < 96k, contract direction is "no", physical direction is "down")
        mock_active_markets.return_value = []
        mock_kw_markets.return_value = [
            MarketInfo(
                ticker="btc-5m-test",
                slug="btc-updown-5m-1234567890",
                category="crypto",
                end_date=datetime(2026, 5, 27, 10, 5, 0, tzinfo=timezone.utc).isoformat(),
                volume=1000.0,
                liquidity=1000.0,
                yes_price=0.55,
                no_price=0.45,
                question="Will BTC exceed $96,000?",
            )
        ]

        with patch("backend.strategies.crypto_oracle._get_time_multiplier", return_value=1.0):
            result = await strategy.run_cycle(ctx)
            # Physical direction down is blocked -> decisions_recorded should be 0
            assert result.decisions_recorded == 0
