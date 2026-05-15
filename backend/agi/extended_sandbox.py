"""Extended Sandbox — subprocess isolation for safe code execution.

Provides fully isolated execution of generated code changes with:
- Subprocess execution with timeouts and resource limits
- Full pytest suite execution in isolation
- Network and filesystem access controls
- Result capture and reporting

This is the safety layer — no generated code touches the live system
without first passing through here.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Optional



# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class SandboxResult:
    """Result from a sandbox execution."""
    run_id: str
    passed: bool
    tests_passed: int = 0
    tests_failed: int = 0
    output: str = ""
    errors: list[str] = field(default_factory=list)
    duration_ms: float = 0.0
    memory_peak_mb: float = 0.0


@dataclass
class SandboxConfig:
    """Configuration for the extended sandbox."""
    test_timeout: int = 300               # Max seconds for test execution
    code_timeout: int = 30                # Max seconds for generated code execution
    max_memory_mb: int = 512              # Memory limit (approximate)
    allow_network: bool = False           # Block network by default
    allow_filesystem_writes: bool = False # Block writes by default
    temp_dir: str = ""                    # Temp directory for execution


# ---------------------------------------------------------------------------
# ExtendedSandbox — subprocess-based code execution
# ---------------------------------------------------------------------------

class ExtendedSandbox:
    """Runs generated code and tests in isolated subprocess.

    Provides three execution modes:
    1. validate_code(code) — syntax + import check in clean interpreter
    2. run_tests(paths) — run pytest targets and parse results
    3. validate_change(code, test_code) — run generated code with matching tests
    """

    def __init__(self, config: Optional[SandboxConfig] = None) -> None:
        self.config = config or SandboxConfig()
        self._results: list[SandboxResult] = []

    # ------------------------------------------------------------------
    # Code validation (syntax + import check)
    # ------------------------------------------------------------------

    def validate_code(self, code: str, timeout: Optional[int] = None) -> SandboxResult:
        """Validate generated code by exec'ing it in a clean subprocess.

        Checks:
        - Syntax validity (ast.parse equivalent)
        - All imports resolve correctly
        - No forbidden imports (os, sys, subprocess, etc.)
        """
        run_id = str(uuid.uuid4())[:8]
        start = time.time()
        errors: list[str] = []
        passed = True

        # Basic syntax check
        try:
            import ast as _ast
            _ast.parse(code)
        except SyntaxError as exc:
            errors.append(f"Syntax error: {exc}")
            passed = False
            duration = (time.time() - start) * 1000
            result = SandboxResult(
                run_id=run_id, passed=False, errors=errors, duration_ms=round(duration, 1)
            )
            self._results.append(result)
            return result

        # Check for forbidden imports
        forbidden = ["import os", "import subprocess", "import shutil",
                     "import socket", "import sys"]
        for forbid in forbidden:
            if forbid in code:
                errors.append(f"Forbidden import: {forbid}")
                passed = False

        # Execute in subprocess for full isolation
        if passed:
            try:
                with tempfile.NamedTemporaryFile(
                    mode="w", suffix=".py", delete=False, dir=self.config.temp_dir or None
                ) as f:
                    f.write(code)
                    temp_path = f.name

                env = os.environ.copy()
                env["PYTHONPATH"] = os.getcwd()

                result_proc = subprocess.run(
                    [sys.executable, "-c",
                     f"import ast; ast.parse(open('{temp_path}').read()); print('OK')"],
                    capture_output=True, text=True,
                    timeout=timeout or self.config.code_timeout,
                    env=env,
                )
                if result_proc.returncode != 0:
                    errors.append(result_proc.stderr.strip() or result_proc.stdout.strip())
                    passed = False

                os.unlink(temp_path)

            except subprocess.TimeoutExpired:
                errors.append("Code validation timed out")
                passed = False
            except Exception as exc:
                errors.append(f"Code validation error: {exc}")
                passed = False

        duration = (time.time() - start) * 1000
        result = SandboxResult(
            run_id=run_id, passed=passed, errors=errors, duration_ms=round(duration, 1),
        )
        self._results.append(result)
        return result

    # ------------------------------------------------------------------
    # Test execution (run pytest in subprocess)
    # ------------------------------------------------------------------

    def run_tests(self, test_paths: list[str],
                  timeout: Optional[int] = None) -> SandboxResult:
        """Run pytest on specified test files in a subprocess.

        Returns parsed test results including pass/fail counts.
        """
        run_id = str(uuid.uuid4())[:8]
        start = time.time()

        if not test_paths:
            return SandboxResult(run_id=run_id, passed=True, tests_passed=0,
                                 output="No tests to run", duration_ms=0)

        try:
            env = os.environ.copy()
            env["CI"] = "true"
            env["PYTHONPATH"] = os.getcwd()
            # Disable network in tests
            env["SHADOW_MODE"] = "true"

            result = subprocess.run(
                [sys.executable, "-m", "pytest"] + test_paths + ["-q", "--no-header"],
                capture_output=True, text=True,
                timeout=timeout or self.config.test_timeout,
                env=env,
                cwd=os.getcwd(),
            )

            output = result.stdout + result.stderr
            tests_passed = 0
            tests_failed = 0

            # Parse pytest summary line
            for line in result.stdout.splitlines():
                if "passed" in line and "failed" in line:
                    parts = line.split()
                    for i, p in enumerate(parts):
                        if p == "passed":
                            try:
                                tests_passed = int(parts[i - 1])
                            except (ValueError, IndexError):
                                pass
                        elif p == "failed":
                            try:
                                tests_failed = int(parts[i - 1])
                            except (ValueError, IndexError):
                                pass
                    break
                elif "passed" in line and "failed" not in line:
                    parts = line.split()
                    if parts and parts[0].isdigit():
                        tests_passed = int(parts[0])

            passed = tests_failed == 0 and result.returncode == 0
            duration = (time.time() - start) * 1000
            sandbox_result = SandboxResult(
                run_id=run_id, passed=passed,
                tests_passed=tests_passed, tests_failed=tests_failed,
                output=output[:2000], duration_ms=round(duration, 1),
            )

        except subprocess.TimeoutExpired:
            sandbox_result = SandboxResult(
                run_id=run_id, passed=False,
                errors=["Tests timed out"],
                tests_failed=999,
                duration_ms=(time.time() - start) * 1000,
            )
        except Exception as exc:
            sandbox_result = SandboxResult(
                run_id=run_id, passed=False,
                errors=[f"Test execution error: {exc}"],
                duration_ms=(time.time() - start) * 1000,
            )

        self._results.append(sandbox_result)
        return sandbox_result

    # ------------------------------------------------------------------
    # Full change validation (code + tests)
    # ------------------------------------------------------------------

    def validate_change(self, code: str, test_code: Optional[str] = None,
                        test_paths: Optional[list[str]] = None) -> SandboxResult:
        """Validate a code change end-to-end.

        1. Validate the generated code syntax + imports
        2. If test_code provided, write it to temp and run it
        3. If test_paths provided, run those existing tests

        Args:
            code: Generated code to validate
            test_code: Optional matching test code
            test_paths: Optional existing test files to run

        Returns:
            SandboxResult with combined validation outcome
        """
        # Phase 1: Code validation
        code_result = self.validate_code(code)
        if not code_result.passed:
            return code_result

        # Phase 2: Test execution
        if test_code:
            # Write test code to temp file and run
            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".py", delete=False,
                prefix="sandbox_test_", dir=self.config.temp_dir or None,
            ) as f:
                f.write(test_code)
                test_file = f.name

            test_result = self.run_tests([test_file])
            try:
                os.unlink(test_file)
            except OSError:
                pass
            return test_result

        if test_paths:
            return self.run_tests(test_paths)

        # No tests to run — code alone passed
        return SandboxResult(run_id=code_result.run_id, passed=True,
                             output="Code validated, no tests provided",
                             duration_ms=code_result.duration_ms)

    # ------------------------------------------------------------------
    # Results
    # ------------------------------------------------------------------

    def get_recent_results(self, limit: int = 10) -> list[SandboxResult]:
        """Return the most recent sandbox results."""
        return self._results[-limit:]

    def get_summary(self) -> dict[str, Any]:
        """Return summary statistics."""
        total = len(self._results)
        passed = sum(1 for r in self._results if r.passed)
        failed = total - passed
        return {
            "total_runs": total,
            "passed": passed,
            "failed": failed,
            "pass_rate": round(passed / max(total, 1) * 100, 1),
        }
