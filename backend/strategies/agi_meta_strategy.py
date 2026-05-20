from __future__ import annotations
from backend.strategies.base import BaseStrategy, StrategyContext, CycleResult
from backend.core.agi_orchestrator import AGIOrchestrator


class AGIMetaStrategy(BaseStrategy):
    """
    Autonomous Meta-Strategy for AGI Orchestration.

    This strategy doesn't trade directly but runs the AGIOrchestrator cycle
    to update market regimes, set high-level goals, and adjust allocations.
    """

    name = "agi_orchestrator"
    description = "Autonomous AGI Research and Goal-Setting Cycle"
    category = "ai_meta"
    default_params = {"cycle_interval_hours": 1}

    async def run_cycle(self, ctx: StrategyContext) -> CycleResult:
        """Execute the AGI Orchestrator cycle autonomously."""
        ctx.logger.info(f"[{self.name}] Starting autonomous AGI cycle...")

        orchestrator = AGIOrchestrator(session=ctx.db)
        try:
            # run_cycle is now asynchronous, await it directly
            result = await orchestrator.run_cycle()

            ctx.logger.info(
                f"[{self.name}] AGI cycle complete. Regime: {result.regime.value}, Goal: {result.goal.value}"
            )

            if result.errors:
                for err in result.errors:
                    ctx.logger.error(f"[{self.name}] AGI Cycle Error: {err}")

            return CycleResult(
                decisions_recorded=1,
                trades_attempted=0,
                trades_placed=0,
                errors=result.errors,
                decisions=[
                    {
                        "type": "agi_cycle",
                        "regime": result.regime.value,
                        "goal": result.goal.value,
                        "actions": result.actions_taken,
                    }
                ],
            )
        finally:
            # Orchestrator doesn't own the session here, so we don't close it,
            # but we follow its own cleanup if needed.
            pass
