"""Regime detector AGI node - wraps existing RegimeDetector."""
from backend.agi.base_node import BaseAGINode, NodeManifest
from backend.agi.agent_state import AgentState
from backend.agi.node_registry import node_registry


@node_registry.plugin
class RegimeDetectorNode(BaseAGINode):
    """Detects market regime and adds it to agent state."""

    @classmethod
    def manifest(cls) -> NodeManifest:
        return NodeManifest(
            name="regime_detector",
            version="1.0.0",
            description="Detects current market regime (bull/bear/sideways/crisis)",
            input_keys=["prices"],
            output_keys=["regime", "regime_confidence"],
            requires_live_data=True,
            tags=["analysis", "regime"],
        )

    async def execute(self, state: AgentState) -> AgentState:
        from backend.core.regime_detector import RegimeDetector

        prices = state.get("prices", [])
        if not prices:
            return state.with_error(self.manifest().name, ValueError("No price data"))

        market_data = {"prices": prices}
        try:
            detector = RegimeDetector()
            result = detector.detect_regime(market_data)
            return state.evolve(
                data={
                    "regime": result.regime.value,
                    "regime_confidence": result.confidence,
                }
            )
        except Exception as e:
            return state.with_error(self.manifest().name, e)
