import pytest
from datetime import datetime, timezone

from backend.agi.agent_state import AgentState


class TestAgentState:
    def test_constructor_defaults(self):
        state = AgentState()

        assert state.run_id == ""
        assert state.graph_name == ""
        assert isinstance(state.created_at, datetime)
        assert state.data == {}
        assert state.errors == []
        assert state.metadata == {}
        assert state.is_sandbox is False

    def test_constructor_with_values(self):
        now = datetime.now(timezone.utc)
        state = AgentState(
            run_id="test-run-123",
            graph_name="test_graph",
            created_at=now,
            data={"key": "value"},
            errors=[{"node": "test", "error": "test error"}],
            metadata={"meta": "data"},
            is_sandbox=True,
        )

        assert state.run_id == "test-run-123"
        assert state.graph_name == "test_graph"
        assert state.created_at == now
        assert state.data == {"key": "value"}
        assert state.errors == [{"node": "test", "error": "test error"}]
        assert state.metadata == {"meta": "data"}
        assert state.is_sandbox is True

    def test_evolve_adds_data(self):
        state = AgentState(run_id="run-1", data={"existing": "value"})

        new_state = state.evolve(data={"new_key": "new_value"})

        assert new_state.data == {"existing": "value", "new_key": "new_value"}
        assert new_state.run_id == "run-1"

    def test_evolve_overrides_existing_data(self):
        state = AgentState(data={"key": "old_value"})

        new_state = state.evolve(data={"key": "new_value"})

        assert new_state.data == {"key": "new_value"}

    def test_evolve_adds_errors(self):
        state = AgentState(errors=[{"error": "first"}])

        new_state = state.evolve(errors=[{"error": "second"}])

        assert len(new_state.errors) == 2
        assert new_state.errors[0] == {"error": "first"}
        assert new_state.errors[1] == {"error": "second"}

    def test_evolve_keeps_original_unchanged(self):
        state = AgentState(data={"key": "original"})

        new_state = state.evolve(data={"key": "updated"})

        assert state.data == {"key": "original"}
        assert new_state.data == {"key": "updated"}

    def test_evolve_updates_metadata(self):
        state = AgentState(metadata={"existing": "value"})

        new_state = state.evolve(metadata={"new": "value"})

        assert new_state.metadata == {"existing": "value", "new": "value"}

    def test_with_error_adds_error_entry(self):
        state = AgentState(run_id="run-1")

        new_state = state.with_error("test_node", ValueError("test error"))

        assert len(new_state.errors) == 1
        assert new_state.errors[0]["node"] == "test_node"
        assert "test error" in new_state.errors[0]["error"]
        assert "timestamp" in new_state.errors[0]

    def test_get_method_retrieves_data(self):
        state = AgentState(data={"key": "value"})

        assert state.get("key") == "value"
        assert state.get("nonexistent") is None
        assert state.get("nonexistent", "default") == "default"

    def test_repr_output(self):
        state = AgentState(
            run_id="run-1",
            graph_name="test_graph",
            data={"key": "value"},
            is_sandbox=True,
        )

        repr_str = repr(state)

        assert "run-1" in repr_str
        assert "test_graph" in repr_str
        assert "['key']" in repr_str
        assert "True" in repr_str

    def test_evolve_changes_run_id(self):
        state = AgentState(run_id="old-run")

        new_state = state.evolve(run_id="new-run")

        assert state.run_id == "old-run"
        assert new_state.run_id == "new-run"

    def test_evolve_changes_graph_name(self):
        state = AgentState(graph_name="old_graph")

        new_state = state.evolve(graph_name="new_graph")

        assert state.graph_name == "old_graph"
        assert new_state.graph_name == "new_graph"

    def test_evolve_preserves_created_at(self):
        now = datetime.now(timezone.utc)
        state = AgentState(created_at=now)

        new_state = state.evolve(data={"new": "data"})

        assert new_state.created_at == now

    def test_evolve_changes_is_sandbox(self):
        state = AgentState(is_sandbox=False)

        new_state = state.evolve(is_sandbox=True)

        assert state.is_sandbox is False
        assert new_state.is_sandbox is True


def test_agent_state_is_sandbox_flag():
    sandbox_state = AgentState(is_sandbox=True)
    regular_state = AgentState(is_sandbox=False)

    assert sandbox_state.is_sandbox is True
    assert regular_state.is_sandbox is False
