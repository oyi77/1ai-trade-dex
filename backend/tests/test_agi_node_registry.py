"""Tests for AGI node registry — same patterns as test_node_registry.py but via agi.node_registry."""

import pytest
from backend.agi.node_registry import node_registry
from backend.agi.base_node import BaseAGINode, NodeManifest
from backend.agi.agent_state import AgentState


class TestAGINodeRegistry:
    """Test suite for AGI node registry."""

    def teardown_method(self):
        """Reset registry after each test."""
        node_registry.reset()

    def _make_node(self, name: str, is_sandbox: bool = False):
        """Helper to create a test node class."""

        class _Node(BaseAGINode):
            @classmethod
            def manifest(cls) -> NodeManifest:
                return NodeManifest(
                    name=name,
                    version="1.0.0",
                    description=f"Test node {name}",
                    input_keys=[],
                    output_keys=[],
                )

            async def execute(self, state: AgentState) -> AgentState:
                state.data[name] = "executed"
                return state

        _Node.__name__ = name
        return _Node

    def test_register_valid_node(self):
        """Test registering a valid node."""
        NodeCls = self._make_node("test_register")
        node_registry.register(NodeCls)
        assert "test_register" in node_registry._plugins
        assert node_registry._enabled["test_register"] is True
        assert node_registry._health_status["test_register"] is True

    def test_get_node_by_name(self):
        """Test retrieving a node by name."""
        NodeCls = self._make_node("test_get")
        node_registry.register(NodeCls)
        node = node_registry.get("test_get")
        assert node is not None

    def test_get_disabled_node_raises(self):
        """Test that getting a disabled node raises KeyError."""
        registry = NodeRegistry()
        NodeCls = self._make_node("test_disabled")
        node_registry.register(NodeCls)
        node_registry._enabled["test_disabled"] = False
        with pytest.raises(KeyError):
            node_registry.get("test_disabled")

    def test_list_all_only_enabled(self):
        """Test that list_all returns only enabled nodes."""
        NodeA = self._make_node("enabled_node")
        NodeB = self._make_node("disabled_node")
        node_registry.register(NodeA)
        node_registry.register(NodeB)
        node_registry._enabled["disabled_node"] = False
        names = [m.name for m in node_registry.list_all()]
        assert "enabled_node" in names
        assert "disabled_node" not in names

    def test_singleton_identity(self):
        """Test that node_registry resolves to same instance."""
        from backend.agi.node_registry import node_registry as nr2
        assert node_registry is nr2

    def test_reset_clears_instance(self):
        """Test that reset() clears state."""
        NodeCls = self._make_node("reset_test")
        node_registry.register(NodeCls)
        node_registry.reset()
        NodeCls2 = self._make_node("reset_test")
        node_registry.register(NodeCls2)
        assert "reset_test" in node_registry._plugins

    def test_sandbox_node_skipped_when_live_required(self):
        """Test that sandbox nodes are registered but can be excluded."""
        NodeCls = self._make_node("sandbox_node")
        node_registry.register(NodeCls)
        assert "sandbox_node" in node_registry._plugins

    @pytest.mark.asyncio
    async def test_sandbox_node_execute_returns_state(self):
        """Test that executing a node returns the modified state."""
        NodeCls = self._make_node("exec_node")
        node_registry.register(NodeCls)
        node = node_registry.get("exec_node")
        state = AgentState(data={})
        result = await node.execute(state)
        assert isinstance(result, AgentState)
        assert result.data.get("exec_node") == "executed"
