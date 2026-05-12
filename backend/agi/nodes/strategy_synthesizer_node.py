"""Strategy synthesizer AGI node - wraps existing synthesizer."""
from backend.agi.base_node import BaseAGINode, NodeManifest
from backend.agi.agent_state import AgentState
from backend.agi.node_registry import node_registry


@node_registry.plugin
class StrategySynthesizerNode(BaseAGINode):
    """Synthesizes new strategies via LLM."""

    @classmethod
    def manifest(cls) -> NodeManifest:
        return NodeManifest(
            name="strategy_synthesizer",
            version="1.0.0",
            description="Synthesizes new trading strategies using LLM",
            input_keys=["regime", "market_data"],
            output_keys=["synthesized_strategy"],
            tags=["synthesis", "strategy", "llm"],
        )

    async def execute(self, state: AgentState) -> AgentState:
        from backend.core.strategy_synthesizer import StrategySynthesizer

        regime = state.get("regime", "sideways")
        market_data = state.get("market_data", {})

        try:
            synthesizer = StrategySynthesizer()
            result = await synthesizer.synthesize(regime=regime, market_data=market_data)
            return state.evolve(data={"synthesized_strategy": result})
        except Exception as e:
            return state.with_error(self.manifest().name, e)
