"""Sandbox manager for isolated strategy validation."""
import uuid
from typing import Optional

from backend.agi.sandbox.sandbox_validator import SandboxValidator
from backend.agi.sandbox.results import SandboxResult
from backend.agi.node_registry import node_registry


class SandboxManager:
    """Manages isolated strategy validation in sandbox mode.

    The sandbox guarantees:
    - No live DB access
    - No live market provider calls
    - Only mock data sources are available
    - All code passes 4-gate validation before execution
    """

    def __init__(self):
        self.validator = SandboxValidator()
        self._results: dict[str, SandboxResult] = {}

    async def validate_strategy(self, code: str, scenario: str = "default") -> SandboxResult:
        """Validate a strategy through the 4-gate pipeline.

        Args:
            code: Strategy source code to validate
            scenario: Test scenario name (e.g., "bull_2024", "bear_market")

        Returns:
            SandboxResult with gate pass/fail status
        """
        result = self.validator.validate(code, scenario)
        self._results[result.run_id] = result
        return result

    async def validate_node(self, node_name: str, state: dict) -> SandboxResult:
        """Validate a single AGI node in sandbox context.

        Checks that the node doesn't require DB or live data access.
        """
        import time

        start = time.time()
        run_id = str(uuid.uuid4())[:8]

        try:
            node = node_registry.get(node_name)
            manifest = node.manifest()

            errors = []
            if manifest.requires_db:
                errors.append(f"Node '{node_name}' requires database access (forbidden in sandbox)")
            if manifest.requires_live_data:
                errors.append(f"Node '{node_name}' requires live data (forbidden in sandbox)")

            result = SandboxResult(
                run_id=run_id,
                status="passed" if not errors else "failed",
                gates_passed=["node_sandbox_check"] if not errors else [],
                gates_failed=[],
                errors=errors,
                execution_time_ms=(time.time() - start) * 1000,
            )
            self._results[run_id] = result
            return result

        except KeyError as e:
            result = SandboxResult(
                run_id=run_id,
                status="error",
                errors=[f"Node not found: {e}"],
                execution_time_ms=(time.time() - start) * 1000,
            )
            self._results[run_id] = result
            return result

    def get_result(self, run_id: str) -> Optional[SandboxResult]:
        """Retrieve a previous validation result."""
        return self._results.get(run_id)

    def list_results(self) -> list[SandboxResult]:
        """List all validation results."""
        return list(self._results.values())


# Module-level singleton
sandbox_manager = SandboxManager()