"""Tests for unified PM arbitrage strategy."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.strategies.unified_pm_arb import UnifiedPMArb, _kelly_size, _normalize_market_info, _normalize_market_info
from backend.strategies.cross_market_arb_enhanced import ArbOpportunityEnhanced


def _make_opp(
    price_a=0.60,
    price_b=0.35,
    platform_a="polymarket",
    platform_b="kalshi",
    market_a="poly_token_123",
    market_b="KXBT-24MAY19",
    net_profit=0.03,
    raw_spread=0.05,
    kind="cross_platform_arb",
) -> ArbOpportunityEnhanced:
    return ArbOpportunityEnhanced(
        event_id="evt1",
        kind=kind,
        platform_a=platform_a,
        platform_b=platform_b,
        market_a_id=market_a,
        market_b_id=market_b,
        price_a=price_a,
        price_b=price_b,
        raw_spread=raw_spread,
        fees=0.02,
        slippage_cost=0.001,
        execution_risk=0.3,
        net_profit=net_profit,
        net_profit_pct=net_profit / min(price_a, price_b),
        confidence=0.8,
        details={
            "cheaper": platform_a,
            "token_id_a": market_a,
            "token_id_b": market_b,
        },
    )


# ---------------------------------------------------------------------------
# Unit tests: Kelly sizing (must be identical to hft_cross_arb._kelly_size)
# ---------------------------------------------------------------------------


class TestKellySize:
    def test_positive_edge(self):
        size = _kelly_size(edge=0.05, bankroll=1000.0, kelly_fraction=0.25)
        assert size > 0
        assert size == pytest.approx(12.5)  # 0.05 * 0.25 * 1000

    def test_zero_edge_returns_zero(self):
        assert _kelly_size(edge=0.0) == 0.0

    def test_negative_edge_returns_zero(self):
        assert _kelly_size(edge=-0.01) == 0.0

    def test_capped_at_max_size(self):
        size = _kelly_size(
            edge=0.5, bankroll=100000.0, max_size=200.0, kelly_fraction=0.25
        )
        assert size == 200.0

    def test_zero_bankroll_returns_zero(self):
        assert _kelly_size(edge=0.05, bankroll=0.0) == 0.0


# ---------------------------------------------------------------------------
# Unit tests: MarketInfo normalization
# ---------------------------------------------------------------------------


class TestNormalizeMarketInfo:
    def test_normalizes_basic_fields(self):
        market = MagicMock()
        market.title = "Will BTC hit 100k?"
        market.market_id = "abc123"
        market.yes_price = 0.65
        market.no_price = 0.35
        market.volume_24h = 50000
        market.open_interest = 10000
        market.raw = {"clobTokenIds": ["token_a", "token_b"]}

        result = _normalize_market_info(market, "polymarket")

        assert result["question"] == "Will BTC hit 100k?"
        assert result["event_id"] == "abc123"
        assert result["yes_price"] == pytest.approx(0.65)
        assert result["no_price"] == pytest.approx(0.35)
        assert result["platform"] == "polymarket"
        assert result["fee_pct"] == 0.02
        assert result["clobTokenIds"] == ["token_a", "token_b"]

    def test_handles_none_prices(self):
        market = MagicMock()
        market.title = "Test"
        market.market_id = "x"
        market.yes_price = None
        market.no_price = None
        market.volume_24h = 0
        market.open_interest = 0
        market.raw = {}

        result = _normalize_market_info(market, "kalshi")
        assert result["yes_price"] is None
        assert result["no_price"] is None
        assert result["fee_pct"] == 0.07  # Kalshi fee

    def test_handles_string_raw(self):
        market = MagicMock()
        market.title = "Test"
        market.market_id = "y"
        market.yes_price = 0.50
        market.no_price = 0.50
        market.volume_24h = 0
        market.open_interest = 0
        market.raw = '{"clobTokenIds": ["tok1"]}'

        result = _normalize_market_info(market, "sxbet")
        assert result["clobTokenIds"] == ["tok1"]


# ---------------------------------------------------------------------------
# Unit tests: strategy sizing
# ---------------------------------------------------------------------------


class TestStrategySizing:
    def test_calculate_size_valid(self):
        strategy = UnifiedPMArb()
        opp = _make_opp(net_profit=0.05)
        size = strategy._calculate_size(opp, bankroll=1000.0)
        assert size > 0

    def test_calculate_size_zero_edge(self):
        strategy = UnifiedPMArb()
        opp = _make_opp(net_profit=0.001)
        # Default min_net_edge is 0.02, but _calculate_size uses kelly
        # which produces tiny size for 0.001 edge
        size = strategy._calculate_size(opp, bankroll=100.0)
        # Should be 0 or very small (below MIN_ORDER_USDC=5)
        assert size == 0.0 or size < 5.0


# ---------------------------------------------------------------------------
# Unit tests: circuit breaker management
# ---------------------------------------------------------------------------


class TestCircuitBreakers:
    def test_breaker_cached_per_venue(self):
        strategy = UnifiedPMArb()
        b1 = strategy._get_breaker("polymarket")
        b2 = strategy._get_breaker("polymarket")
        assert b1 is b2

    def test_different_venues_different_breakers(self):
        strategy = UnifiedPMArb()
        b1 = strategy._get_breaker("polymarket")
        b2 = strategy._get_breaker("kalshi")
        assert b1 is not b2


# ---------------------------------------------------------------------------
# Integration: atomic execution
# ---------------------------------------------------------------------------


class TestAtomicExecution:
    @pytest.mark.asyncio
    async def test_both_legs_fill(self):
        """Both providers succeed -> status=filled."""
        mock_result = NormalizedOrderResult(
            venue_order_id="order_1",
            client_order_id="arb-a",
            status=OrderStatus.FILLED,
            filled_size=Decimal("10.00"),
            filled_avg_price=Decimal("0.60"),
            remaining_size=Decimal("0"),
            fees_paid=Decimal("0.06"),
        )

        mock_provider_a = AsyncMock()
        mock_provider_a.place_order = AsyncMock(return_value=mock_result)
        mock_provider_a.cancel_order = AsyncMock(return_value=True)

        mock_provider_b = AsyncMock()
        mock_provider_b.place_order = AsyncMock(return_value=mock_result)
        mock_provider_b.cancel_order = AsyncMock(return_value=True)

        strategy = UnifiedPMArb()

        # Mock ctx
        ctx = MagicMock()
        ctx.get_market_provider = MagicMock(
            side_effect=lambda v: mock_provider_a if v == "polymarket" else mock_provider_b
        )
        ctx.bankroll = 1000.0

        opp = _make_opp()
        result = await strategy._execute_arb(ctx, opp, bankroll=1000.0)
        assert result["status"] == "filled"
        assert result["profit"] > 0

    @pytest.mark.asyncio
    async def test_one_leg_fails_other_cancelled(self):
        """One provider fails -> emergency cancel on the other."""
        mock_success = NormalizedOrderResult(
            venue_order_id="order_ok",
            client_order_id="arb-a",
            status=OrderStatus.FILLED,
            filled_size=Decimal("10.00"),
            filled_avg_price=Decimal("0.60"),
            remaining_size=Decimal("0"),
            fees_paid=Decimal("0.06"),
        )

        mock_provider_a = AsyncMock()
        mock_provider_a.place_order = AsyncMock(return_value=mock_success)
        mock_provider_a.cancel_order = AsyncMock(return_value=True)

        mock_provider_b = AsyncMock()
        mock_provider_b.place_order = AsyncMock(side_effect=Exception("API down"))
        mock_provider_b.cancel_order = AsyncMock(return_value=True)

        strategy = UnifiedPMArb()

        ctx = MagicMock()
        ctx.get_market_provider = MagicMock(
            side_effect=lambda v: mock_provider_a if v == "polymarket" else mock_provider_b
        )
        ctx.bankroll = 1000.0

        opp = _make_opp()
        result = await strategy._execute_arb(ctx, opp, bankroll=1000.0)
        assert result["status"] == "partial"
        # Emergency cancel should have been called
        mock_provider_a.cancel_order.assert_called_once()

    @pytest.mark.asyncio
    async def test_both_fail(self):
        """Both providers fail -> status=failed."""
        mock_provider_a = AsyncMock()
        mock_provider_a.place_order = AsyncMock(side_effect=Exception("down"))

        mock_provider_b = AsyncMock()
        mock_provider_b.place_order = AsyncMock(side_effect=Exception("down"))

        strategy = UnifiedPMArb()

        ctx = MagicMock()
        ctx.get_market_provider = MagicMock(
            side_effect=lambda v: mock_provider_a if v == "polymarket" else mock_provider_b
        )
        ctx.bankroll = 1000.0

        opp = _make_opp()
        result = await strategy._execute_arb(ctx, opp, bankroll=1000.0)
        assert result["status"] == "failed"

    @pytest.mark.asyncio
    async def test_skips_when_no_edge(self):
        """Tiny edge -> size below minimum -> skipped."""
        strategy = UnifiedPMArb()
        ctx = MagicMock()
        opp = _make_opp(net_profit=0.001)
        result = await strategy._execute_arb(ctx, opp, bankroll=100.0)
        assert result["status"] == "skipped"


# ---------------------------------------------------------------------------
# Integration: cycle with mocked providers
# ---------------------------------------------------------------------------


class TestRunCycle:
    @pytest.mark.asyncio
    async def test_cycle_no_markets(self):
        """No providers -> errors."""
        strategy = UnifiedPMArb()
        ctx = MagicMock()
        ctx.get_market_provider = MagicMock(return_value=None)
        ctx.bankroll = 1000.0

        result = await strategy.run_cycle(ctx)
        assert result.trades_placed == 0
        assert len(result.errors) > 0

    @pytest.mark.asyncio
    async def test_cycle_no_opportunities(self):
        """Markets but no arb -> zero trades."""
        mock_provider = AsyncMock()
        mock_provider.search_markets = AsyncMock(return_value=[])

        strategy = UnifiedPMArb()
        ctx = MagicMock()
        ctx.get_market_provider = MagicMock(return_value=mock_provider)
        ctx.bankroll = 1000.0

        result = await strategy.run_cycle(ctx)
        assert result.trades_placed == 0


# ---------------------------------------------------------------------------
# History tracking
# ---------------------------------------------------------------------------


class TestHistory:
    def test_empty_history(self):
        strategy = UnifiedPMArb()
        assert strategy.get_history() == []

    def test_history_after_execution(self):
        strategy = UnifiedPMArb()
        strategy._history.append({"event_id": "x", "status": "filled"})
        assert len(strategy.get_history()) == 1


# ---------------------------------------------------------------------------
# Strategy metadata
# ---------------------------------------------------------------------------


class TestStrategyMeta:
    def test_name(self):
        assert UnifiedPMArb.name == "unified_arb"

    def test_category(self):
        assert UnifiedPMArb.category == "arb"

    def test_default_params(self):
        params = UnifiedPMArb.default_params
        assert "max_exposure" in params
        assert "kelly_fraction" in params
        assert params["kelly_fraction"] == 0.25


# Import needed for atomic execution tests
from decimal import Decimal
from backend.markets.order_types import NormalizedOrderResult, OrderStatus
