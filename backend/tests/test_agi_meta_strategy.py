"""Tests for AGIMetaStrategy — AGI orchestrator cycle wrapper."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from dataclasses import dataclass, field

from backend.strategies.agi_meta_strategy import AGIMetaStrategy
from backend.strategies.base import StrategyContext, CycleResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@dataclass
class _FakeAGICycleResult:
    regime: MagicMock
    goal: MagicMock
    errors: list = field(default_factory=list)
    actions_taken: int = 0


def _make_ctx(bankroll=100.0):
    db = MagicMock()
    db.query.return_value.filter.return_value.all.return_value = []
    return StrategyContext(
        db=db,
        clob=None,
        settings=MagicMock(),
        logger=MagicMock(),
        params={},
        mode="paper",
        bankroll=bankroll,
    )


def _make_agi_result(regime_val="BULL", goal_val="MAXIMIZE_PNL", errors=None, actions=1):
    result = _FakeAGICycleResult(
        regime=MagicMock(value=regime_val),
        goal=MagicMock(value=goal_val),
        errors=errors or [],
        actions_taken=actions,
    )
    return result


# ---------------------------------------------------------------------------
# Metadata tests
# ---------------------------------------------------------------------------


class TestAGIMetaStrategyMeta:
    def test_name(self):
        s = AGIMetaStrategy()
        assert s.name == "agi_orchestrator"

    def test_category(self):
        s = AGIMetaStrategy()
        assert s.category == "ai_meta"

    def test_description(self):
        s = AGIMetaStrategy()
        assert len(s.description) > 0

    def test_default_params(self):
        params = AGIMetaStrategy.default_params
        assert "cycle_interval_hours" in params
        assert params["cycle_interval_hours"] == 1


# ---------------------------------------------------------------------------
# run_cycle tests
# ---------------------------------------------------------------------------


class TestRunCycle:
    @pytest.mark.asyncio
    async def test_returns_cycle_result(self):
        """run_cycle must return a CycleResult."""
        strategy = AGIMetaStrategy()
        ctx = _make_ctx()
        fake_result = _make_agi_result()

        with patch("backend.strategies.agi_meta_strategy.AGIOrchestrator") as MockOrch:
            mock_orch = MockOrch.return_value
            mock_orch.run_cycle = AsyncMock(return_value=fake_result)

            with patch("backend.strategies.agi_meta_strategy._collect_news_context", AsyncMock(return_value="")):
                result = await strategy.run_cycle(ctx)

        assert isinstance(result, CycleResult)
        assert result.trades_attempted == 0
        assert result.trades_placed == 0

    @pytest.mark.asyncio
    async def test_records_decision_on_success(self):
        """Successful AGI cycle records exactly 1 decision."""
        strategy = AGIMetaStrategy()
        ctx = _make_ctx()
        fake_result = _make_agi_result(regime_val="BULL", goal_val="MAXIMIZE_PNL")

        with patch("backend.strategies.agi_meta_strategy.AGIOrchestrator") as MockOrch:
            mock_orch = MockOrch.return_value
            mock_orch.run_cycle = AsyncMock(return_value=fake_result)

            with patch("backend.strategies.agi_meta_strategy._collect_news_context", AsyncMock(return_value="")):
                result = await strategy.run_cycle(ctx)

        assert result.decisions_recorded == 1
        assert len(result.decisions) == 1
        assert result.decisions[0]["type"] == "agi_cycle"
        assert result.decisions[0]["regime"] == "BULL"
        assert result.decisions[0]["goal"] == "MAXIMIZE_PNL"

    @pytest.mark.asyncio
    async def test_news_context_recorded_in_decision(self):
        """When news context is present, decision includes char count."""
        strategy = AGIMetaStrategy()
        ctx = _make_ctx()
        fake_result = _make_agi_result()

        with patch("backend.strategies.agi_meta_strategy.AGIOrchestrator") as MockOrch:
            mock_orch = MockOrch.return_value
            mock_orch.run_cycle = AsyncMock(return_value=fake_result)

            with patch("backend.strategies.agi_meta_strategy._collect_news_context", AsyncMock(return_value="positive sentiment context")):
                result = await strategy.run_cycle(ctx)

        assert result.decisions[0]["news_context_chars"] == len("positive sentiment context")

    @pytest.mark.asyncio
    async def test_errors_propagated_from_agi_cycle(self):
        """Errors from AGI cycle are propagated to CycleResult."""
        strategy = AGIMetaStrategy()
        ctx = _make_ctx()
        fake_result = _make_agi_result(errors=["fetch_failed", "timeout"])

        with patch("backend.strategies.agi_meta_strategy.AGIOrchestrator") as MockOrch:
            mock_orch = MockOrch.return_value
            mock_orch.run_cycle = AsyncMock(return_value=fake_result)

            with patch("backend.strategies.agi_meta_strategy._collect_news_context", AsyncMock(return_value="")):
                result = await strategy.run_cycle(ctx)

        assert "fetch_failed" in result.errors
        assert "timeout" in result.errors

    @pytest.mark.asyncio
    async def test_orchestrator_exception_returns_error_result(self):
        """When orchestrator raises, the base run() wrapper catches and returns error CycleResult."""
        strategy = AGIMetaStrategy()
        ctx = _make_ctx()

        with patch("backend.strategies.agi_meta_strategy.AGIOrchestrator") as MockOrch:
            mock_orch = MockOrch.return_value
            mock_orch.run_cycle = AsyncMock(side_effect=RuntimeError("orchestrator crash"))

            with patch("backend.strategies.agi_meta_strategy._collect_news_context", AsyncMock(return_value="")):
                # Use base run() which catches exceptions from run_cycle
                result = await strategy.run(ctx)

        assert isinstance(result, CycleResult)
        assert result.decisions_recorded == 0
        assert len(result.errors) > 0

    @pytest.mark.asyncio
    async def test_empty_news_context_no_field(self):
        """When news context is empty, decisions should not have news_context_chars."""
        strategy = AGIMetaStrategy()
        ctx = _make_ctx()
        fake_result = _make_agi_result()

        with patch("backend.strategies.agi_meta_strategy.AGIOrchestrator") as MockOrch:
            mock_orch = MockOrch.return_value
            mock_orch.run_cycle = AsyncMock(return_value=fake_result)

            with patch("backend.strategies.agi_meta_strategy._collect_news_context", AsyncMock(return_value="")):
                result = await strategy.run_cycle(ctx)

        assert "news_context_chars" not in result.decisions[0]

    @pytest.mark.asyncio
    async def test_news_collector_exception_does_not_crash(self):
        """If news collector raises, strategy should still complete."""
        strategy = AGIMetaStrategy()
        ctx = _make_ctx()
        fake_result = _make_agi_result()

        with patch("backend.strategies.agi_meta_strategy.AGIOrchestrator") as MockOrch:
            mock_orch = MockOrch.return_value
            mock_orch.run_cycle = AsyncMock(return_value=fake_result)

            with patch("backend.strategies.agi_meta_strategy._collect_news_context", AsyncMock(side_effect=Exception("news_api_down"))):
                # _collect_news_context is called at top level, exception propagates
                # This tests that the outer run() wrapper catches it
                result = await strategy.run(ctx)

        assert isinstance(result, CycleResult)
