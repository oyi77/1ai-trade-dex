"""Auto-improve AGI node - wraps existing auto-improve system."""

from backend.agi.base_node import BaseAGINode, NodeManifest
from backend.agi.agent_state import AgentState
from backend.agi.node_registry import node_registry


@node_registry.plugin
class AutoImproveNode(BaseAGINode):
    """Generates parameter improvements for underperforming strategies."""

    @classmethod
    def manifest(cls) -> NodeManifest:
        return NodeManifest(
            name="auto_improve",
            version="1.0.0",
            description="Generates parameter improvements for strategies",
            input_keys=["strategy_key", "performance_data"],
            output_keys=["improved_params", "rollback_point"],
            tags=["improvement", "optimization"],
        )

    async def execute(self, state: AgentState) -> AgentState:
        from backend.core.learning.auto_improve import AutoImprove

        strategy_key = state.get("strategy_key")
        performance_data = state.get("performance_data", {})

        if not strategy_key:
            return state.with_error(
                self.manifest().name, ValueError("No strategy_key provided")
            )

        try:
            improver = AutoImprove()
            result = improver.generate_improvement(strategy_key, performance_data)
            return state.evolve(
                data={
                    "improved_params": result.get("params", {}),
                    "rollback_point": result.get("rollback_point"),
                }
            )
        except Exception as e:
            return state.with_error(self.manifest().name, e)
