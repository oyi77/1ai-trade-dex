"""AGI node abstract base class and manifest."""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import List

from backend.core.plugin_registry import BasePlugin


@dataclass
class NodeManifest:
    """Declarative metadata for an AGI node plugin."""
    name: str
    version: str
    description: str
    input_keys: List[str] = field(default_factory=list)
    output_keys: List[str] = field(default_factory=list)
    requires_db: bool = False
    requires_live_data: bool = False
    tags: List[str] = field(default_factory=list)


class BaseAGINode(BasePlugin, ABC):
    """Abstract base class for all AGI graph nodes.

    Each node receives an AgentState, performs its logic, and returns
    an updated AgentState. Nodes declare their input/output keys via
    the manifest, and the graph engine validates data availability
    before execution.
    """

    @classmethod
    @abstractmethod
    def manifest(cls) -> NodeManifest:
        """Return the node's static metadata."""
        ...

    @abstractmethod
    async def execute(self, state: "AgentState") -> "AgentState":
        """Execute the node's logic and return updated state."""
        ...

    def can_execute(self, state: "AgentState") -> bool:
        """Check if all required input keys exist in state data."""
        manifest = self.manifest()
        return all(key in state.data for key in manifest.input_keys)

    async def teardown(self) -> None:
        """Called when the node is detached. Override for cleanup."""
        pass