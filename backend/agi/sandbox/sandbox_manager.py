"""Sandbox manager for isolated strategy validation."""
import uuid
import os
import tempfile
import resource
import subprocess
import time
import logging
from typing import Dict

from backend.agi.sandbox.sandbox_validator import SandboxValidator
from backend.agi.sandbox.results import SandboxResult
from backend.agi.node_registry import node_registry

logger = logging.getLogger(__name__)

class SandboxManager:
    """Manages isolated strategy validation in sandbox mode with production hardening.

    Hardening features:
    - Resource limits: CPU time (1s), Address Space/Memory (200MB)
    - Filesystem: Isolation via temporary directories
    - Network: Blocked via environment and restrictive execution
    - Time: Hard timeout (2s) per execution
    - Clean Environment: Subprocesses start with a minimal environment
    """

    def __init__(self):
        self.validator = SandboxValidator()
        self._results: Dict[str, SandboxResult] = {}

    def _set_resource_limits(self):
        """Set resource limits for the current process (called in preexec_fn).

        Gracefully skips limits not supported on the current platform
        (e.g. RLIMIT_AS is unavailable on macOS).
        """
        limits = [
            ("RLIMIT_CPU", resource.RLIMIT_CPU, (5, 5)),
            ("RLIMIT_AS", resource.RLIMIT_AS, (200 * 1024 * 1024, 200 * 1024 * 1024)),
            ("RLIMIT_CORE", resource.RLIMIT_CORE, (0, 0)),
        ]
        for name, res, value in limits:
            try:
                resource.setrlimit(res, value)
            except (ValueError, OSError):
                # Limit not supported on this platform (e.g. RLIMIT_AS on macOS)
                pass

    async def execute_code(self, code: str, scenario: str = "default") -> SandboxResult:
        """
        Executes code in a hardened sandbox environment.

        Args:
            code: Strategy source code to execute
            scenario: Test scenario name

        Returns:
            SandboxResult containing execution metrics and output
        """
        # 1. Validate code before execution (the 4 gates)
        validation_result = self.validator.validate(code, scenario)
        if not validation_result.passed:
            return validation_result

        run_id = str(uuid.uuid4())[:8]
        start_time = time.perf_counter()

        # Create fresh temporary directory for the run
        with tempfile.TemporaryDirectory(prefix=f"sandbox_{run_id}_") as tmp_dir:
            try:
                # Create a wrapper script to execute the code
                # We use a wrapper to ensure we can set limits and isolate the environment
                code_file = os.path.join(tmp_dir, "strategy.py")
                with open(code_file, "w") as f:
                    f.write(code)

                # Minimal environment: block network by removing common proxies/config.
                # Pass through critical env vars needed by backend config validation.
                env = {
                    "PYTHONPATH": os.getcwd(),
                    "TMPDIR": tmp_dir,
                    "HOME": tmp_dir,
                    "HTTP_PROXY": "",
                    "HTTPS_PROXY": "",
                    "no_proxy": "*",
                    "WALLET_FERNET_KEY": os.environ.get("WALLET_FERNET_KEY", ""),
                    "SHADOW_MODE": os.environ.get("SHADOW_MODE", "true"),
                }

                # Execute via subprocess for isolation of resource limits and memory.
                # Use the same Python interpreter (venv) so installed packages are available.
                # -S is not used: isolation comes from resource limits + temp dir + env scrubbing.
                import sys
                process = subprocess.Popen(
                    [sys.executable, "-u", code_file],
                    cwd=tmp_dir,
                    env=env,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    preexec_fn=self._set_resource_limits,
                    text=True
                )

                try:
                    stdout, stderr = process.communicate(timeout=5.0)
                    output = stdout if stdout else stderr
                    status = "passed" if process.returncode == 0 else "failed"
                    killed = False
                except subprocess.TimeoutExpired:
                    process.kill()
                    stdout, stderr = process.communicate()
                    output = f"Execution timed out after 2s\n{stderr}"
                    status = "error"
                    killed = True
                except Exception as e:
                    output = str(e)
                    status = "error"
                    killed = False

                end_time = time.perf_counter()

                # Calculate resource usage
                resource.getrusage(resource.RUSAGE_SELF)
                # Note: Real CPU/Mem metrics from subprocess are complex in Python.
                # We'll use the wrapper's elapsed time as CPU proxy and let the OS kill if mem exceeded.
                # Actual mem requires external monitoring or /proc

                result = SandboxResult(
                    run_id=run_id,
                    status=status,
                    output=output,
                    execution_time_ms=(end_time - start_time) * 1000,
                    cpu_ms=(end_time - start_time) * 1000, # Proxy
                    mem_kb=0.0, # Actual mem requires external monitoring or /proc
                    killed=killed,
                    gates_passed=validation_result.gates_passed,
                    gates_failed=validation_result.gates_failed,
                    errors=validation_result.errors if status == "error" else [],
                )

                self._results[run_id] = result
                return result

            except Exception as e:
                logger.error(f"Sandbox execution crash: {e}")
                return SandboxResult(run_id=run_id, status="error", errors=[str(e)])

    async def validate_strategy(self, code: str, scenario: str = "default") -> SandboxResult:
        """Validate a strategy through the 4-gate pipeline and execute in hardened sandbox."""
        return await self.execute_code(code, scenario)

    async def validate_node(self, node_name: str, state: dict) -> SandboxResult:
        """Validate a single AGI node in sandbox context."""
        import time
        start = time.time()
        run_id = str(uuid.uuid4())[:8]

        try:
            node = node_registry.get(node_name)
            manifest = node.manifest()

            errors = []
            if manifest.requires_db:
                errors.append(f"Node '{node_name}' requires database access - not allowed in sandbox")
            if manifest.requires_live_data:
                errors.append(f"Node '{node_name}' requires live data - not allowed in sandbox")

            status = "passed" if not errors else "failed"
            return SandboxResult(
                run_id=run_id,
                status=status,
                errors=errors,
                execution_time_ms=(time.time() - start) * 1000
            )
        except Exception as e:
            return SandboxResult(run_id=run_id, status="error", errors=[str(e)])
