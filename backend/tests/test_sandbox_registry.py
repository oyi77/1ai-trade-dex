import pytest
from backend.agi.base_node import BaseAGINode, NodeManifest
from backend.agi.sandbox.sandbox_registry import sandbox_registry


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
        sandbox_registry.reset()

    def test_get_valid_node_from_sandbox_registry(self):
        sandbox_registry.register(MockValidNode)

        node = sandbox_registry.get("mock_valid")

        assert node is not None
        assert node.manifest().name == "mock_valid"

    def test_node_with_requires_db_true_is_rejected(self):
        with pytest.raises(
            ValueError, match="requires database access - not allowed in sandbox"
        ):
            sandbox_registry.register(MockDBNode)

        assert "mock_db_node" not in sandbox_registry._plugins

    def test_node_with_requires_live_data_true_is_rejected(self):
        with pytest.raises(
            ValueError, match="requires live data - not allowed in sandbox"
        ):
            sandbox_registry.register(MockLiveDataNode)

        assert "mock_live_data_node" not in sandbox_registry._plugins

    def test_registry_is_reusable(self):
        # Module-level instance — same on re-import
        from backend.agi.sandbox.sandbox_registry import sandbox_registry as sr2
        assert sandbox_registry is sr2

    def test_register_multiple_valid_nodes(self):
        sandbox_registry.register(MockValidNode)

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

        sandbox_registry.register(MockValidNode2)

        assert "mock_valid" in sandbox_registry._plugins
        assert "mock_valid_2" in sandbox_registry._plugins

    def test_get_disabled_node_raises_keyerror(self):
        sandbox_registry.register(MockValidNode)
        sandbox_registry.set_enabled("mock_valid", False)

        with pytest.raises(KeyError, match="is disabled"):
            sandbox_registry.get("mock_valid")

    def test_get_missing_node_raises_keyerror(self):
        with pytest.raises(KeyError, match="not found"):
            sandbox_registry.get("nonexistent")

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
        sandbox_registry.register(node_class)

        node = sandbox_registry.get("instantiation_test")
        assert hasattr(node, "instantiated")
        assert node.instantiated is True

    def test_list_all_returns_manifests(self):
        sandbox_registry.register(MockValidNode)

        manifests = sandbox_registry.list_all()

        assert len(manifests) == 1
        assert manifests[0].name == "mock_valid"
        assert manifests[0].version == "1.0.0"


async def test_sandbox_registry_health_check():
    sandbox_registry.reset()

    sandbox_registry.register(MockValidNode)

    node = sandbox_registry.get("mock_valid")
    health = await node.health_check()

    assert health is True

    sandbox_registry.reset()


def test_sandbox_registry_enabled_disabled():
    sandbox_registry.reset()

    sandbox_registry.register(MockValidNode)

    assert sandbox_registry._enabled["mock_valid"] is True

    sandbox_registry.set_enabled("mock_valid", False)

    assert sandbox_registry._enabled["mock_valid"] is False

    sandbox_registry.reset()


def test_sandbox_registry_reset():
    sandbox_registry.register(MockValidNode)
    assert "mock_valid" in sandbox_registry._plugins

    sandbox_registry.reset()

    assert "mock_valid" not in sandbox_registry._plugins
