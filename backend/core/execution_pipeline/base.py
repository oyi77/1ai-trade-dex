"""Base classes for execution pipeline stages."""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import List


@dataclass
class ExecutionStageManifest:
    """Declarative metadata for an execution pipeline stage."""
    name: str
    display_name: str
    version: str
    mode: str
    order: int
    required_env_vars: List[str] = field(default_factory=list)
    tags: List[str] = field(default_factory=list)


class BaseExecutionStage(ABC):
    """Abstract base class for all execution pipeline stages."""

    @classmethod
    @abstractmethod
    def manifest(cls) -> ExecutionStageManifest:
        """Return the stage's static metadata."""
        ...

    def validate(self, decision: dict, ctx: dict) -> bool:
        """Pre-execution validation. Override to check decision validity.

        Args:
            decision: Trade decision dict with market_ticker, direction, size, etc.
            ctx: Execution context dict with mode, bankroll, current_exposure, etc.

        Returns:
            True if decision passes validation, False otherwise
        """
        return True

    def execute(self, decision: dict, ctx: dict) -> dict:
        """Execute the decision. Override to perform stage-specific execution.

        Args:
            decision: Trade decision dict with market_ticker, direction, size, etc.
            ctx: Execution context dict with mode, bankroll, current_exposure, etc.

        Returns:
            Execution result dict with status, order_id, fill_price, etc.
        """
        return {"status": "completed"}

    def record(self, decision: dict, result: dict, ctx: dict) -> None:
        """Record the execution result. Override to persist trade/attempt data.

        Args:
            decision: Trade decision dict
            result: Execution result dict from execute()
            ctx: Execution context dict
        """
        pass

    def health_check(self) -> bool:
        """Optional liveness probe. Override to check stage dependencies.

        Returns:
            True if healthy, False otherwise
        """
        return True

    async def teardown(self) -> None:
        """Called when the stage is detached. Close connections, flush caches."""
        pass
