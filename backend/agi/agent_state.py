"""AGI core infrastructure: AgentState, BaseAGINode, NodeRegistry, GraphEngine."""
from datetime import datetime, timezone
from typing import Any


class AgentState:
    """Immutable agent state passed through the AGI graph.

    Attributes:
        run_id: Unique identifier for this execution run
        graph_name: Name of the graph being executed
        created_at: Timestamp of state creation
        data: Dictionary of key-value data passed between nodes
        errors: List of errors encountered during execution
        metadata: Additional metadata about the execution
        is_sandbox: Whether this state is executing in sandbox mode
    """

    def __init__(
        self,
        run_id: str = "",
        graph_name: str = "",
        created_at: datetime | None = None,
        data: dict | None = None,
        errors: list | None = None,
        metadata: dict | None = None,
        is_sandbox: bool = False,
    ):
        self.run_id = run_id
        self.graph_name = graph_name
        self.created_at = created_at or datetime.now(timezone.utc)
        self.data = data or {}
        self.errors = errors or []
        self.metadata = metadata or {}
        self.is_sandbox = is_sandbox

    def evolve(self, **updates) -> "AgentState":
        """Return a new AgentState with the given updates applied."""
        new_data = {**self.data, **updates.pop("data", {})}
        new_errors = list(self.errors) + updates.pop("errors", [])
        new_metadata = {**self.metadata, **updates.pop("metadata", {})}

        return AgentState(
            run_id=updates.pop("run_id", self.run_id),
            graph_name=updates.pop("graph_name", self.graph_name),
            created_at=updates.pop("created_at", self.created_at),
            data=new_data,
            errors=new_errors,
            metadata=new_metadata,
            is_sandbox=updates.pop("is_sandbox", self.is_sandbox),
        )

    def with_error(self, node_name: str, error: Exception) -> "AgentState":
        """Return a new state with an error added."""
        return self.evolve(errors=[{"node": node_name, "error": str(error), "timestamp": datetime.now(timezone.utc).isoformat()}])

    def get(self, key: str, default: Any = None) -> Any:
        """Dict-like access to state data."""
        return self.data.get(key, default)

    def __repr__(self) -> str:
        return f"AgentState(run_id={self.run_id!r}, graph={self.graph_name!r}, keys={list(self.data.keys())}, sandbox={self.is_sandbox})"
