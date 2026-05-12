"""Evolution AGI node - manages strategy evolution lifecycle."""
from backend.agi.base_node import BaseAGINode, NodeManifest
from backend.agi.agent_state import AgentState
from backend.agi.node_registry import node_registry


@node_registry.plugin
class EvolutionNode(BaseAGINode):
    """Manages strategy evolution through shadow→paper→live promotion."""

    @classmethod
    def manifest(cls) -> NodeManifest:
        return NodeManifest(
            name="evolution",
            version="1.0.0",
            description="Manages strategy lifecycle and promotion pipeline",
            input_keys=["strategy_performance", "stage"],
            output_keys=["promotion_decision", "next_stage"],
            tags=["lifecycle", "evolution", "promotion"],
        )

    async def execute(self, state: AgentState) -> AgentState:
        from backend.core.autonomous_promoter import AutonomousPromoter

        performance = state.get("strategy_performance", {})
        stage = state.get("stage", "shadow")

        try:
            promoter = AutonomousPromoter()
            decision = promoter.evaluate_promotion(performance, stage)
            return state.evolve(
                data={
                    "promotion_decision": decision.get("action", "hold"),
                    "next_stage": decision.get("next_stage", stage),
                }
            )
        except Exception as e:
            return state.with_error(self.manifest().name, e)