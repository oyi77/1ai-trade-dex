"""Autonomous code improvement agent with safety gates and automatic rollback."""

import json
import os
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Tuple

from loguru import logger

from backend.ai.provider_registry import ProviderRegistry, AllProvidersExhausted
from backend.core.safety import SafetyMonitor, AlertSeverity
from backend.models.database import BotState, SessionLocal


class CodeRefactoringAgent:
    """Autonomous code refactoring with LLM-powered suggestions and safety gates."""

    # Paths requiring safety monitor approval
    PROTECTED_PATHS = {
        "backend/core/",
        "backend/strategies/",
    }

    def __init__(self):
        """Initialize the refactoring agent."""
        self.provider_registry = ProviderRegistry()
        self.safety_monitor = SafetyMonitor()
        self.logger = logger.bind(task="code_refactorer")

    def _is_protected_path(self, module_path: str) -> bool:
        """Check if a module path requires safety approval."""
        normalized = module_path.replace("\\", "/")
        return any(
            normalized.startswith(protected)
            for protected in self.PROTECTED_PATHS
        )

    async def propose_refactor(
        self, module_path: str, goal: str
    ) -> Optional[str]:
        """
        Propose a unified diff for code refactoring using LLM.

        Args:
            module_path: Path to the module to refactor
            goal: Description of desired improvements (e.g., "reduce complexity", "improve performance")

        Returns:
            Unified diff string if successful, None otherwise
        """
        if not os.path.exists(module_path):
            self.logger.error(f"Module not found: {module_path}")
            return None

        try:
            with open(module_path, "r") as f:
                current_code = f.read()
        except Exception as e:
            self.logger.error(f"Failed to read module {module_path}: {e}")
            return None

        # Construct prompt for LLM
        prompt = f"""Please propose code improvements for the following Python module.

Goal: {goal}

Current code:
```python
{current_code}
```

Provide your response as a unified diff (git format) that can be applied with the `patch` command.
Use --- and +++ headers with file paths, and ensure the diff is valid.

Important:
- Only include functional improvements, not trivial formatting changes
- Ensure all imports and dependencies are maintained
- Preserve all public API signatures
- Include meaningful context lines in the diff

Response format:
--- a/{module_path}
+++ b/{module_path}
@@ -line_start,count +line_start,count @@
 context line
-removed line
+added line
 context line
"""

        system_prompt = """You are an expert Python code refactorer.
Generate high-quality unified diffs that improve code quality while maintaining functionality.
Always output valid, applicable diffs."""

        try:
            # Try to get a provider from the registry
            available = self.provider_registry.list_available()
            if not available:
                self.logger.warning("No AI providers available for refactoring proposal")
                return None

            # Use the first available provider
            provider_name = available[0].name
            provider = self.provider_registry.get(provider_name)

            self.logger.info(
                f"Requesting refactor proposal from {provider_name}",
                goal=goal,
                module=module_path
            )

            diff = await provider.complete(
                prompt=prompt,
                system=system_prompt,
                max_tokens=4096,
                temperature=0.3,  # Lower temperature for more deterministic output
            )

            self.logger.info(
                "Received refactor proposal",
                diff_length=len(diff),
                module=module_path
            )

            return diff

        except AllProvidersExhausted:
            self.logger.error("All AI providers exhausted")
            return None
        except Exception as e:
            self.logger.error(f"Failed to propose refactor: {e}")
            return None

    def _validate_diff(self, diff: str) -> bool:
        """
        Validate that a diff is well-formed and safe to apply.

        Args:
            diff: Unified diff string

        Returns:
            True if valid, False otherwise
        """
        if not diff or not diff.strip():
            self.logger.warning("Diff is empty")
            return False

        # Check for required diff headers
        if "---" not in diff or "+++" not in diff:
            self.logger.warning("Diff missing file headers")
            return False

        # Basic sanity check: ensure hunks are present
        if "@@" not in diff:
            self.logger.warning("Diff missing hunk headers")
            return False

        return True

    def apply_refactor(self, module_path: str, diff: str) -> bool:
        """
        Apply a unified diff to the module after validation.

        Args:
            module_path: Path to the module to refactor
            diff: Unified diff string

        Returns:
            True if applied successfully, False otherwise
        """
        if not self._validate_diff(diff):
            self.logger.error("Diff validation failed")
            return False

        # Create backup before applying
        try:
            backup_path = f"{module_path}.backup"
            with open(module_path, "r") as src:
                with open(backup_path, "w") as dst:
                    dst.write(src.read())
            self.logger.info(f"Created backup at {backup_path}")
        except Exception as e:
            self.logger.error(f"Failed to create backup: {e}")
            return False

        # Apply diff using patch command
        try:
            # Write diff to temporary file
            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".patch", delete=False
            ) as f:
                f.write(diff)
                patch_file = f.name

            try:
                # E-134: Use context manager to avoid file handle leak
                with open(patch_file, "r") as patch_fh:
                    result = subprocess.run(
                        ["patch", "-p1", module_path],
                        stdin=patch_fh,
                        capture_output=True,
                        text=True,
                        timeout=30,
                    )

                if result.returncode != 0:
                    self.logger.error(
                        f"Patch command failed: {result.stderr}"
                    )
                    # Restore from backup
                    self._restore_backup(module_path, backup_path)
                    return False

                self.logger.info(f"Successfully applied diff to {module_path}")
                return True

            finally:
                # Clean up temp patch file
                if os.path.exists(patch_file):
                    os.unlink(patch_file)

        except Exception as e:
            self.logger.error(f"Failed to apply diff: {e}")
            self._restore_backup(module_path, backup_path)
            return False

    def _restore_backup(self, module_path: str, backup_path: str) -> None:
        """Restore a module from backup."""
        try:
            if os.path.exists(backup_path):
                with open(backup_path, "r") as src:
                    with open(module_path, "w") as dst:
                        dst.write(src.read())
                self.logger.info(f"Restored {module_path} from backup")
        except Exception as e:
            self.logger.error(f"Failed to restore backup: {e}")

    def run_module_tests(self, module_path: str) -> bool:
        """
        Run pytest for the given module.

        Args:
            module_path: Path to the module to test

        Returns:
            True if tests pass, False otherwise
        """
        # Convert module path to test path
        # e.g., backend/agi/code_refactorer.py -> backend/agi/tests/test_code_refactorer.py
        module_name = Path(module_path).stem
        module_dir = Path(module_path).parent
        test_path = module_dir / "tests" / f"test_{module_name}.py"

        if not test_path.exists():
            self.logger.warning(f"No tests found for {module_path} at {test_path}")
            # E-133: Return False when no tests exist — True was misleading
            return False

        try:
            self.logger.info(f"Running tests from {test_path}")
            result = subprocess.run(
                ["python", "-m", "pytest", str(test_path), "-xvs"],
                capture_output=True,
                text=True,
                timeout=120,
                cwd=".",
            )

            if result.returncode == 0:
                self.logger.info(f"Tests passed for {module_path}")
                return True
            else:
                self.logger.error(
                    f"Tests failed for {module_path}: {result.stdout}\n{result.stderr}"
                )
                return False

        except subprocess.TimeoutExpired:
            self.logger.error(f"Tests timed out for {module_path}")
            return False
        except Exception as e:
            self.logger.error(f"Failed to run tests: {e}")
            return False

    def rollback(self, module_path: str) -> bool:
        """
        Rollback changes to a module via git checkout.

        Args:
            module_path: Path to the module to rollback

        Returns:
            True if rollback successful, False otherwise
        """
        try:
            # First try to restore from backup if it exists
            backup_path = f"{module_path}.backup"
            if os.path.exists(backup_path):
                self._restore_backup(module_path, backup_path)
                os.unlink(backup_path)
                self.logger.info(f"Rolled back {module_path} from backup")
                return True

            # Otherwise use git
            result = subprocess.run(
                ["git", "checkout", module_path],
                capture_output=True,
                text=True,
                timeout=10,
            )

            if result.returncode == 0:
                self.logger.info(f"Rolled back {module_path} via git")
                return True
            else:
                self.logger.error(f"Failed to rollback {module_path}: {result.stderr}")
                return False

        except Exception as e:
            self.logger.error(f"Rollback failed: {e}")
            return False

    def _log_refactor_action(
        self,
        action: str,
        module_path: str,
        goal: str,
        success: bool,
        details: str = "",
    ) -> None:
        """Log refactoring action to BotState history."""
        try:
            db = SessionLocal()
            bot_state = db.query(BotState).filter(BotState.mode == "paper").first()
            if not bot_state:
                self.logger.warning("No BotState found for logging")
                db.close()
                return

            # Parse existing history
            history = []
            if bot_state.misc_data:
                try:
                    misc = json.loads(bot_state.misc_data)
                    history = misc.get("refactor_history", [])
                except json.JSONDecodeError:
                    history = []

            # Add new entry
            entry = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "action": action,
                "module_path": module_path,
                "goal": goal,
                "success": success,
                "details": details,
            }
            history.append(entry)

            # Keep last 100 entries
            history = history[-100:]

            # Update BotState
            misc = json.loads(bot_state.misc_data or "{}")
            misc["refactor_history"] = history
            bot_state.misc_data = json.dumps(misc)
            db.commit()

            self.logger.info(
                f"Logged refactor action: {action}",
                module=module_path,
                success=success,
            )

        except Exception as e:
            self.logger.error(f"Failed to log refactor action: {e}")
        finally:
            db.close()

    async def full_refactor_cycle(
        self, module_path: str, goal: str, require_approval: bool = False
    ) -> Tuple[bool, str]:
        """
        Execute a complete refactoring cycle:
        1. Propose refactor
        2. Validate diff
        3. Check safety gates
        4. Apply refactor
        5. Run tests
        6. Rollback on failure

        Args:
            module_path: Path to module
            goal: Refactoring goal
            require_approval: If True, require safety monitor approval for protected paths

        Returns:
            (success: bool, message: str)
        """
        self.logger.info(
            "Starting refactor cycle",
            module=module_path,
            goal=goal,
        )

        # Step 1: Propose refactor
        diff = await self.propose_refactor(module_path, goal)
        if not diff:
            msg = "Failed to propose refactor"
            self.logger.error(msg)
            self._log_refactor_action("propose", module_path, goal, False, msg)
            return False, msg

        # Step 2: Validate diff
        if not self._validate_diff(diff):
            msg = "Proposed diff failed validation"
            self.logger.error(msg)
            self._log_refactor_action("validate", module_path, goal, False, msg)
            return False, msg

        # Step 3: Check safety gates
        if self._is_protected_path(module_path) and require_approval:
            self.logger.warning(
                f"Module {module_path} requires safety approval",
                is_protected=True,
            )
            self.safety_monitor.record_alert(
                AlertSeverity.WARNING,
                f"Refactor requested for protected path: {module_path}",
                strategy_key="code_refactorer",
            )
            # For now, log but don't block. In production, this would require human approval.
            msg = "Protected path - manual approval required"
            self._log_refactor_action(
                "safety_gate", module_path, goal, False, msg
            )
            return False, msg

        # Step 4: Apply refactor
        if not self.apply_refactor(module_path, diff):
            msg = "Failed to apply refactor"
            self.logger.error(msg)
            self._log_refactor_action("apply", module_path, goal, False, msg)
            return False, msg

        # Step 5: Run tests
        tests_passed = self.run_module_tests(module_path)
        if not tests_passed:
            self.logger.error("Tests failed after refactor, rolling back")
            self.rollback(module_path)
            msg = "Tests failed after refactor - rolled back"
            self._log_refactor_action(
                "test_failed_rollback", module_path, goal, False, msg
            )
            return False, msg

        # Success!
        msg = "Refactor completed successfully"
        self.logger.info(msg, module=module_path)
        self._log_refactor_action("complete", module_path, goal, True, msg)
        return True, msg
