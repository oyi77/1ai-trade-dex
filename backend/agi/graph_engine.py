"""Directed graph executor for AGI pipeline orchestration."""
from dataclasses import dataclass, field
from typing import List, Dict, Tuple
from collections import defaultdict

from backend.agi.agent_state import AgentState
from backend.agi.node_registry import node_registry


@dataclass
class GraphDefinition:
    """Defines a directed acyclic graph of AGI nodes."""
    name: str
    nodes: List[str] = field(default_factory=list)
    edges: List[Tuple[str, str]] = field(default_factory=list)


class GraphEngine:
    """Executes AGI node graphs with dependency resolution and sandbox support."""

    def __init__(self, registry=None):
        self.registry = registry or node_registry
        self.graphs: Dict[str, GraphDefinition] = {}

    def add_graph(self, graph_def: GraphDefinition) -> None:
        """Register a graph definition."""
        self._validate_graph(graph_def)
        self.graphs[graph_def.name] = graph_def

    def _validate_graph(self, graph_def: GraphDefinition) -> None:
        """Validate graph structure and detect cycles."""
        # Check all nodes exist in registry
        for node_name in graph_def.nodes:
            if node_name not in self.registry._plugins:
                raise ValueError(f"Node '{node_name}' not found in registry")

        # Build adjacency list and detect cycles
        adj = defaultdict(list)
        for src, dst in graph_def.edges:
            adj[src].append(dst)

        if self._detect_cycle(graph_def.nodes, adj):
            raise ValueError(f"Graph '{graph_def.name}' contains a cycle")

    def _detect_cycle(self, nodes: List[str], adj: Dict[str, List[str]]) -> bool:
        """Detect cycles using DFS with coloring."""
        WHITE, GRAY, BLACK = 0, 1, 2
        color = {n: WHITE for n in nodes}

        def dfs(node):
            color[node] = GRAY
            for neighbor in adj.get(node, []):
                if neighbor not in color:
                    continue
                if color[neighbor] == GRAY:
                    return True
                if color[neighbor] == WHITE and dfs(neighbor):
                    return True
            color[node] = BLACK
            return False

        for node in nodes:
            if color[node] == WHITE:
                if dfs(node):
                    return True
        return False

    def _topological_sort(self, graph_def: GraphDefinition) -> List[str]:
        """Order nodes by dependencies (topological sort)."""
        in_degree = {n: 0 for n in graph_def.nodes}
        adj = defaultdict(list)

        for src, dst in graph_def.edges:
            adj[src].append(dst)
            if dst in in_degree:
                in_degree[dst] += 1

        queue = [n for n in graph_def.nodes if in_degree.get(n, 0) == 0]
        result = []

        while queue:
            node = queue.pop(0)
            result.append(node)
            for neighbor in adj[node]:
                if neighbor in in_degree:
                    in_degree[neighbor] -= 1
                    if in_degree[neighbor] == 0:
                        queue.append(neighbor)

        return result

    async def execute_graph(self, graph_name: str, initial_state: AgentState) -> AgentState:
        """Execute all nodes in a graph in topological order."""
        if graph_name not in self.graphs:
            raise ValueError(f"Graph '{graph_name}' not found")

        graph_def = self.graphs[graph_name]
        ordered_nodes = self._topological_sort(graph_def)
        state = initial_state

        for node_name in ordered_nodes:
            state = await self.execute_node(node_name, state)

        return state

    async def execute_node(self, node_name: str, state: AgentState) -> AgentState:
        """Execute a single node with input validation and sandbox checks."""
        node = self.registry.get(node_name)
        manifest = node.manifest()

        # Skip nodes that require DB in sandbox mode
        if state.is_sandbox and manifest.requires_db:
            return state

        # Skip nodes that require live data in sandbox mode
        if state.is_sandbox and manifest.requires_live_data:
            return state

        # Check input availability
        if not node.can_execute(state):
            missing = [k for k in manifest.input_keys if k not in state.data]
            state = state.with_error(node_name, ValueError(f"Missing inputs: {missing}"))
            return state

        try:
            state = await node.execute(state)
        except Exception as e:
            state = state.with_error(node_name, e)

        return state
