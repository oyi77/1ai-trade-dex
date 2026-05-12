"""Sandbox validation results."""
from dataclasses import dataclass, field
from datetime import datetime
from typing import List


@dataclass
class SandboxResult:
    """Result of a sandbox validation run."""
    run_id: str
    status: str  # "passed", "failed", "error"
    gates_passed: List[str] = field(default_factory=list)
    gates_failed: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    execution_time_ms: float = 0.0
    created_at: datetime = field(default_factory=datetime.now)

    @property
    def passed(self) -> bool:
        return self.status == "passed"

    def to_dict(self) -> dict:
        return {
            "run_id": self.run_id,
            "status": self.status,
            "gates_passed": self.gates_passed,
            "gates_failed": self.gates_failed,
            "errors": self.errors,
            "warnings": self.warnings,
            "execution_time_ms": self.execution_time_ms,
            "created_at": self.created_at.isoformat(),
        }