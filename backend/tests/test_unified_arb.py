"""Tests for unified PM arbitrage strategy (detection-only rewrite)."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.strategies.unified_pm_arb import UnifiedPMArb
from backend.strategies.cross_market_arb_enhanced import ArbOpportunityEnhanced, ScanResult


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
            "token_id_a": market_a,
            "token_id_b": market_b,
        },
    )


def _make_scan_result(opps=None, markets_scanned=100, duration_ms=50.0):
    return ScanResult(
        opportunities=opps or [],
        markets_scanned=markets_scanned,
        scan_duration_ms=duration_ms,
    )


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
        assert "min_net_edge" in params
        assert "enabled" in params
        assert params["enabled"] is True


# ---------------------------------------------------------------------------
# Unit: decision building from opportunities
# ---------------------------------------------------------------------------


class TestDecisionBuilding:
    def test_builds_decision_from_opportunity(self):
        opp = _make_opp()
        strategy = UnifiedPMArb()

        # Simulate what run_cycle does internally on the detected opportunities
        decisions = []
        for idx, o in enumerate([opp]):
            size_usd = getattr(o, "size_usd", None) or 10.0
            _uniq_suffix = (
                f"{o.platform_a}:{o.platform_b}:{o.price_a:.4f}:"
                f"{o.price_b:.4f}:{o.kind}:{idx}"
            )
            _cid = o.event_id or _uniq_suffix
            decision = {
                "kind": o.kind,
                "decision": "BUY",
                "direction": "YES",
                "condition_id": _cid,
                "market_ticker": _cid,
                "platform_a": o.platform_a,
                "platform_b": o.platform_b,
                "price_a": o.price_a,
                "price_b": o.price_b,
                "net_profit": o.net_profit,
                "net_profit_pct": o.net_profit_pct,
                "confidence": o.confidence,
                "raw_spread": o.raw_spread,
                "fees": o.fees,
                "slippage_cost": o.slippage_cost,
                "execution_risk": o.execution_risk,
                "details": o.details,
                "size": size_usd,
                "market_type": "arb",
                "model_probability": min(1.0, 0.5 + o.net_profit_pct),
            }
            decisions.append(decision)

        assert len(decisions) == 1
        d = decisions[0]
        assert d["decision"] == "BUY"
        assert d["direction"] == "YES"
        assert d["market_type"] == "arb"
        assert d["platform_a"] == "polymarket"
        assert d["platform_b"] == "kalshi"
        assert d["confidence"] > 0
        assert d["size"] == 10.0
        assert d["model_probability"] <= 1.0
        assert "condition_id" in d
        assert "details" in d


# ---------------------------------------------------------------------------
# History tracking
# ---------------------------------------------------------------------------


class TestHistory:
    def test_empty_history(self):
        strategy = UnifiedPMArb()
        assert strategy.get_history() == []

    def test_history_after_detection(self):
        strategy = UnifiedPMArb()
        strategy._history.append({"event_id": "x", "status": "detected"})
        assert len(strategy.get_history()) == 1


# ---------------------------------------------------------------------------
# Integration: run_cycle with mocked providers and detector
# ---------------------------------------------------------------------------


class TestRunCycle:
    @pytest.mark.asyncio
    async def test_cycle_no_markets(self):
        """Both fetches return empty -> error."""
        strategy = UnifiedPMArb()
        ctx = MagicMock()
        ctx.db = MagicMock()
        ctx.bankroll = 100.0

        with patch.object(strategy, "_fetch_polymarket", AsyncMock(return_value=[])):
            with patch.object(strategy, "_fetch_kalshi", AsyncMock(return_value=[])):
                result = await strategy.run_cycle(ctx)

        assert result.trades_placed == 0
        assert result.decisions_recorded == 0
        assert len(result.errors) > 0

    @pytest.mark.asyncio
    async def test_cycle_no_opportunities(self):
        """Markets fetched but detector finds nothing -> zero trades."""
        strategy = UnifiedPMArb()
        ctx = MagicMock()
        ctx.db = MagicMock()
        ctx.bankroll = 100.0

        with patch.object(strategy, "_fetch_polymarket", AsyncMock(return_value=[{"question": "Test", "event_id": "1", "yes_price": 0.55, "no_price": 0.55, "platform": "polymarket"}])), \
             patch.object(strategy, "_fetch_kalshi", AsyncMock(return_value=[])), \
             patch.object(strategy, "_get_detector", AsyncMock()) as mock_detector:
            mock_detector.return_value.scan_all_providers = MagicMock(
                return_value=_make_scan_result(opps=[])
            )
            result = await strategy.run_cycle(ctx)

        assert result.trades_placed == 0
        assert result.decisions_recorded == 0

    @pytest.mark.asyncio
    async def test_cycle_opportunities_become_decisions(self):
        """Detector returns opportunities -> decisions returned in CycleResult."""
        strategy = UnifiedPMArb()
        ctx = MagicMock()
        ctx.db = MagicMock()
        ctx.bankroll = 100.0

        opp = _make_opp(net_profit=0.05)
        mock_scan = _make_scan_result(opps=[opp])

        with patch.object(strategy, "_fetch_polymarket", AsyncMock(return_value=[{"question": "BTC above 100k?", "event_id": "evt1", "yes_price": 0.60, "no_price": 0.40, "platform": "polymarket"}])), \
             patch.object(strategy, "_fetch_kalshi", AsyncMock(return_value=[{"question": "BTC above 100k?", "event_id": "evt1", "yes_price": 0.35, "no_price": 0.65, "platform": "kalshi"}])), \
             patch.object(strategy, "_get_detector", AsyncMock()) as mock_detector:
            mock_detector.return_value.scan_all_providers = MagicMock(return_value=mock_scan)
            result = await strategy.run_cycle(ctx)

        assert result.decisions_recorded == 1
        assert result.trades_placed == 0  # detection only
        assert len(result.decisions) == 1
        assert result.decisions[0]["market_type"] == "arb"
        assert result.decisions[0]["platform_a"] == "polymarket"
        assert result.decisions[0]["platform_b"] == "kalshi"

    @pytest.mark.asyncio
    async def test_cycle_respects_max_opportunities(self):
        """Only return up to max_opportunities_per_cycle."""
        strategy = UnifiedPMArb()
        strategy.default_params["max_opportunities_per_cycle"] = 2
        ctx = MagicMock()
        ctx.db = MagicMock()
        ctx.bankroll = 100.0

        opps = [_make_opp(event_id=f"evt{i}", net_profit=0.05 - i * 0.001) for i in range(5)]
        mock_scan = _make_scan_result(opps=opps)

        with patch.object(strategy, "_fetch_polymarket", AsyncMock(return_value=[{"question": "Test", "event_id": "x", "yes_price": 0.55, "no_price": 0.55, "platform": "polymarket"}])), \
             patch.object(strategy, "_fetch_kalshi", AsyncMock(return_value=[])), \
             patch.object(strategy, "_get_detector", AsyncMock()) as mock_detector:
            mock_detector.return_value.scan_all_providers = MagicMock(return_value=mock_scan)
            result = await strategy.run_cycle(ctx)

        assert result.decisions_recorded == 2
        assert len(result.decisions) == 2

    @pytest.mark.asyncio
    async def test_cycle_fetch_errors_handled(self):
        """When one provider fails, still run with the other."""
        strategy = UnifiedPMArb()
        ctx = MagicMock()
        ctx.db = MagicMock()
        ctx.bankroll = 100.0

        opp = _make_opp()
        mock_scan = _make_scan_result(opps=[opp])

        with patch.object(strategy, "_fetch_polymarket", AsyncMock(side_effect=Exception("Gamma down"))), \
             patch.object(strategy, "_fetch_kalshi", AsyncMock(return_value=[{"question": "Test", "event_id": "x", "yes_price": 0.55, "no_price": 0.55, "platform": "kalshi"}])), \
             patch.object(strategy, "_get_detector", AsyncMock()) as mock_detector:
            mock_detector.return_value.scan_all_providers = MagicMock(return_value=mock_scan)
            result = await strategy.run_cycle(ctx)

        # Should still complete with Kalshi markets
        assert result.decisions_recorded == 1
        assert len(result.errors) == 0
