"""Codebase scanner AGI node — wraps CodebaseScanner for the graph engine."""
from backend.agi.base_node import BaseAGINode, NodeManifest
from backend.agi.agent_state import AgentState
from backend.agi.node_registry import node_registry
from backend.agi.codebase_intelligence import CodebaseScanner, ImprovementAnalyzer


@node_registry.plugin
class CodebaseScannerNode(BaseAGINode):
    """Scans the codebase and identifies improvement candidates."""

    @classmethod
    def manifest(cls) -> NodeManifest:
        return NodeManifest(
            name="codebase_scanner",
            version="1.0.0",
            description="Scans backend codebase, builds dependency graph, finds improvement candidates",
            input_keys=["action"],
            output_keys=["modules", "candidates", "health_metrics"],
            requires_live_data=False,
            tags=["scan", "analysis", "intelligence"],
        )

    async def execute(self, state: AgentState) -> AgentState:
        action = state.get("action", "scan")
        if action == "scan":
            scanner = CodebaseScanner()
            graph = scanner.scan_all()
            analyzer = ImprovementAnalyzer(scanner)
            candidates = analyzer.find_candidates()
            return state.evolve(data={
                "modules": len(graph.all_modules()),
                "candidates": [{
                    "category": c.category,
                    "file_path": c.file_path,
                    "severity": c.severity,
                    "description": c.description,
                } for c in candidates[:50]],
                "health_metrics": {
                    "total_modules": len(graph.all_modules()),
                    "total_lines": sum(m.lines for m in graph.all_modules()),
                    "total_candidates": len(candidates),
                },
            })
        return state.with_error(self.manifest().name, ValueError(f"Unknown action: {action}"))
