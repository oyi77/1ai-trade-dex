"""Strategy composer AGI node - wraps existing StrategyComposer."""
from backend.agi.base_node import BaseAGINode, NodeManifest
from backend.agi.agent_state import AgentState
from backend.agi.node_registry import node_registry


@node_registry.plugin
class StrategyComposerNode(BaseAGINode):
    """Composes strategy blocks into an executable strategy."""

    @classmethod
    def manifest(cls) -> NodeManifest:
        return NodeManifest(
            name="strategy_composer",
            version="1.0.0",
            description="Composes strategy blocks into executable strategy",
            input_keys=["regime", "market_data"],
            output_keys=["strategy_composition"],
            tags=["composition", "strategy"],
        )

    async def execute(self, state: AgentState) -> AgentState:
        from backend.core.strategy_composer import StrategyComposer

        regime = state.get("regime", "sideways")
        market_data = state.get("market_data", {})

        try:
            composer = StrategyComposer()
            composition = composer.compose(regime=regime, market_data=market_data)
            return state.evolve(data={"strategy_composition": composition})
        except Exception as e:
            return state.with_error(self.manifest().name, e)