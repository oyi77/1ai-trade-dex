"""Forensics AGI node - wraps existing trade forensics."""
from backend.agi.base_node import BaseAGINode, NodeManifest
from backend.agi.agent_state import AgentState
from backend.agi.node_registry import node_registry


@node_registry.plugin
class ForensicsNode(BaseAGINode):
    """Analyzes losing trades and generates improvement insights."""

    @classmethod
    def manifest(cls) -> NodeManifest:
        return NodeManifest(
            name="forensics",
            version="1.0.0",
            description="Analyzes trade losses and generates improvement insights",
            input_keys=["loss_trades"],
            output_keys=["diagnosis", "improvement_suggestions"],
            requires_db=True,
            tags=["analysis", "forensics", "improvement"],
        )

    async def execute(self, state: AgentState) -> AgentState:
        from backend.core.trade_forensics import TradeForensics

        loss_trades = state.get("loss_trades", [])
        if not loss_trades:
            return state.with_error(self.manifest().name, ValueError("No loss trades provided"))

        try:
            forensics = TradeForensics()
            diagnosis = forensics.diagnose_losses(loss_trades)
            return state.evolve(
                data={
                    "diagnosis": diagnosis,
                    "improvement_suggestions": diagnosis.get("suggestions", []),
                }
            )
        except Exception as e:
            return state.with_error(self.manifest().name, e)
