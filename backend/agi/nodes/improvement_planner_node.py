"""Self-improvement planner AGI node — plans improvement cycles."""
from backend.agi.base_node import BaseAGINode, NodeManifest
from backend.agi.agent_state import AgentState
from backend.agi.node_registry import node_registry
from backend.agi.codebase_intelligence import CodebaseScanner, ImprovementAnalyzer


@node_registry.plugin
class ImprovementPlannerNode(BaseAGINode):
    """Analyzes codebase and plans the next improvement cycle."""

    @classmethod
    def manifest(cls) -> NodeManifest:
        return NodeManifest(
            name="improvement_planner",
            version="1.0.0",
            description="Plans improvement cycles by prioritizing candidates",
            input_keys=["candidates", "max_changes"],
            output_keys=["plan", "prioritized_candidates"],
            requires_live_data=False,
            tags=["planning", "improvement"],
        )

    async def execute(self, state: AgentState) -> AgentState:
        candidates_data = state.get("candidates", [])
        max_changes = state.get("max_changes", 3)
        severity_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
        sorted_candidates = sorted(
            candidates_data,
            key=lambda c: severity_order.get(c.get("severity", "low"), 99),
        )[:max_changes]
        return state.evolve(data={
            "plan": {
                "total_candidates": len(candidates_data),
                "to_address": len(sorted_candidates),
                "estimated_effort": "high" if any(
                    c.get("severity") in ("critical", "high") for c in sorted_candidates
                ) else "medium",
            },
            "prioritized_candidates": sorted_candidates,
        })
