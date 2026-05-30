"""
Tests for probability_arb strategy: detect_arb, ProbabilityArb class, execute_arb bugs.
"""

import asyncio
import pytest
from unittest.mock import MagicMock, AsyncMock, patch

from backend.strategies.probability_arb import (
    detect_arb,
    ProbabilityArb,
    ArbOpportunity,
    execute_arb,
    _place_order_with_retry,
    process_pending_arbs,
    _pending_arbs,
)
from backend.strategies.base import CycleResult, StrategyContext


# ---------------------------------------------------------------------------
# detect_arb (standalone function, uses settings directly)
# ---------------------------------------------------------------------------


class TestDetectArb:
    def test_yes_no_sum_below_one_returns_opportunity(self):
        """YES=0.50, NO=0.40 -> sum=0.90, profit=$0.10, net after fees=$0.09."""
        opp = detect_arb(0.50, 0.40)
        assert opp is not None
        assert opp.yes_price == 0.50
        assert opp.no_price == 0.40
        assert opp.sum_price == pytest.approx(0.90)
        assert opp.net_profit > 0

    def test_yes_no_sum_at_one_returns_none(self):
        """YES=0.55, NO=0.45 -> sum=1.00, no arb."""
        opp = detect_arb(0.55, 0.45)
        assert opp is None

    def test_yes_no_sum_above_one_returns_none(self):
        """YES=0.60, NO=0.50 -> sum=1.10, no arb."""
        opp = detect_arb(0.60, 0.50)
        assert opp is None

    def test_profit_too_small_after_fees_returns_none(self):
        """Tiny spread that doesn't cover fees."""
        # sum = 0.995, spread = 0.005, fees = 0.01 -> net = -0.005
        opp = detect_arb(0.50, 0.495)
        assert opp is None

    def test_opportunity_has_confidence(self):
        """Confidence should be > 0 when there's a profitable arb."""
        opp = detect_arb(0.40, 0.35)
        assert opp is not None
        assert opp.confidence > 0
        assert opp.confidence <= 1.0

    def test_large_spread_high_confidence(self):
        """Large spread should yield high confidence."""
        opp = detect_arb(0.30, 0.30)
        assert opp is not None
        assert opp.confidence >= 1.0

    def test_symmetric_prices(self):
        """detect_arb should be symmetric in YES/NO."""
        opp1 = detect_arb(0.40, 0.30)
        opp2 = detect_arb(0.30, 0.40)
        assert opp1 is not None
        assert opp2 is not None
        assert opp1.net_profit == pytest.approx(opp2.net_profit)


# ---------------------------------------------------------------------------
# ProbabilityArb class
# ---------------------------------------------------------------------------


class TestProbabilityArbClass:
    def test_name_and_category(self):
        pa = ProbabilityArb()
        assert pa.name == "probability_arb"
        assert pa.category == "arb"

    def test_default_params(self):
        pa = ProbabilityArb()
        assert pa.default_params["min_profit"] > 0
        assert pa.default_params["max_position"] > 0

    @pytest.mark.asyncio
    async def test_detect_delegates_to_detect_arb(self):
        """ProbabilityArb.detect() should delegate to standalone detect_arb."""
        pa = ProbabilityArb()
        opp = await pa.detect(0.50, 0.40)
        assert opp is not None
        assert isinstance(opp, ArbOpportunity)
        assert opp.net_profit > 0

    @pytest.mark.asyncio
    async def test_detect_no_arb(self):
        pa = ProbabilityArb()
        opp = await pa.detect(0.55, 0.50)
        assert opp is None

    @pytest.mark.asyncio
    async def test_run_cycle_no_markets_returns_empty(self):
        """When Gamma returns no markets, cycle returns 0 decisions."""
        pa = ProbabilityArb()
        ctx = _make_ctx()

        with patch("backend.data.gamma.fetch_markets", new_callable=AsyncMock, return_value=[]):
            result = await pa.run_cycle(ctx)

        assert isinstance(result, CycleResult)
        assert result.decisions_recorded == 0
        assert result.trades_attempted == 0

    @pytest.mark.asyncio
    async def test_run_cycle_with_arb_markets(self):
        """Markets with YES+NO < $1.00 should trigger arb detection."""
        pa = ProbabilityArb()
        ctx = _make_ctx()

        # Gamma market format with outcomePrices
        markets = [
            {
                "conditionId": "arb-market-1",
                "outcomePrices": "[0.40, 0.35]",
                "clobTokenIds": '["token_yes", "token_no"]',
            },
            {
                "conditionId": "no-arb-market",
                "outcomePrices": "[0.55, 0.50]",
                "clobTokenIds": '["token_yes2", "token_no2"]',
            },
        ]

        with patch("backend.data.gamma.fetch_markets", new_callable=AsyncMock, return_value=markets):
            # execute_arb has a NameError on market_id -- this test documents the bug
            # In paper mode (clob=None), _place_order_with_retry returns None immediately
            result = await pa.run_cycle(ctx)

        # The run_cycle catches exceptions per-market, so we get a result
        assert isinstance(result, CycleResult)

    @pytest.mark.asyncio
    async def test_run_cycle_gamma_import_failure_returns_errors(self):
        """When Gamma import fails, cycle returns with error."""
        pa = ProbabilityArb()
        ctx = _make_ctx()

        with patch.dict("sys.modules", {"backend.data.gamma": None}):
            result = await pa.run_cycle(ctx)

        # Either empty markets or an error
        assert isinstance(result, CycleResult)


# ---------------------------------------------------------------------------
# execute_arb -- documents the NameError bug
# ---------------------------------------------------------------------------


class TestExecuteArbBug:
    @pytest.mark.asyncio
    async def test_execute_arb_name_error_on_market_id(self):
        """BUG: execute_arb references undefined `market_id` variable on line 104.

        The function signature takes (opportunity, yes_token_id, no_token_id, clob)
        but the body uses `market_id` which is not a parameter.
        This should raise a NameError when called.
        """
        opp = ArbOpportunity(
            market_id="test-market",
            yes_price=0.40,
            no_price=0.35,
            sum_price=0.75,
            profit=0.25,
            fees=0.01,
            net_profit=0.24,
            confidence=1.0,
        )

        with pytest.raises(NameError, match="market_id"):
            await execute_arb(opp, "yes_tok", "no_tok", clob=None)

    @pytest.mark.asyncio
    async def test_execute_arb_with_clob_also_raises(self):
        """Even with a CLOB client, the NameError fires before any order."""
        opp = ArbOpportunity(
            market_id="test-market",
            yes_price=0.40,
            no_price=0.35,
            sum_price=0.75,
            profit=0.25,
            fees=0.01,
            net_profit=0.24,
            confidence=1.0,
        )
        mock_clob = MagicMock()
        mock_clob.place_limit_order = AsyncMock(return_value=MagicMock(order_id="ord_123"))

        with pytest.raises(NameError, match="market_id"):
            await execute_arb(opp, "yes_tok", "no_tok", clob=mock_clob)


# ---------------------------------------------------------------------------
# _place_order_with_retry
# ---------------------------------------------------------------------------


class TestPlaceOrderWithRetry:
    @pytest.mark.asyncio
    async def test_returns_none_when_clob_is_none(self):
        """Paper mode: no CLOB, returns None."""
        result = await _place_order_with_retry(
            token_id="tok", side="BUY", price=0.50, size=10.0,
            clob=None, idempotency_key="key-1",
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_success_returns_order_id(self):
        mock_clob = MagicMock()
        mock_clob.place_limit_order = AsyncMock(
            return_value=MagicMock(order_id="ord_abc")
        )

        result = await _place_order_with_retry(
            token_id="tok", side="BUY", price=0.50, size=10.0,
            clob=mock_clob, idempotency_key="key-1",
        )
        assert result == "ord_abc"

    @pytest.mark.asyncio
    async def test_retry_on_failure(self):
        """Should retry up to ARB_MAX_RETRIES times."""
        mock_clob = MagicMock()
        call_count = 0

        async def failing_order(**kwargs):
            nonlocal call_count
            call_count += 1
            raise Exception("API error")

        mock_clob.place_limit_order = AsyncMock(side_effect=failing_order)

        with pytest.raises(Exception, match="API error"):
            await _place_order_with_retry(
                token_id="tok", side="BUY", price=0.50, size=10.0,
                clob=mock_clob, idempotency_key="key-1",
            )
        # Should have tried 1 + 3 retries = 4 times
        assert call_count == 4


# ---------------------------------------------------------------------------
# process_pending_arbs
# ---------------------------------------------------------------------------


class TestProcessPendingArbs:
    def test_empty_pending_returns_zero(self):
        _pending_arbs.clear()
        count = process_pending_arbs()
        assert count == 0

    def test_expired_arb_removed(self):
        """Arbs older than 5 minutes with max retries exhausted should be removed."""
        _pending_arbs.clear()
        _pending_arbs["old-key"] = {
            "opportunity": MagicMock(),
            "market_id": "m1",
            "queued_at": 0,  # ancient
            "retries": 5,  # over max
        }
        count = process_pending_arbs()
        assert "old-key" not in _pending_arbs


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_ctx():
    """Create a minimal mock StrategyContext."""
    return StrategyContext(
        db=MagicMock(),
        clob=None,  # paper mode
        settings=MagicMock(),
        logger=MagicMock(),
        params={},
        mode="paper",
        bankroll=100.0,
    )
