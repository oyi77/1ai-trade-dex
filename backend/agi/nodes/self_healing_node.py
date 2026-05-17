"""Self-healing AGI node — monitors system health and triggers recovery."""
from backend.agi.base_node import BaseAGINode, NodeManifest
from backend.agi.agent_state import AgentState
from backend.agi.node_registry import node_registry
from backend.agi.self_healing import SelfHealingWatchdog


@node_registry.plugin
class SelfHealingNode(BaseAGINode):
    """Monitors system health and triggers automatic recovery actions."""

    @classmethod
    def manifest(cls) -> NodeManifest:
        return NodeManifest(
            name="self_healing",
            version="1.0.0",
            description="Monitors system health, detects regressions, triggers auto-recovery",
            input_keys=["action"],
            output_keys=["health_score", "actions_taken", "alerts"],
            requires_live_data=False,
            tags=["health", "recovery", "monitoring"],
        )

    async def execute(self, state: AgentState) -> AgentState:
        action = state.get("action", "check")
        watchdog = SelfHealingWatchdog()

        if action == "check":
            actions = watchdog.run_cycle()
            return state.evolve(data={
                "health_score": watchdog.get_health_score(),
                "actions_taken": [{
                    "action_type": a.action_type,
                    "target": a.target,
                    "success": a.success,
                } for a in actions],
                "summary": watchdog.get_summary(),
            })
        elif action == "record_error":
            watchdog.record_error(
                module=state.get("module", "unknown"),
                message=state.get("message", ""),
                severity=state.get("severity", "warning"),
            )
            return state.evolve(data={"recorded": True})
        return state.with_error(self.manifest().name, ValueError(f"Unknown action: {action}"))
