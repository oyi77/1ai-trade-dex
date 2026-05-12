import pytest
import asyncio
from unittest.mock import MagicMock, AsyncMock
from backend.agi.base_node import BaseAGINode, NodeManifest
from backend.agi.agent_state import AgentState
from backend.agi.sandbox.sandbox_registry import SandboxNodeRegistry


class MockValidNode(BaseAGINode):
    @classmethod
    def manifest(cls):
        return NodeManifest(
            name="mock_valid",
            version="1.0.0",
            description="A valid sandbox node",
            input_keys=["test_input"],
            output_keys=["test_output"],
            tags=["test"],
        )

    async def execute(self, state):
        return state


class MockDBNode(BaseAGINode):
    @classmethod
    def manifest(cls):
        return NodeManifest(
            name="mock_db_node",
            version="1.0.0",
            description="Node requiring DB",
            input_keys=["test"],
            output_keys=["result"],
            requires_db=True,
        )

    async def execute(self, state):
        return state


class MockLiveDataNode(BaseAGINode):
    @classmethod
    def manifest(cls):
        return NodeManifest(
            name="mock_live_data_node",
            version="1.0.0",
            description="Node requiring live data",
            input_keys=["test"],
            output_keys=["result"],
            requires_live_data=True,
        )

    async def execute(self, state):
        return state


class TestSandboxNodeRegistry:
    def setup_method(self):
        SandboxNodeRegistry._instance = None
        self.registry = SandboxNodeRegistry()

    def test_get_valid_node_from_sandbox_registry(self):
        self.registry.register(MockValidNode)

        node = self.registry.get("mock_valid")

        assert node is not None
        assert node.manifest().name == "mock_valid"

    def test_node_with_requires_db_true_is_rejected(self):
        with pytest.raises(ValueError, match="requires database access - not allowed in sandbox"):
            self.registry.register(MockDBNode)

        assert "mock_db_node" not in self.registry._plugins

    def test_node_with_requires_live_data_true_is_rejected(self):
        with pytest.raises(ValueError, match="requires live data - not allowed in sandbox"):
            self.registry.register(MockLiveDataNode)

        assert "mock_live_data_node" not in self.registry._plugins

    def test_registry_returns_instance(self):
        registry1 = SandboxNodeRegistry()
        registry2 = SandboxNodeRegistry()

        assert registry1 is registry2

    def test_register_multiple_valid_nodes(self):
        self.registry.register(MockValidNode)

        class MockValidNode2(BaseAGINode):
            @classmethod
            def manifest(cls):
                return NodeManifest(
                    name="mock_valid_2",
                    version="1.0.0",
                    description="Another valid node",
                    input_keys=["test"],
                    output_keys=["result"],
                )

            async def execute(self, state):
                return state

        self.registry.register(MockValidNode2)

        assert "mock_valid" in self.registry._plugins
        assert "mock_valid_2" in self.registry._plugins

    def test_get_disabled_node_raises_keyerror(self):
        self.registry.register(MockValidNode)
        self.registry.set_enabled("mock_valid", False)

        with pytest.raises(KeyError, match="is disabled"):
            self.registry.get("mock_valid")

    def test_get_missing_node_raises_keyerror(self):
        with pytest.raises(KeyError, match="not found"):
            self.registry.get("nonexistent")

    def test_node_instantiation_on_register(self):
        class InstantiationTestNode(BaseAGINode):
            @classmethod
            def manifest(cls):
                return NodeManifest(
                    name="instantiation_test",
                    version="1.0.0",
                    description="Test",
                    input_keys=["a"],
                    output_keys=["b"],
                )

            async def execute(self, state):
                return state

            def __init__(self):
                super().__init__()
                self.instantiated = True

        node_class = InstantiationTestNode
        self.registry.register(node_class)

        node = self.registry.get("instantiation_test")
        assert hasattr(node, "instantiated")
        assert node.instantiated is True

    def test_list_all_returns_manifests(self):
        self.registry.register(MockValidNode)

        manifests = self.registry.list_all()

        assert len(manifests) == 1
        assert manifests[0].name == "mock_valid"
        assert manifests[0].version == "1.0.0"


def test_sandbox_registry_singleton():
    registry1 = SandboxNodeRegistry()
    registry2 = SandboxNodeRegistry()

    assert registry1 is registry2

    SandboxNodeRegistry._instance = None


async def test_sandbox_registry_health_check():
    SandboxNodeRegistry._instance = None
    registry = SandboxNodeRegistry()

    registry.register(MockValidNode)

    node = registry.get("mock_valid")
    health = await node.health_check()

    assert health is True

    SandboxNodeRegistry._instance = None


def test_sandbox_registry_enabled_disabled():
    SandboxNodeRegistry._instance = None
    registry = SandboxNodeRegistry()

    registry.register(MockValidNode)

    assert registry._enabled["mock_valid"] is True

    registry.set_enabled("mock_valid", False)

    assert registry._enabled["mock_valid"] is False

    SandboxNodeRegistry._instance = None


def test_sandbox_registry_reset():
    SandboxNodeRegistry._instance = None
    registry = SandboxNodeRegistry()

    registry.register(MockValidNode)
    assert "mock_valid" in registry._plugins

    SandboxNodeRegistry.reset()

    assert SandboxNodeRegistry._instance is None

    new_registry = SandboxNodeRegistry()
    assert "mock_valid" not in new_registry._plugins
