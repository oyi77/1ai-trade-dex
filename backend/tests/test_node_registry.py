import pytest

from backend.agi.node_registry import node_registry
from backend.agi.base_node import BaseAGINode, NodeManifest
from backend.agi.agent_state import AgentState


class TestNodeRegistry:

    def teardown_method(self):
        node_registry.reset()

    def test_register_valid_node(self):
        class TestNode(BaseAGINode):
            @classmethod
            def manifest(cls) -> NodeManifest:
                return NodeManifest(
                    name="test_node",
                    version="1.0.0",
                    description="Test node",
                    input_keys=[],
                    output_keys=[],
                )

            async def execute(self, state: AgentState) -> AgentState:
                return state

        node_registry.register(TestNode)

        assert "test_node" in node_registry._plugins
        assert node_registry._enabled["test_node"] is True
        assert node_registry._health_status["test_node"] is True

    def test_get_node_by_name(self):
        class TestNode(BaseAGINode):
            @classmethod
            def manifest(cls) -> NodeManifest:
                return NodeManifest(
                    name="test_node_get",
                    version="1.0.0",
                    description="Test node for get",
                    input_keys=[],
                    output_keys=[],
                )

            async def execute(self, state: AgentState) -> AgentState:
                return state

        node_registry.register(TestNode)
        node = node_registry.get("test_node_get")

        assert node is not None
        assert isinstance(node, TestNode)

    def test_get_disabled_node_raises_keyerror(self):
        class TestNode(BaseAGINode):
            @classmethod
            def manifest(cls) -> NodeManifest:
                return NodeManifest(
                    name="disabled_test_node",
                    version="1.0.0",
                    description="Disabled test node",
                    input_keys=[],
                    output_keys=[],
                )

            async def execute(self, state: AgentState) -> AgentState:
                return state

        node_registry.register(TestNode)
        node_registry.set_enabled("disabled_test_node", False)

        with pytest.raises(KeyError, match="is disabled"):
            node_registry.get("disabled_test_node")

    def test_get_nonexistent_node_raises_keyerror(self):
        with pytest.raises(KeyError, match="not found"):
            node_registry.get("nonexistent_node")

    def test_list_all_returns_only_enabled_nodes(self):
        class EnabledNode(BaseAGINode):
            @classmethod
            def manifest(cls) -> NodeManifest:
                return NodeManifest(
                    name="enabled_node",
                    version="1.0.0",
                    description="Enabled node",
                    input_keys=[],
                    output_keys=[],
                )

            async def execute(self, state: AgentState) -> AgentState:
                return state

        class DisabledNode(BaseAGINode):
            @classmethod
            def manifest(cls) -> NodeManifest:
                return NodeManifest(
                    name="disabled_node_list",
                    version="1.0.0",
                    description="Disabled node",
                    input_keys=[],
                    output_keys=[],
                )

            async def execute(self, state: AgentState) -> AgentState:
                return state

        node_registry.register(EnabledNode)
        node_registry.register(DisabledNode)
        node_registry.set_enabled("disabled_node_list", False)

        manifests = node_registry.list_all()

        assert len(manifests) == 1
        assert manifests[0].name == "enabled_node"

    def test_auto_discover_loads_nodes_from_package(self):
        count = node_registry.auto_discover("backend.agi.nodes")
        assert count > 0

    def test_singleton_instance(self):
        # Singleton behavior — import returns same instance
        from backend.agi.node_registry import node_registry as registry2
        assert node_registry is registry2

    @pytest.mark.asyncio
    async def test_health_check(self):
        class HealthNode(BaseAGINode):
            @classmethod
            def manifest(cls) -> NodeManifest:
                return NodeManifest(
                    name="health_node",
                    version="1.0.0",
                    description="Node with health check",
                    input_keys=[],
                    output_keys=[],
                )

            async def execute(self, state: AgentState) -> AgentState:
                return state

            async def health_check(self) -> bool:
                return True

        node_registry.register(HealthNode)

        results = await node_registry.run_health_checks()

        assert results["health_node"] is True
