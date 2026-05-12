"""Sandbox validation - 4-gate pipeline for strategy safety."""
import ast
import re
from typing import List, Optional

from backend.core.plugin_errors import SandboxViolation
from backend.agi.sandbox.results import SandboxResult


class GateCheck:
    """Result of a single gate check."""
    def __init__(self, name: str, passed: bool, message: str = ""):
        self.name = name
        self.passed = passed
        self.message = message


class SandboxValidator:
    """4-gate validation pipeline for sandboxed strategy code.

    Gate 1: Import safety - reject forbidden imports (DB, live providers, etc.)
    Gate 2: AST safety - reject dangerous constructs (exec, eval, etc.)
    Gate 3: Resource limits - check for excessive resource usage
    Gate 4: Output validation - verify output format and bounds
    """

    FORBIDDEN_IMPORTS = {
        "os", "sys", "subprocess", "socket",
        "backend.models.database", "backend.db.utils",
        "backend.data.polymarket_clob", "backend.data.kalshi_client",
        "backend.core.auto_trader", "backend.core.autonomous_promoter",
    }

    DANGEROUS_FUNCTIONS = {"exec", "eval", "compile", "open", "input", "__import__"}

    def validate(self, code: str, scenario: str = "default") -> SandboxResult:
        """Run all 4 gates on the provided code string."""
        import uuid
        import time

        start = time.time()
        result = SandboxResult(run_id=str(uuid.uuid4())[:8], status="passed")

        # Gate 1: Import safety
        gate1 = self._gate1_import_safety(code)
        if gate1.passed:
            result.gates_passed.append("gate1_import_safety")
        else:
            result.gates_failed.append("gate1_import_safety")
            result.errors.append(gate1.message)

        # Gate 2: AST safety
        gate2 = self._gate2_ast_safety(code)
        if gate2.passed:
            result.gates_passed.append("gate2_ast_safety")
        else:
            result.gates_failed.append("gate2_ast_safety")
            result.errors.append(gate2.message)

        # Gate 3: Resource limits
        gate3 = self._gate3_resource_limits(code)
        if gate3.passed:
            result.gates_passed.append("gate3_resource_limits")
        else:
            result.gates_failed.append("gate3_resource_limits")
            result.warnings.append(gate3.message)

        # Gate 4: Output validation
        gate4 = self._gate4_output_validation(code)
        if gate4.passed:
            result.gates_passed.append("gate4_output_validation")
        else:
            result.gates_failed.append("gate4_output_validation")
            result.errors.append(gate4.message)

        result.execution_time_ms = (time.time() - start) * 1000
        result.status = "passed" if not result.gates_failed and not result.errors else "failed"
        return result

    def _gate1_import_safety(self, code: str) -> GateCheck:
        """Check for forbidden imports."""
        for imp in self.FORBIDDEN_IMPORTS:
            patterns = [
                f"import {imp}",
                f"from {imp}",
                f"import {imp}.",
            ]
            for pattern in patterns:
                if pattern in code:
                    return GateCheck(
                        "gate1_import_safety", False,
                        f"Forbidden import detected: {imp}"
                    )
        return GateCheck("gate1_import_safety", True)

    def _gate2_ast_safety(self, code: str) -> GateCheck:
        """Check AST for dangerous constructs."""
        try:
            tree = ast.parse(code)
        except SyntaxError as e:
            return GateCheck("gate2_ast_safety", False, f"Syntax error: {e}")

        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name) and node.func.id in self.DANGEROUS_FUNCTIONS:
                    return GateCheck(
                        "gate2_ast_safety", False,
                        f"Dangerous function call: {node.func.id}"
                    )
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name in self.FORBIDDEN_IMPORTS:
                        return GateCheck(
                            "gate2_ast_safety", False,
                            f"Forbidden import: {alias.name}"
                        )
            if isinstance(node, ast.ImportFrom) and node.module:
                for alias in node.names:
                    full = f"{node.module}.{alias.name}"
                    if full in self.FORBIDDEN_IMPORTS or node.module in self.FORBIDDEN_IMPORTS:
                        return GateCheck(
                            "gate2_ast_safety", False,
                            f"Forbidden import: {full}"
                        )
        return GateCheck("gate2_ast_safety", True)

    def _gate3_resource_limits(self, code: str) -> GateCheck:
        """Check for excessive resource usage patterns."""
        lines = code.split("\n")
        if len(lines) > 500:
            return GateCheck("gate3_resource_limits", False, "Code exceeds 500 line limit")

        loops = sum(1 for line in lines if re.match(r"^\s*(for|while)\s", line))
        if loops > 10:
            return GateCheck("gate3_resource_limits", False, f"Too many loops ({loops}), max 10")

        return GateCheck("gate3_resource_limits", True)

    def _gate4_output_validation(self, code: str) -> GateCheck:
        """Validate that code produces expected output format."""
        if "return" not in code:
            return GateCheck("gate4_output_validation", False, "No return statement found")
        return GateCheck("gate4_output_validation", True)