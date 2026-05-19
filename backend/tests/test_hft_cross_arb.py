"""Tests for HFT cross-exchange atomic arbitrage executor."""
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.strategies.hft_cross_arb import (
    HFTCrossArbExecutor,
    _kelly_size,
    _calculate_fees,
)
from backend.strategies.cross_market_arb_enhanced import ArbOpportunityEnhanced


def _make_opp(
    price_a=0.60,
    price_b=0.35,
    cheaper="polymarket",
    market_a="poly_token_123",
    market_b="KXBT-24MAY19",
    net_profit=0.03,
    raw_spread=0.05,
) -> ArbOpportunityEnhanced:
    return ArbOpportunityEnhanced(
        event_id="evt1",
        kind="cross_platform",
        platform_a="polymarket",
        platform_b="kalshi",
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
        details={"cheaper": cheaper},
    )


# ---------------------------------------------------------------------------
# Helpers: mock circuit breaker that passes through
# ---------------------------------------------------------------------------

class _PassThroughBreaker:
    """Mock circuit breaker that always allows calls through."""
    def __init__(self):
        self.state = "CLOSED"

    async def call(self, func, *args, **kwargs):
        return await func(*args, **kwargs)

    async def record_success(self):
        pass

    async def record_failure(self):
        pass

    def reset(self):
        pass


@pytest.fixture(autouse=True)
def _patch_breakers():
    """Replace module-level circuit breakers with pass-through mocks."""
    import backend.strategies.hft_cross_arb as mod
    orig_poly = mod._poly_breaker
    orig_kalshi = mod._kalshi_breaker
    mod._poly_breaker = _PassThroughBreaker()
    mod._kalshi_breaker = _PassThroughBreaker()
    yield
    mod._poly_breaker = orig_poly
    mod._kalshi_breaker = orig_kalshi


# ---------------------------------------------------------------------------
# Unit tests: Kelly sizing
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
        size = _kelly_size(edge=0.5, bankroll=100000.0, max_size=200.0, kelly_fraction=0.25)
        assert size == 200.0

    def test_zero_bankroll_returns_zero(self):
        assert _kelly_size(edge=0.05, bankroll=0.0) == 0.0


# ---------------------------------------------------------------------------
# Unit tests: fee calculation
# ---------------------------------------------------------------------------

class TestFeeCalculation:
    def test_basic_fees(self):
        poly_fee, kalshi_fee, slippage = _calculate_fees(
            poly_price=0.60, kalshi_price=0.35,
            poly_size=100.0, kalshi_size=100.0,
            slippage_bps=5.0,
        )
        assert poly_fee == pytest.approx(0.60)  # 0.60 * 100 * 0.01
        assert kalshi_fee == pytest.approx(0.35)  # 0.35 * 100 * 0.01
        assert slippage > 0

    def test_custom_fee_rates(self):
        poly_fee, kalshi_fee, _ = _calculate_fees(
            poly_price=0.50, kalshi_price=0.50,
            poly_size=100.0, kalshi_size=100.0,
            poly_fee_pct=0.02, kalshi_fee_pct=0.07,
            slippage_bps=0.0,
        )
        assert poly_fee == pytest.approx(1.0)  # 0.50 * 100 * 0.02
        assert kalshi_fee == pytest.approx(3.5)  # 0.50 * 100 * 0.07


# ---------------------------------------------------------------------------
# Unit tests: size calculation
# ---------------------------------------------------------------------------

class TestCalculateSizes:
    def test_valid_opp(self):
        executor = HFTCrossArbExecutor(paper_mode=True, max_exposure=200.0)
        opp = _make_opp()
        poly_size, kalshi_size = executor.calculate_sizes(opp, bankroll=1000.0)
        assert poly_size > 0
        assert kalshi_size > 0

    def test_zero_edge_skips(self):
        executor = HFTCrossArbExecutor(paper_mode=True, min_net_edge=0.05)
        opp = _make_opp(net_profit=0.001)
        poly_size, kalshi_size = executor.calculate_sizes(opp, bankroll=1000.0)
        assert poly_size == 0.0
        assert kalshi_size == 0.0


# ---------------------------------------------------------------------------
# Atomic execution: both legs succeed
# ---------------------------------------------------------------------------

class TestAtomicExecution:
    @pytest.mark.asyncio
    async def test_both_legs_fill(self):
        mock_clob = AsyncMock()
        mock_clob.place_limit_order = AsyncMock(
            return_value=MagicMock(order_id="poly_order_1", success=True)
        )
        mock_clob.cancel_order = AsyncMock(return_value=True)

        mock_kalshi = AsyncMock()
        mock_kalshi.place_order = AsyncMock(
            return_value={"order": {"order_id": "kalshi_order_1"}}
        )

        executor = HFTCrossArbExecutor(
            clob=mock_clob,
            kalshi_client=mock_kalshi,
            max_exposure=200.0,
            paper_mode=True,
        )
        opp = _make_opp()

        result = await executor.execute_arb(opp, bankroll=1000.0)
        assert result.status == "filled"
        assert result.poly_order_id == "poly_order_1"
        assert result.kalshi_order_id == "kalshi_order_1"
        assert result.net_profit > 0
        assert result.latency_ms > 0

    @pytest.mark.asyncio
    async def test_poly_fails_kalshi_cancelled(self):
        mock_clob = AsyncMock()
        mock_clob.place_limit_order = AsyncMock(side_effect=Exception("poly API down"))
        mock_clob.cancel_order = AsyncMock(return_value=True)

        mock_kalshi = AsyncMock()
        mock_kalshi.place_order = AsyncMock(
            return_value={"order": {"order_id": "kalshi_order_2"}}
        )
        mock_kalshi.cancel_order = AsyncMock(return_value=True)

        executor = HFTCrossArbExecutor(
            clob=mock_clob,
            kalshi_client=mock_kalshi,
            max_exposure=200.0,
            paper_mode=True,
        )
        opp = _make_opp()

        result = await executor.execute_arb(opp, bankroll=1000.0)
        assert result.status == "partial"
        assert result.error is not None

    @pytest.mark.asyncio
    async def test_kalshi_fails_poly_cancelled(self):
        mock_clob = AsyncMock()
        mock_clob.place_limit_order = AsyncMock(
            return_value=MagicMock(order_id="poly_order_3", success=True)
        )
        mock_clob.cancel_order = AsyncMock(return_value=True)

        mock_kalshi = AsyncMock()
        mock_kalshi.place_order = AsyncMock(side_effect=Exception("kalshi rate limited"))
        mock_kalshi.cancel_order = AsyncMock(return_value=True)

        executor = HFTCrossArbExecutor(
            clob=mock_clob,
            kalshi_client=mock_kalshi,
            max_exposure=200.0,
            paper_mode=True,
        )
        opp = _make_opp()

        result = await executor.execute_arb(opp, bankroll=1000.0)
        assert result.status == "partial"
        assert result.error is not None
        mock_clob.cancel_order.assert_called_once()

    @pytest.mark.asyncio
    async def test_both_fail(self):
        mock_clob = AsyncMock()
        mock_clob.place_limit_order = AsyncMock(side_effect=Exception("poly down"))

        mock_kalshi = AsyncMock()
        mock_kalshi.place_order = AsyncMock(side_effect=Exception("kalshi down"))

        executor = HFTCrossArbExecutor(
            clob=mock_clob,
            kalshi_client=mock_kalshi,
            paper_mode=True,
        )
        opp = _make_opp()

        result = await executor.execute_arb(opp, bankroll=1000.0)
        assert result.status == "failed"

    @pytest.mark.asyncio
    async def test_skips_when_no_edge(self):
        executor = HFTCrossArbExecutor(paper_mode=True, min_net_edge=0.10)
        opp = _make_opp(net_profit=0.001)
        result = await executor.execute_arb(opp, bankroll=1000.0)
        assert result.status == "skipped"


# ---------------------------------------------------------------------------
# Batch execution
# ---------------------------------------------------------------------------

class TestBatchExecution:
    @pytest.mark.asyncio
    async def test_batch_returns_results(self):
        mock_clob = AsyncMock()
        mock_clob.place_limit_order = AsyncMock(
            return_value=MagicMock(order_id="poly_o", success=True)
        )
        mock_kalshi = AsyncMock()
        mock_kalshi.place_order = AsyncMock(
            return_value={"order": {"order_id": "kalshi_o"}}
        )

        executor = HFTCrossArbExecutor(
            clob=mock_clob,
            kalshi_client=mock_kalshi,
            paper_mode=True,
        )
        opps = [_make_opp(price_a=0.60 - i * 0.01) for i in range(3)]
        results = await executor.execute_batch(opps, bankroll=5000.0)
        assert len(results) == 3


# ---------------------------------------------------------------------------
# History tracking
# ---------------------------------------------------------------------------

class TestHistory:
    @pytest.mark.asyncio
    async def test_history_recorded(self):
        mock_clob = AsyncMock()
        mock_clob.place_limit_order = AsyncMock(
            return_value=MagicMock(order_id="h1", success=True)
        )
        mock_kalshi = AsyncMock()
        mock_kalshi.place_order = AsyncMock(
            return_value={"order": {"order_id": "h2"}}
        )

        executor = HFTCrossArbExecutor(
            clob=mock_clob,
            kalshi_client=mock_kalshi,
            paper_mode=True,
        )
        opp = _make_opp()
        await executor.execute_arb(opp, bankroll=1000.0)

        history = executor.get_history(limit=10)
        assert len(history) == 1
        assert history[0]["arb_id"]
        assert history[0]["status"] == "filled"


# ---------------------------------------------------------------------------
# Detection passthrough
# ---------------------------------------------------------------------------

class TestDetection:
    def test_detect_arb_delegates(self):
        executor = HFTCrossArbExecutor(paper_mode=True)
        # Empty lists should return empty
        assert executor.detect_arb([], []) == []

    def test_scan_all_delegates(self):
        executor = HFTCrossArbExecutor(paper_mode=True)
        assert executor.scan_all([], []) == []
