"""Goal engine AGI node - wraps existing AGIGoalEngine."""
from backend.agi.base_node import BaseAGINode, NodeManifest
from backend.agi.agent_state import AgentState
from backend.agi.node_registry import node_registry


@node_registry.plugin
class GoalEngineNode(BaseAGINode):
    """Determines trading goal based on regime and performance."""

    @classmethod
    def manifest(cls) -> NodeManifest:
        return NodeManifest(
            name="goal_engine",
            version="1.0.0",
            description="Determines current trading goal based on regime and performance",
            input_keys=["regime", "performance_metrics"],
            output_keys=["goal", "goal_reason"],
            tags=["goal", "decision"],
        )

    async def execute(self, state: AgentState) -> AgentState:
        from backend.core.agi_goal_engine import AGIGoalEngine

        regime = state.get("regime", "sideways")

        try:
            engine = AGIGoalEngine(session=None)
            goal = engine.get_current_goal(regime)
            return state.evolve(
                data={
                    "goal": goal.value,
                    "goal_reason": engine._goal_reason,
                }
            )
        except Exception as e:
            return state.with_error(self.manifest().name, e)
