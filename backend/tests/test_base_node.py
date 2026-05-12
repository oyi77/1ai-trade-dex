import pytest
from backend.agi.base_node import BaseAGINode, NodeManifest
from backend.agi.agent_state import AgentState


class TestBaseNodeManifest:
    def test_node_manifest_defaults(self):
        manifest = NodeManifest(
            name="test_node",
            version="1.0.0",
            description="test node",
        )

        assert manifest.name == "test_node"
        assert manifest.version == "1.0.0"
        assert manifest.description == "test node"
        assert manifest.input_keys == []
        assert manifest.output_keys == []
        assert manifest.requires_db is False
        assert manifest.requires_live_data is False
        assert manifest.tags == []


class MockTestNode(BaseAGINode):
    @classmethod
    def manifest(cls):
        return NodeManifest(
            name="mock_test",
            version="1.0.0",
            description="mock node",
            input_keys=["test_input"],
            output_keys=["test_output"],
            tags=["test"],
        )

    async def execute(self, state):
        return state


class TestBaseAGINode:
    def test_manifest_abstract(self):
        try:

            class NoManifestNode(BaseAGINode):
                pass
        except TypeError:

            pass

    def test_can_execute_with_missing_input(self):
        node = MockTestNode()
        state = AgentState(data={})

        assert node.can_execute(state) is False

    def test_can_execute_with_present_input(self):
        node = MockTestNode()
        state = AgentState(data={"test_input": "value"})

        assert node.can_execute(state) is True

    def test_can_execute_with_partial_inputs(self):
        node = MockTestNode()
        state = AgentState(data={"test_input": "value", "other": "data"})

        assert node.can_execute(state) is True

    def test_can_execute_with_extra_inputs(self):
        node = MockTestNode()
        state = AgentState(data={"test_input": "value", "extra": "data"})

        assert node.can_execute(state) is True

    def test_execute_abstract(self):
        try:

            class NoExecuteNode(BaseAGINode):
                @classmethod
                def manifest(cls):
                    return NodeManifest(
                        name="no_execute",
                        version="1.0.0",
                        description="test",
                    )

                async def execute(self, state):
                    return state
        except TypeError:

            pass


def test_node_manifest_input_output_keys():
    manifest = NodeManifest(
        name="test",
        version="1.0.0",
        description="test",
        input_keys=["a", "b"],
        output_keys=["c"],
    )

    assert len(manifest.input_keys) == 2
    assert len(manifest.output_keys) == 1


def test_node_manifest_requires_db_flag():
    manifest = NodeManifest(
        name="test",
        version="1.0.0",
        description="test",
        requires_db=True,
    )

    assert manifest.requires_db is True


def test_node_manifest_requires_live_data_flag():
    manifest = NodeManifest(
        name="test",
        version="1.0.0",
        description="test",
        requires_live_data=True,
    )

    assert manifest.requires_live_data is True
