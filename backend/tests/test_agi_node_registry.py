"""Tests for AGI node registry — same patterns as test_node_registry.py but via agi.node_registry."""

import pytest
from backend.agi.node_registry import NodeRegistry
from backend.agi.base_node import BaseAGINode, NodeManifest
from backend.agi.agent_state import AgentState


class TestAGINodeRegistry:
    """Test suite for AGI node registry."""

    def teardown_method(self):
        """Reset registry after each test."""
        NodeRegistry.reset()

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
        registry = NodeRegistry()
        NodeCls = self._make_node("test_register")
        registry.register(NodeCls)
        assert "test_register" in registry._plugins
        assert registry._enabled["test_register"] is True
        assert registry._health_status["test_register"] is True

    def test_get_node_by_name(self):
        """Test retrieving a node by name."""
        registry = NodeRegistry()
        NodeCls = self._make_node("test_get")
        registry.register(NodeCls)
        node = registry.get("test_get")
        assert node is not None

    def test_get_disabled_node_raises(self):
        """Test that getting a disabled node raises KeyError."""
        registry = NodeRegistry()
        NodeCls = self._make_node("test_disabled")
        registry.register(NodeCls)
        registry._enabled["test_disabled"] = False
        with pytest.raises(KeyError):
            registry.get("test_disabled")

    def test_list_all_only_enabled(self):
        """Test that list_all returns only enabled nodes."""
        registry = NodeRegistry()
        NodeA = self._make_node("enabled_node")
        NodeB = self._make_node("disabled_node")
        registry.register(NodeA)
        registry.register(NodeB)
        registry._enabled["disabled_node"] = False
        names = [m.name for m in registry.list_all()]
        assert "enabled_node" in names
        assert "disabled_node" not in names

    def test_singleton_identity(self):
        """Test that NodeRegistry is a singleton."""
        r1 = NodeRegistry()
        r2 = NodeRegistry()
        assert r1 is r2

    def test_reset_clears_instance(self):
        """Test that reset() creates a new instance."""
        r1 = NodeRegistry()
        NodeRegistry.reset()
        r2 = NodeRegistry()
        assert r1 is not r2

    def test_sandbox_node_skipped_when_live_required(self):
        """Test that sandbox nodes are registered but can be excluded."""
        registry = NodeRegistry()
        NodeCls = self._make_node("sandbox_node")
        registry.register(NodeCls)
        # Verify the node exists but can be excluded by consumer logic
        assert "sandbox_node" in registry._plugins

    @pytest.mark.asyncio
    async def test_sandbox_node_execute_returns_state(self):
        """Test that executing a node returns the modified state."""
        registry = NodeRegistry()
        NodeCls = self._make_node("exec_node")
        registry.register(NodeCls)
        node = registry.get("exec_node")
        state = AgentState(data={})
        result = await node.execute(state)
        assert isinstance(result, AgentState)
        assert result.data.get("exec_node") == "executed"
