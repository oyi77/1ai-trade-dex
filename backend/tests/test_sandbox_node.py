"""Test suite for SandboxNodeRegistry."""
import pytest

from backend.agi.base_node import BaseAGINode, NodeManifest
from backend.agi.sandbox.sandbox_registry import SandboxNodeRegistry


class MockValidNode(BaseAGINode):
    """A sandbox-safe node for testing."""

    @classmethod
    def manifest(cls) -> NodeManifest:
        return NodeManifest(
            name="mock_valid",
            version="1.0.0",
            description="A valid sandbox node",
            input_keys=["test_input"],
            output_keys=["test_output"],
            tags=["test"],
        )

    async def execute(self, state) -> None:
        pass


class MockDBNode(BaseAGINode):
    """A node that requires DB access."""

    @classmethod
    def manifest(cls) -> NodeManifest:
        return NodeManifest(
            name="mock_db_node",
            version="1.0.0",
            description="A node requiring DB access",
            input_keys=["test"],
            output_keys=["result"],
            requires_db=True,
        )

    async def execute(self, state) -> None:
        pass


class MockLiveDataNode(BaseAGINode):
    """A node that requires live data."""

    @classmethod
    def manifest(cls) -> NodeManifest:
        return NodeManifest(
            name="mock_live_data_node",
            version="1.0.0",
            description="A node requiring live data",
            input_keys=["test"],
            output_keys=["result"],
            requires_live_data=True,
        )

    async def execute(self, state) -> None:
        pass


class TestSandboxNodeRegistry:
    """Tests for SandboxNodeRegistry validation."""

    def setup_method(self):
        """Reset registry before each test."""
        SandboxNodeRegistry._instance = None
        self.registry = SandboxNodeRegistry()

    def test_get_valid_node_from_sandbox_registry(self):
        """Node can be retrieved from sandbox registry."""
        self.registry.register(MockValidNode)

        node = self.registry.get("mock_valid")

        assert node is not None
        assert node.manifest().name == "mock_valid"

    def test_node_with_requires_db_true_is_rejected(self):
        """Node with requires_db=True is rejected by sandbox."""
        with pytest.raises(ValueError, match="requires database access - not allowed in sandbox"):
            self.registry.register(MockDBNode)

        assert "mock_db_node" not in self.registry._plugins

    def test_node_with_requires_live_data_true_is_rejected(self):
        """Node with requires_live_data=True is rejected by sandbox."""
        with pytest.raises(ValueError, match="requires live data - not allowed in sandbox"):
            self.registry.register(MockLiveDataNode)

        assert "mock_live_data_node" not in self.registry._plugins

    def test_valid_node_passes_sandbox_validation(self):
        """Valid node passes sandbox validation."""
        self.registry.register(MockValidNode)

        assert "mock_valid" in self.registry._plugins
        assert self.registry._enabled.get("mock_valid") is True
        assert self.registry._health_status.get("mock_valid") is True

        node = self.registry.get("mock_valid")
        assert isinstance(node, MockValidNode)
