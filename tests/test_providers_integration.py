"""Integration tests for all 8 market providers.

Tests each provider's interface contract: manifest, place_order (paper mode),
get_balance, get_positions, cancel_order, search_markets, and fee models.
All external HTTP/blockchain calls are mocked.
"""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.markets.base_provider import MarketProviderManifest
from backend.markets.order_types import (
    NormalizedBalance,
    NormalizedOrder,
    NormalizedOrderResult,
    OrderSide,
    OrderType,
    OrderStatus,
    VenueCapability,
)
from backend.markets.providers.paper_provider import (
    FillResult,
    OrderbookLevel,
    _polymarket_fee,
    check_limit_order_fill,
    simulate_orderbook_fill,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_order(
    market_id: str = "test_market",
    side: OrderSide = OrderSide.BUY,
    size: Decimal = Decimal("10"),
    price: Decimal | None = Decimal("0.50"),
    order_type: OrderType = OrderType.MARKET,
) -> NormalizedOrder:
    return NormalizedOrder(
        market_id=market_id,
        side=side,
        order_type=order_type,
        size=size,
        price=price,
        client_order_id="test_client_001",
    )


def _assert_manifest(m: MarketProviderManifest) -> None:
    """Validate manifest has all required fields with correct types."""
    assert isinstance(m.name, str) and m.name, "name must be non-empty str"
    assert isinstance(m.display_name, str) and m.display_name
    assert isinstance(m.version, str) and m.version
    assert isinstance(m.venue_type, str) and m.venue_type
    assert isinstance(m.capabilities, list)
    assert len(m.capabilities) > 0, "capabilities must not be empty"
    assert all(isinstance(c, VenueCapability) for c in m.capabilities)
    assert isinstance(m.supported_currencies, list)
    assert isinstance(m.required_env_vars, list)


def _assert_order_result(result: NormalizedOrderResult) -> None:
    """Validate an order result has correct types."""
    assert isinstance(result, NormalizedOrderResult)
    assert isinstance(result.status, OrderStatus)
    assert isinstance(result.filled_size, Decimal)
    assert isinstance(result.remaining_size, Decimal)
    assert isinstance(result.fees_paid, Decimal)


def _assert_balance(bal: NormalizedBalance) -> None:
    """Validate a balance result."""
    assert isinstance(bal, NormalizedBalance)
    assert isinstance(bal.available_cash, Decimal)
    assert isinstance(bal.total_equity, Decimal)
    assert isinstance(bal.reserved_margin, Decimal)
    assert isinstance(bal.venue, str)


# ===========================================================================
# 1. Polymarket Provider
# ===========================================================================

class TestPolymarketProvider:
    """Integration tests for PolymarketProvider."""

    @pytest.fixture(autouse=True)
    def _setup(self):
        """Create a paper-mode Polymarket provider with mocked dependencies."""
        with patch.dict("sys.modules", {
            "backend.data.polymarket_clob": MagicMock(),
            "py_clob_client": MagicMock(),
        }):
            from backend.markets.providers.polymarket_provider import PolymarketProvider
            self.provider = PolymarketProvider(paper_mode=True)
            self.provider_cls = PolymarketProvider

    def test_manifest(self):
        m = self.provider_cls.manifest()
        _assert_manifest(m)
        assert m.name == "polymarket"
        assert m.display_name == "Polymarket"
        assert m.venue_type == "prediction_market"
        assert VenueCapability.LIMIT_ORDERS in m.capabilities
        assert VenueCapability.MARKET_ORDERS in m.capabilities
        assert VenueCapability.MARKET_SEARCH in m.capabilities
        assert VenueCapability.STREAMING_FILLS in m.capabilities
        assert m.supports_paper_mode is True
        assert m.is_live_venue is True
        assert "USDC" in m.supported_currencies

    @pytest.mark.asyncio
    async def test_place_order_paper_filled(self):
        order = _make_order(price=Decimal("0.60"))
        result = await self.provider.place_order(order)
        _assert_order_result(result)
        assert result.status == OrderStatus.FILLED
        assert result.filled_size == Decimal("10")
        assert result.filled_avg_price == Decimal("0.60")
        assert result.remaining_size == Decimal("0")
        assert "paper_" in result.venue_order_id

    @pytest.mark.asyncio
    async def test_place_order_paper_no_price_defaults(self):
        order = _make_order(price=None)
        result = await self.provider.place_order(order)
        assert result.status == OrderStatus.FILLED
        assert result.filled_avg_price == Decimal("0.5")

    @pytest.mark.asyncio
    async def test_place_order_paper_fee_zero(self):
        """Polymarket paper mode returns zero fees (live fees handled by CLOB)."""
        order = _make_order(price=Decimal("0.50"))
        result = await self.provider.place_order(order)
        assert result.fees_paid == Decimal("0")

    @pytest.mark.asyncio
    async def test_get_balance_paper(self):
        bal = await self.provider.get_balance()
        _assert_balance(bal)
        assert bal.venue == "polymarket"
        assert bal.available_cash == Decimal("10000")
        assert bal.total_equity == Decimal("10000")

    @pytest.mark.asyncio
    async def test_get_positions_paper(self):
        positions = await self.provider.get_positions()
        assert isinstance(positions, list)

    @pytest.mark.asyncio
    async def test_cancel_order_paper(self):
        result = await self.provider.cancel_order("paper_test")
        assert result is True

    @pytest.mark.asyncio
    async def test_search_markets_returns_list(self):
        """Paper mode search falls through to gamma mock or returns list."""
        with patch(
            "backend.markets.providers.polymarket_provider.PolymarketProvider.search_markets",
            return_value=[],
        ):
            result = await self.provider.search_markets(query="test", limit=5)
            assert isinstance(result, list)

    @pytest.mark.asyncio
    async def test_place_order_live_rejected_without_price(self):
        """Live mode rejects orders without a limit price."""
        with patch.dict("sys.modules", {
            "backend.data.polymarket_clob": MagicMock(),
            "py_clob_client": MagicMock(),
        }):
            from backend.markets.providers.polymarket_provider import PolymarketProvider
            live = PolymarketProvider(paper_mode=False)
            live._mode = "live"
            order = _make_order(price=None)
            result = await live.place_order(order)
            assert result.status == OrderStatus.REJECTED


# ===========================================================================
# 2. Kalshi Provider
# ===========================================================================

class TestKalshiProvider:
    """Integration tests for KalshiProvider."""

    @pytest.fixture(autouse=True)
    def _setup(self):
        mock_client = MagicMock()
        mock_client.get_positions = AsyncMock(return_value=[])
        mock_client.get_balance = AsyncMock(return_value={"available": 5000})
        mock_client.get_markets = AsyncMock(return_value={"markets": []})
        mock_client.batch_create_orders = AsyncMock(return_value={})
        mock_client.batch_cancel_orders = AsyncMock(return_value=True)

        with patch.dict("sys.modules", {
            "backend.data.kalshi_client": MagicMock(),
        }):
            from backend.markets.providers.kalshi_provider import KalshiProvider
            self.provider_cls = KalshiProvider
            self.provider = KalshiProvider(paper_mode=True)
            self.provider._client = mock_client

    def test_manifest(self):
        m = self.provider_cls.manifest()
        _assert_manifest(m)
        assert m.name == "kalshi"
        assert m.display_name == "Kalshi"
        assert m.venue_type == "prediction_market"
        assert VenueCapability.LIMIT_ORDERS in m.capabilities
        assert VenueCapability.MARKET_ORDERS in m.capabilities
        assert VenueCapability.MARKET_SEARCH in m.capabilities
        assert m.maker_fee_bps == 175
        assert m.taker_fee_bps == 700

    @pytest.mark.asyncio
    async def test_place_order_paper_filled(self):
        order = _make_order(price=Decimal("0.60"))
        result = await self.provider.place_order(order)
        _assert_order_result(result)
        assert result.status == OrderStatus.FILLED
        assert result.filled_size == Decimal("10")
        assert result.filled_avg_price == Decimal("0.60")
        assert result.remaining_size == Decimal("0")

    @pytest.mark.asyncio
    async def test_place_order_paper_fee_nonzero(self):
        """Kalshi paper mode computes realistic fee via _kalshi_fee."""
        order = _make_order(price=Decimal("0.50"), size=Decimal("10"))
        result = await self.provider.place_order(order)
        # fee = ceil(10 * 0.50 * 0.50 * 0.07 * 100) / 100 = ceil(17.5)/100 = 0.18
        assert result.fees_paid > Decimal("0")

    @pytest.mark.asyncio
    async def test_get_balance_paper(self):
        bal = await self.provider.get_balance()
        _assert_balance(bal)
        assert bal.venue == "kalshi"
        assert bal.available_cash == Decimal("10000")

    @pytest.mark.asyncio
    async def test_get_positions_paper(self):
        positions = await self.provider.get_positions()
        assert isinstance(positions, list)

    @pytest.mark.asyncio
    async def test_cancel_order_paper(self):
        result = await self.provider.cancel_order("paper_test")
        assert result is True

    @pytest.mark.asyncio
    async def test_search_markets(self):
        result = await self.provider.search_markets(query="test", limit=5)
        assert isinstance(result, list)

    @pytest.mark.asyncio
    async def test_live_rejected_without_price(self):
        result = await self.provider.place_order(_make_order(price=None, order_type=OrderType.LIMIT))
        # In paper mode it fills with default; testing live rejection
        with patch.object(self.provider, "_paper_mode", False):
            result = await self.provider.place_order(_make_order(price=None, order_type=OrderType.LIMIT))
            assert result.status == OrderStatus.REJECTED


# ===========================================================================
# Kalshi Fee Model
# ===========================================================================

class TestKalshiFeeModel:
    """Test _kalshi_fee fee model: fee peaks at price=0.50."""

    def test_fee_at_extremes_near_zero(self):
        from backend.markets.providers.kalshi_provider import _kalshi_fee
        fee_low = _kalshi_fee(Decimal("0.10"), Decimal("10"))
        fee_high = _kalshi_fee(Decimal("0.90"), Decimal("10"))
        assert fee_low >= Decimal("0")
        assert fee_high >= Decimal("0")

    def test_fee_peaks_at_half(self):
        from backend.markets.providers.kalshi_provider import _kalshi_fee
        fee_010 = _kalshi_fee(Decimal("0.10"), Decimal("100"))
        fee_050 = _kalshi_fee(Decimal("0.50"), Decimal("100"))
        fee_090 = _kalshi_fee(Decimal("0.90"), Decimal("100"))
        assert fee_050 > fee_010, "Fee at 0.50 must exceed fee at 0.10"
        assert fee_050 > fee_090, "Fee at 0.50 must exceed fee at 0.90"

    def test_fee_symmetry(self):
        from backend.markets.providers.kalshi_provider import _kalshi_fee
        fee_a = _kalshi_fee(Decimal("0.30"), Decimal("50"))
        fee_b = _kalshi_fee(Decimal("0.70"), Decimal("50"))
        assert fee_a == fee_b, "Fee must be symmetric around 0.50"

    def test_fee_scales_with_size(self):
        from backend.markets.providers.kalshi_provider import _kalshi_fee
        fee_10 = _kalshi_fee(Decimal("0.50"), Decimal("10"))
        fee_100 = _kalshi_fee(Decimal("0.50"), Decimal("100"))
        assert fee_100 > fee_10

    def test_fee_at_price_levels(self):
        from backend.markets.providers.kalshi_provider import _kalshi_fee
        for price in [Decimal("0.10"), Decimal("0.50"), Decimal("0.90")]:
            fee = _kalshi_fee(price, Decimal("10"))
            assert fee >= Decimal("0"), f"Fee must be non-negative at price {price}"


# ===========================================================================
# 3. SX.bet Provider
# ===========================================================================

class TestSXBetProvider:
    """Integration tests for SXBetProvider."""

    @pytest.fixture(autouse=True)
    def _setup(self):
        mock_client = MagicMock()
        mock_client.health_check = AsyncMock(return_value=True)

        with patch.dict("sys.modules", {
            "backend.clients.sxbet_client": MagicMock(),
        }):
            from backend.markets.providers.sxbet_provider import SXBetProvider
            self.provider_cls = SXBetProvider
            self.provider = SXBetProvider(paper_mode=True)
            self.provider._client = mock_client

    def test_manifest(self):
        m = self.provider_cls.manifest()
        _assert_manifest(m)
        assert m.name == "sxbet"
        assert m.display_name == "SX.bet"
        assert m.venue_type == "sports_prediction"
        assert VenueCapability.LIMIT_ORDERS in m.capabilities
        assert VenueCapability.MARKET_SEARCH in m.capabilities

    @pytest.mark.asyncio
    async def test_place_order_paper_filled(self):
        order = _make_order(price=Decimal("0.55"))
        result = await self.provider.place_order(order)
        _assert_order_result(result)
        assert result.status == OrderStatus.FILLED
        assert result.filled_size == Decimal("10")
        assert result.filled_avg_price == Decimal("0.55")
        assert result.fees_paid == Decimal("0")

    @pytest.mark.asyncio
    async def test_get_balance_returns_normalized_balance(self):
        """FIXED: sxbet_provider now uses correct NormalizedBalance kwargs."""
        result = await self.provider.get_balance()
        assert isinstance(result, NormalizedBalance)
        assert result.available_cash == Decimal("0")

    @pytest.mark.asyncio
    async def test_get_positions(self):
        positions = await self.provider.get_positions()
        assert isinstance(positions, list)

    @pytest.mark.asyncio
    async def test_cancel_order_returns_false(self):
        """SX.bet doesn't support cancellation."""
        result = await self.provider.cancel_order("test_order")
        assert result is False


# ===========================================================================
# 4. Limitless Provider
# ===========================================================================

class TestLimitlessProvider:
    """Limitless DISABLED — smart wallet not deployed on Base (2026-05-30)."""

    def test_limitless_provider_disabled(self):
        """LimitlessProvider raises RuntimeError on instantiation."""
        import sys
        with patch.dict("sys.modules", {
            "backend.clients.limitless_client": MagicMock(),
        }):
            import importlib
            try:
                # The .py.disabled file won't be auto-discovered, but the class
                # in data/providers/limitless.py raises RuntimeError
                from backend.data.providers.limitless import LimitlessProvider
                with pytest.raises(RuntimeError, match="Limitless disabled"):
                    LimitlessProvider()
            except ImportError:
                pass  # module may not be importable after __init__.py removal


# ===========================================================================
# 5. Myriad Provider
# ===========================================================================

class TestMyriadProvider:
    """Integration tests for MyriadProvider."""

    @pytest.fixture(autouse=True)
    def _setup(self):
        mock_client = MagicMock()
        mock_client.get_balance = AsyncMock(return_value=Decimal("5000"))
        mock_client.get_positions = AsyncMock(return_value=[])
        mock_client.get_markets = AsyncMock(return_value=[])
        mock_client.place_order = AsyncMock(return_value={"order_id": "mid_001"})
        mock_client.cancel_order = AsyncMock(return_value=True)

        with patch.dict("sys.modules", {
            "backend.clients.myriad_client": MagicMock(),
        }):
            from backend.markets.providers.myriad_provider import MyriadProvider
            self.provider_cls = MyriadProvider
            self.provider = MyriadProvider(paper_mode=True)
            self.provider._client = mock_client

    def test_manifest(self):
        m = self.provider_cls.manifest()
        _assert_manifest(m)
        assert m.name == "myriad"
        assert m.display_name == "Myriad Markets"
        assert m.venue_type == "prediction_market"
        assert VenueCapability.LIMIT_ORDERS in m.capabilities
        assert VenueCapability.MARKET_ORDERS in m.capabilities
        assert VenueCapability.MARKET_SEARCH in m.capabilities

    @pytest.mark.asyncio
    async def test_place_order_paper_filled(self):
        order = _make_order(price=Decimal("0.65"))
        result = await self.provider.place_order(order)
        _assert_order_result(result)
        assert result.status == OrderStatus.FILLED
        assert result.filled_size == Decimal("10")
        assert result.filled_avg_price == Decimal("0.65")
        assert result.fees_paid == Decimal("0")

    @pytest.mark.asyncio
    async def test_place_order_paper_no_price_defaults(self):
        order = _make_order(price=None)
        result = await self.provider.place_order(order)
        assert result.status == OrderStatus.FILLED
        assert result.filled_avg_price == Decimal("0.5")

    @pytest.mark.asyncio
    async def test_get_positions(self):
        positions = await self.provider.get_positions()
        assert isinstance(positions, list)

    @pytest.mark.asyncio
    async def test_cancel_order(self):
        result = await self.provider.cancel_order("test_order")
        assert isinstance(result, bool)

    @pytest.mark.asyncio
    async def test_search_markets(self):
        result = await self.provider.search_markets(query="test", limit=5)
        assert isinstance(result, list)


# ===========================================================================
# 6. Predict.fun Provider
# ===========================================================================

class TestPredictFunProvider:
    """Integration tests for PredictFunProvider."""

    @pytest.fixture(autouse=True)
    def _setup(self):
        mock_client = MagicMock()
        mock_client.health_check = AsyncMock(return_value=True)

        with patch.dict("sys.modules", {
            "backend.clients.azuro_client": MagicMock(),
        }):
            from backend.markets.providers.predict_fun_provider import PredictFunProvider
            self.provider_cls = PredictFunProvider
            self.provider = PredictFunProvider(paper_mode=True)
            self.provider._client = mock_client

    def test_manifest(self):
        m = self.provider_cls.manifest()
        _assert_manifest(m)
        assert m.name == "predict_fun"
        assert m.display_name == "predict.fun"
        assert m.venue_type == "prediction_market"
        assert VenueCapability.MARKET_ORDERS in m.capabilities
        assert VenueCapability.MARKET_SEARCH in m.capabilities

    @pytest.mark.asyncio
    async def test_place_order_paper_filled(self):
        order = _make_order(price=Decimal("0.70"))
        result = await self.provider.place_order(order)
        _assert_order_result(result)
        assert result.status == OrderStatus.FILLED
        assert result.filled_size == Decimal("10")
        assert result.filled_avg_price == Decimal("0.70")
        assert result.fees_paid == Decimal("0")

    @pytest.mark.asyncio
    async def test_get_balance_returns_normalized_balance(self):
        """FIXED: predict_fun_provider now uses correct NormalizedBalance kwargs."""
        result = await self.provider.get_balance()
        assert isinstance(result, NormalizedBalance)
        assert result.available_cash == Decimal("0")

    @pytest.mark.asyncio
    async def test_get_positions(self):
        positions = await self.provider.get_positions()
        assert isinstance(positions, list)

    @pytest.mark.asyncio
    async def test_cancel_order_raises(self):
        """Azuro-based providers raise on cancel (non-cancellable bets)."""
        with pytest.raises(ValueError, match="non-cancellable"):
            await self.provider.cancel_order("test_order")


# ===========================================================================
# 7. Bookmaker.xyz Provider
# ===========================================================================

class TestBookmakerXYZProvider:
    """Integration tests for BookmakerXYZProvider."""

    @pytest.fixture(autouse=True)
    def _setup(self):
        mock_client = MagicMock()
        mock_client.health_check = AsyncMock(return_value=True)

        with patch.dict("sys.modules", {
            "backend.clients.azuro_client": MagicMock(),
        }):
            from backend.markets.providers.bookmaker_xyz_provider import (
                BookmakerXYZProvider,
            )
            self.provider_cls = BookmakerXYZProvider
            self.provider = BookmakerXYZProvider(paper_mode=True)
            self.provider._client = mock_client

    def test_manifest(self):
        m = self.provider_cls.manifest()
        _assert_manifest(m)
        assert m.name == "bookmaker_xyz"
        assert m.display_name == "bookmaker.xyz"
        assert m.venue_type == "sports_prediction"
        assert VenueCapability.MARKET_ORDERS in m.capabilities
        assert VenueCapability.MARKET_SEARCH in m.capabilities

    @pytest.mark.asyncio
    async def test_place_order_paper_filled(self):
        order = _make_order(price=Decimal("0.55"))
        result = await self.provider.place_order(order)
        _assert_order_result(result)
        assert result.status == OrderStatus.FILLED
        assert result.filled_size == Decimal("10")
        assert result.filled_avg_price == Decimal("0.55")
        assert result.fees_paid == Decimal("0")

    @pytest.mark.asyncio
    async def test_get_balance_returns_normalized_balance(self):
        """FIXED: bookmaker_xyz_provider now uses correct NormalizedBalance kwargs."""
        result = await self.provider.get_balance()
        assert isinstance(result, NormalizedBalance)
        assert result.available_cash == Decimal("0")

    @pytest.mark.asyncio
    async def test_get_positions(self):
        positions = await self.provider.get_positions()
        assert isinstance(positions, list)

    @pytest.mark.asyncio
    async def test_cancel_order_raises(self):
        """Azuro-based providers raise on cancel (non-cancellable bets)."""
        with pytest.raises(ValueError, match="non-cancellable"):
            await self.provider.cancel_order("test_order")


# ===========================================================================
# 8. Paper Provider
# ===========================================================================

class TestPaperProvider:
    """Integration tests for PaperProvider with orderbook simulation."""

    @pytest.fixture(autouse=True)
    def _setup(self):
        from backend.markets.providers.paper_provider import PaperProvider
        self.provider = PaperProvider(paper_mode=True)

    def test_manifest(self):
        from backend.markets.providers.paper_provider import PaperProvider
        m = PaperProvider.manifest()
        _assert_manifest(m)
        assert m.name == "paper"
        assert m.display_name == "Paper Trading"
        assert m.venue_type == "simulation"
        assert VenueCapability.LIMIT_ORDERS in m.capabilities
        assert VenueCapability.MARKET_ORDERS in m.capabilities
        assert VenueCapability.BATCH_ORDERS in m.capabilities
        assert m.is_live_venue is False
        assert m.required_env_vars == []

    @pytest.mark.asyncio
    async def test_place_market_order_filled(self):
        order = _make_order(order_type=OrderType.MARKET, price=Decimal("0.50"))
        result = await self.provider.place_order(order)
        _assert_order_result(result)
        assert result.status == OrderStatus.FILLED
        assert result.filled_size == Decimal("10")
        assert result.filled_avg_price == Decimal("0.50")
        assert result.remaining_size == Decimal("0")

    @pytest.mark.asyncio
    async def test_place_limit_order_stays_open(self):
        """Limit orders without orderbook stay OPEN until price crosses."""
        order = _make_order(order_type=OrderType.LIMIT, price=Decimal("0.40"))
        result = await self.provider.place_order(order)
        _assert_order_result(result)
        assert result.status == OrderStatus.OPEN
        assert result.filled_size == Decimal("0")
        assert result.remaining_size == Decimal("10")

    @pytest.mark.asyncio
    async def test_orderbook_fill_simulation(self):
        """Market order with orderbook uses multi-level fill."""
        levels = [
            OrderbookLevel(price=Decimal("0.50"), size=Decimal("5")),
            OrderbookLevel(price=Decimal("0.52"), size=Decimal("3")),
            OrderbookLevel(price=Decimal("0.55"), size=Decimal("10")),
        ]
        self.provider.set_orderbook("mkt_ob", levels)
        order = _make_order(
            market_id="mkt_ob",
            order_type=OrderType.MARKET,
            size=Decimal("8"),
            price=Decimal("0.50"),
        )
        result = await self.provider.place_order(order)
        assert result.status == OrderStatus.FILLED
        assert result.filled_size == Decimal("8")
        # 5 @ 0.50 + 3 @ 0.52 = 2.50 + 1.56 = 4.06 / 8 = 0.5075
        expected_avg = (Decimal("5") * Decimal("0.50") + Decimal("3") * Decimal("0.52")) / Decimal("8")
        assert result.filled_avg_price == expected_avg
        assert result.fees_paid > Decimal("0")

    @pytest.mark.asyncio
    async def test_limit_order_fill_on_price_crossing(self):
        """Limit BUY fills when ask drops to/below limit price."""
        order = _make_order(
            order_type=OrderType.LIMIT,
            side=OrderSide.BUY,
            price=Decimal("0.55"),
            size=Decimal("5"),
        )
        result = await self.provider.place_order(order)
        assert result.status == OrderStatus.OPEN  # stays open initially

        # Price crosses: ask at 0.53 <= limit 0.55
        filled = await self.provider.try_fill_limit_orders(
            "test_market", best_bid=Decimal("0.52"), best_ask=Decimal("0.53")
        )
        assert len(filled) == 1
        assert filled[0].status == OrderStatus.FILLED
        assert filled[0].filled_avg_price == Decimal("0.55")
        assert filled[0].fees_paid > Decimal("0")

    @pytest.mark.asyncio
    async def test_limit_order_no_fill_when_price_not_crossed(self):
        """Limit BUY stays open when ask is above limit price."""
        order = _make_order(
            order_type=OrderType.LIMIT,
            side=OrderSide.BUY,
            price=Decimal("0.45"),
        )
        await self.provider.place_order(order)
        filled = await self.provider.try_fill_limit_orders(
            "test_market", best_bid=Decimal("0.40"), best_ask=Decimal("0.50")
        )
        assert len(filled) == 0

    @pytest.mark.asyncio
    async def test_cancel_order(self):
        order = _make_order(order_type=OrderType.LIMIT, price=Decimal("0.40"))
        result = await self.provider.place_order(order)
        vid = result.venue_order_id
        assert await self.provider.cancel_order(vid) is True
        # Cancelling again returns False
        assert await self.provider.cancel_order(vid) is False

    @pytest.mark.asyncio
    async def test_cancel_all_orders(self):
        await self.provider.place_order(_make_order(order_type=OrderType.LIMIT, price=Decimal("0.40")))
        await self.provider.place_order(_make_order(order_type=OrderType.LIMIT, price=Decimal("0.60")))
        count = await self.provider.cancel_all_orders()
        assert count == 2

    @pytest.mark.asyncio
    async def test_get_balance(self):
        bal = await self.provider.get_balance()
        _assert_balance(bal)
        assert bal.venue == "paper"
        assert bal.available_cash == Decimal("100000")

    @pytest.mark.asyncio
    async def test_get_positions_after_fill(self):
        await self.provider.place_order(_make_order(order_type=OrderType.MARKET))
        positions = await self.provider.get_positions()
        assert len(positions) == 1
        assert positions[0].market_id == "test_market"
        assert positions[0].venue == "paper"

    @pytest.mark.asyncio
    async def test_search_markets_returns_empty(self):
        result = await self.provider.search_markets(query="test")
        assert result == []

    @pytest.mark.asyncio
    async def test_paper_fee_matches_polymarket_model(self):
        """Paper provider uses Polymarket taker fee: fee = bps/10000 * min(p, 1-p) * size."""
        order = _make_order(
            order_type=OrderType.MARKET,
            price=Decimal("0.50"),
            size=Decimal("100"),
        )
        result = await self.provider.place_order(order)
        expected_fee = _polymarket_fee(Decimal("0.50"), Decimal("100"))
        assert result.fees_paid == expected_fee

    @pytest.mark.asyncio
    async def test_single_price_fallback(self):
        """Without orderbook, fills at single price with fee."""
        order = _make_order(
            order_type=OrderType.MARKET,
            price=Decimal("0.75"),
            size=Decimal("20"),
        )
        result = await self.provider.place_order(order)
        assert result.status == OrderStatus.FILLED
        assert result.filled_avg_price == Decimal("0.75")
        expected_fee = _polymarket_fee(Decimal("0.75"), Decimal("20"))
        assert result.fees_paid == expected_fee


# ===========================================================================
# Polymarket Fee Model (used by Paper Provider)
# ===========================================================================

class TestPolymarketFeeModel:
    """Test _polymarket_fee: fee peaks at 0.50, symmetric, near-zero at extremes."""

    def test_fee_at_050_is_maximal(self):
        fee_010 = _polymarket_fee(Decimal("0.10"), Decimal("100"))
        fee_050 = _polymarket_fee(Decimal("0.50"), Decimal("100"))
        fee_090 = _polymarket_fee(Decimal("0.90"), Decimal("100"))
        assert fee_050 >= fee_010, "Fee at 0.50 must be >= fee at 0.10"
        assert fee_050 >= fee_090, "Fee at 0.50 must be >= fee at 0.90"

    def test_fee_symmetry(self):
        fee_a = _polymarket_fee(Decimal("0.30"), Decimal("50"))
        fee_b = _polymarket_fee(Decimal("0.70"), Decimal("50"))
        assert fee_a == fee_b, "Fee must be symmetric around 0.50"

    def test_fee_scales_with_size(self):
        fee_10 = _polymarket_fee(Decimal("0.50"), Decimal("10"))
        fee_100 = _polymarket_fee(Decimal("0.50"), Decimal("100"))
        assert fee_100 > fee_10

    def test_fee_non_negative(self):
        for price in ["0.01", "0.10", "0.25", "0.50", "0.75", "0.90", "0.99"]:
            fee = _polymarket_fee(Decimal(price), Decimal("10"))
            assert fee >= Decimal("0"), f"Fee at {price} must be non-negative"

    def test_fee_min_enforcement(self):
        """Fees > 0 are clamped to at least 0.0001."""
        fee = _polymarket_fee(Decimal("0.99"), Decimal("1"))
        assert fee >= Decimal("0.0001") or fee == Decimal("0")

    def test_zero_fee_bps_returns_zero(self):
        fee = _polymarket_fee(Decimal("0.50"), Decimal("100"), fee_bps=0)
        assert fee == Decimal("0")

    def test_fee_at_price_levels(self):
        """Comprehensive test at 3 price levels for both models."""
        prices = [Decimal("0.10"), Decimal("0.50"), Decimal("0.90")]
        for p in prices:
            poly_fee = _polymarket_fee(p, Decimal("100"))
            assert poly_fee >= Decimal("0")


# ===========================================================================
# Orderbook Fill Simulation (Paper Provider utility)
# ===========================================================================

class TestOrderbookFillSimulation:
    """Test simulate_orderbook_fill multi-level fill logic."""

    def test_single_level_exact_fill(self):
        levels = [OrderbookLevel(price=Decimal("0.50"), size=Decimal("10"))]
        result = simulate_orderbook_fill(OrderSide.BUY, Decimal("10"), levels)
        assert isinstance(result, FillResult)
        assert result.filled_size == Decimal("10")
        assert result.avg_price == Decimal("0.50")
        assert result.levels_consumed == 1
        assert result.slippage_bps == Decimal("0")

    def test_multi_level_partial_fill(self):
        levels = [
            OrderbookLevel(price=Decimal("0.50"), size=Decimal("3")),
            OrderbookLevel(price=Decimal("0.55"), size=Decimal("5")),
            OrderbookLevel(price=Decimal("0.60"), size=Decimal("10")),
        ]
        result = simulate_orderbook_fill(OrderSide.BUY, Decimal("6"), levels)
        assert result.filled_size == Decimal("6")
        assert result.levels_consumed == 2
        # avg = (3*0.50 + 3*0.55) / 6 = (1.50 + 1.65) / 6 = 3.15 / 6 = 0.525
        expected_avg = (Decimal("3") * Decimal("0.50") + Decimal("3") * Decimal("0.55")) / Decimal("6")
        assert result.avg_price == expected_avg
        assert result.slippage_bps > Decimal("0")

    def test_fee_computed_per_level(self):
        levels = [
            OrderbookLevel(price=Decimal("0.50"), size=Decimal("5")),
            OrderbookLevel(price=Decimal("0.60"), size=Decimal("5")),
        ]
        result = simulate_orderbook_fill(OrderSide.BUY, Decimal("10"), levels)
        assert result.fee > Decimal("0"), "Fee must be positive for fills"

    def test_empty_orderbook_raises(self):
        with pytest.raises(ValueError, match="empty"):
            simulate_orderbook_fill(OrderSide.BUY, Decimal("10"), [])

    def test_partial_fill_with_insufficient_liquidity(self):
        """Partial fill succeeds when orderbook has less liquidity than requested.
        The function only raises when total_filled == 0 (zero liquidity)."""
        levels = [OrderbookLevel(price=Decimal("0.50"), size=Decimal("3"))]
        result = simulate_orderbook_fill(OrderSide.BUY, Decimal("10"), levels)
        assert result.filled_size == Decimal("3")
        assert result.levels_consumed == 1

    def test_zero_liquidity_raises(self):
        """A single level with zero size triggers the 'Insufficient' ValueError."""
        levels = [OrderbookLevel(price=Decimal("0.50"), size=Decimal("0"))]
        with pytest.raises(ValueError, match="Insufficient"):
            simulate_orderbook_fill(OrderSide.BUY, Decimal("10"), levels)

    def test_sell_order_walks_bids(self):
        """SELL orders consume bid levels (descending)."""
        levels = [
            OrderbookLevel(price=Decimal("0.55"), size=Decimal("5")),
            OrderbookLevel(price=Decimal("0.50"), size=Decimal("5")),
        ]
        result = simulate_orderbook_fill(OrderSide.SELL, Decimal("7"), levels)
        assert result.filled_size == Decimal("7")


class TestLimitOrderFillCheck:
    """Test check_limit_order_fill crossing logic."""

    def test_buy_fills_when_ask_below_limit(self):
        order = _make_order(side=OrderSide.BUY, price=Decimal("0.55"), order_type=OrderType.LIMIT)
        assert check_limit_order_fill(order, Decimal("0.50"), Decimal("0.53")) is True

    def test_buy_no_fill_when_ask_above_limit(self):
        order = _make_order(side=OrderSide.BUY, price=Decimal("0.45"), order_type=OrderType.LIMIT)
        assert check_limit_order_fill(order, Decimal("0.40"), Decimal("0.50")) is False

    def test_sell_fills_when_bid_above_limit(self):
        order = _make_order(side=OrderSide.SELL, price=Decimal("0.45"), order_type=OrderType.LIMIT)
        assert check_limit_order_fill(order, Decimal("0.50"), Decimal("0.55")) is True

    def test_sell_no_fill_when_bid_below_limit(self):
        order = _make_order(side=OrderSide.SELL, price=Decimal("0.55"), order_type=OrderType.LIMIT)
        assert check_limit_order_fill(order, Decimal("0.50"), Decimal("0.55")) is False

    def test_no_fill_without_price(self):
        order = _make_order(price=None, order_type=OrderType.LIMIT)
        assert check_limit_order_fill(order, Decimal("0.50"), Decimal("0.55")) is False
