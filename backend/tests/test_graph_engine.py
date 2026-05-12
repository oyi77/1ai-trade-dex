"""Test suite for the GraphEngine."""
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock

from backend.agi.graph_engine import GraphEngine, GraphDefinition
from backend.agi.agent_state import AgentState
from backend.agi.base_node import NodeManifest, BaseAGINode
from backend.agi.node_registry import NodeRegistry


class TestGraphEngine:

    @pytest.fixture
    def mock_node(self):
        node = MagicMock(spec=BaseAGINode)
        node.manifest.return_value = NodeManifest(
            name="test_node",
            version="1.0.0",
            description="Test node",
            input_keys=["input"],
            output_keys=["output"],
        )
        node.execute = AsyncMock(return_value=AgentState(data={"output": "result"}))
        node.can_execute.return_value = True
        return node

    @pytest.fixture
    def registry_with_nodes(self, mock_node):
        registry = NodeRegistry()
        NodeRegistry._instance = None
        registry._plugins = {}
        registry._manifests = {}
        registry._enabled = {}
        registry._health_status = {}
        registry._plugins["node_a"] = mock_node
        registry._plugins["node_b"] = mock_node
        registry._plugins["node_c"] = mock_node
        registry._plugins["node_d"] = mock_node
        registry._manifests["node_a"] = mock_node.manifest.return_value
        registry._manifests["node_b"] = mock_node.manifest.return_value
        registry._manifests["node_c"] = mock_node.manifest.return_value
        registry._manifests["node_d"] = mock_node.manifest.return_value
        registry._enabled["node_a"] = True
        registry._enabled["node_b"] = True
        registry._enabled["node_c"] = True
        registry._enabled["node_d"] = True
        return registry

    def test_add_valid_graph(self, registry_with_nodes):
        engine = GraphEngine(registry=registry_with_nodes)

        graph_def = GraphDefinition(
            name="test_graph",
            nodes=["node_a", "node_b", "node_c"],
            edges=[("node_a", "node_b"), ("node_b", "node_c")],
        )

        engine.add_graph(graph_def)

        assert "test_graph" in engine.graphs
        assert engine.graphs["test_graph"] == graph_def

    def test_graph_validation_detects_cycles(self, registry_with_nodes):
        engine = GraphEngine(registry=registry_with_nodes)

        # Create a graph with a cycle: A -> B -> C -> A
        graph_def = GraphDefinition(
            name="cyclic_graph",
            nodes=["node_a", "node_b", "node_c"],
            edges=[
                ("node_a", "node_b"),
                ("node_b", "node_c"),
                ("node_c", "node_a"),
            ],
        )

        with pytest.raises(ValueError, match="contains a cycle"):
            engine.add_graph(graph_def)

    def test_topological_sort_orders_nodes_correctly(self, registry_with_nodes):
        """Test topological sort produces correct ordering."""
        engine = GraphEngine(registry=registry_with_nodes)

        graph_def = GraphDefinition(
            name="sort_test_graph",
            nodes=["node_a", "node_b", "node_c"],
            edges=[("node_a", "node_b"), ("node_b", "node_c")],
        )

        engine.add_graph(graph_def)
        ordered = engine._topological_sort(graph_def)

        assert ordered == ["node_a", "node_b", "node_c"]

    def test_topological_sort_with_multiple_dependencies(self, registry_with_nodes):
        """Test topological sort with multiple dependency branches."""
        engine = GraphEngine(registry=registry_with_nodes)

        graph_def = GraphDefinition(
            name="multi_dep_graph",
            nodes=["node_a", "node_b", "node_c", "node_d"],
            edges=[
                ("node_a", "node_c"),
                ("node_b", "node_c"),
                ("node_c", "node_d"),
            ],
        )

        engine.add_graph(graph_def)
        ordered = engine._topological_sort(graph_def)

        assert ordered[0] in ["node_a", "node_b"]
        assert ordered[1] in ["node_a", "node_b"]
        assert ordered[2] == "node_c"
        assert ordered[3] == "node_d"

    async def test_execute_simple_graph(self, registry_with_nodes):
        """Test executing a simple graph."""
        engine = GraphEngine(registry=registry_with_nodes)

        graph_def = GraphDefinition(
            name="exec_graph",
            nodes=["node_a", "node_b"],
            edges=[("node_a", "node_b")],
        )

        engine.add_graph(graph_def)

        initial_state = AgentState(data={"input": "test"})
        result = await engine.execute_graph("exec_graph", initial_state)

        assert result.data.get("output") == "result"
        assert len(result.errors) == 0

    def test_graph_with_missing_nodes_raises_value_error(self, registry_with_nodes):
        """Test that referencing non-existent nodes raises ValueError."""
        engine = GraphEngine(registry=registry_with_nodes)

        graph_def = GraphDefinition(
            name="missing_node_graph",
            nodes=["node_a", "node_b", "nonexistent_node"],
            edges=[("node_a", "node_b")],
        )

        with pytest.raises(ValueError, match="not found in registry"):
            engine.add_graph(graph_def)

    def test_execute_graph_not_found(self, registry_with_nodes):
        """Test executing a non-existent graph raises ValueError."""
        engine = GraphEngine(registry=registry_with_nodes)

        initial_state = AgentState()
        with pytest.raises(ValueError, match="not found"):
            asyncio.run(engine.execute_graph("nonexistent_graph", initial_state))

    def test_empty_graph(self, registry_with_nodes):
        """Test graph with no edges."""
        engine = GraphEngine(registry=registry_with_nodes)

        graph_def = GraphDefinition(
            name="empty_edges_graph",
            nodes=["node_a", "node_b"],
            edges=[],
        )

        engine.add_graph(graph_def)
        ordered = engine._topological_sort(graph_def)

        assert set(ordered) == {"node_a", "node_b"}

    def test_single_node_graph(self, registry_with_nodes):
        """Test graph with only one node."""
        engine = GraphEngine(registry=registry_with_nodes)

        graph_def = GraphDefinition(
            name="single_node_graph",
            nodes=["node_a"],
            edges=[],
        )

        engine.add_graph(graph_def)
        ordered = engine._topological_sort(graph_def)

        assert ordered == ["node_a"]

    def test_self_loop_detection(self, registry_with_nodes):
        """Test that self-loops are detected as cycles."""
        engine = GraphEngine(registry=registry_with_nodes)

        graph_def = GraphDefinition(
            name="self_loop_graph",
            nodes=["node_a"],
            edges=[("node_a", "node_a")],
        )

        with pytest.raises(ValueError, match="contains a cycle"):
            engine.add_graph(graph_def)

    def test_graph_with_dead_end(self, registry_with_nodes):
        """Test graph where some nodes have no outgoing edges."""
        engine = GraphEngine(registry=registry_with_nodes)

        graph_def = GraphDefinition(
            name="dead_end_graph",
            nodes=["node_a", "node_b", "node_c"],
            edges=[("node_a", "node_b"), ("node_b", "node_c")],
        )

        engine.add_graph(graph_def)
        ordered = engine._topological_sort(graph_def)

        assert ordered == ["node_a", "node_b", "node_c"]

    def test_multiple_independent_chains(self, registry_with_nodes):
        """Test graph with multiple independent dependency chains."""
        engine = GraphEngine(registry=registry_with_nodes)

        graph_def = GraphDefinition(
            name="independent_chains_graph",
            nodes=["node_a", "node_b", "node_c", "node_d"],
            edges=[
                ("node_a", "node_b"),
                ("node_c", "node_d"),
            ],
        )

        engine.add_graph(graph_def)
        ordered = engine._topological_sort(graph_def)

        assert ordered[0] in ["node_a", "node_c"]
        assert ordered[1] in ["node_a", "node_c"]
        assert ordered[2] in ["node_b", "node_d"]
        assert ordered[3] in ["node_b", "node_d"]
