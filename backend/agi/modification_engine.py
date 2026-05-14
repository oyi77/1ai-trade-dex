"""Modification Engine — safe, git-based code modifications with LLM generation.

Provides:
- SafeModifier: creates git branches, applies changes, runs validation, merges
- CodeGenerator: generates code changes via LLM (wraps existing StrategyComposer)
- ChangeTracker: records what changed and why for rollback

Every modification is:
1. Branched from current HEAD
2. Validated via pytest in subprocess
3. Either merged (all tests pass) or abandoned (failures)
"""

from __future__ import annotations

import ast
import json
import os
import subprocess
import time
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Optional

from loguru import logger


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

class ChangeType(Enum):
    STRATEGY = "strategy"
    MODULE = "module"
    DATA_SOURCE = "data_source"
    CONFIG = "config"
    PERFORMANCE = "performance"
    TEST = "test"
    REFACTOR = "refactor"
    FIX = "fix"


class ChangeStatus(Enum):
    PROPOSED = "proposed"
    BRANCHED = "branched"
    APPLIED = "applied"
    VALIDATED = "validated"
    MERGED = "merged"
    ABANDONED = "abandoned"
    ROLLED_BACK = "rolled_back"


@dataclass
class CodeChange:
    """A proposed modification to the codebase."""
    change_id: str
    change_type: ChangeType
    title: str
    description: str
    files_modified: list[str]           # Relative paths
    diff_summary: str                   # Short description of each change
    motivation: str                     # Why this change is needed
    risk_level: str                     # "low", "medium", "high"
    status: ChangeStatus = ChangeStatus.PROPOSED
    branch_name: str = ""
    validation_results: dict[str, Any] = field(default_factory=lambda: {
        "tests_passed": 0,
        "tests_failed": 0,
        "lint_errors": 0,
        "validation_log": [],
    })
    created_at: float = field(default_factory=time.time)
    merged_at: Optional[float] = None


@dataclass
class GeneratedCode:
    """Output from an LLM code generation request."""
    code: str
    file_path: str                  # Where to write the file
    strategy_name: str = ""
    imports_needed: list[str] = field(default_factory=list)
    confidence: float = 0.0         # 0-1
    explanation: str = ""


# ---------------------------------------------------------------------------
# SafeModifier — git-branch → modify → validate → merge
# ---------------------------------------------------------------------------

class SafeModifier:
    """Applies code changes with git-based safety guarantees.

    Flow:
        1. Create branch from current HEAD
        2. Apply changes
        3. Run pytest on affected modules
        4. Merge if all tests pass, abandon if not
    """

    def __init__(self, repo_path: str | None = None) -> None:
        self.repo_path = Path(repo_path) if repo_path else Path.cwd()
        self._git_dir = self.repo_path / ".git"
        self.history: list[CodeChange] = []

    # ------------------------------------------------------------------
    # Git operations
    # ------------------------------------------------------------------

    def _run_git(self, *args: str, check: bool = True) -> subprocess.CompletedProcess:
        """Run a git command in the repo directory."""
        return subprocess.run(
            ["git"] + list(args),
            cwd=str(self.repo_path),
            capture_output=True,
            text=True,
            timeout=30,
            check=check,
        )

    def _current_branch(self) -> str:
        result = self._run_git("rev-parse", "--abbrev-ref", "HEAD")
        return result.stdout.strip()

    def _create_branch(self, change_id: str) -> str:
        """Create a feature branch from current HEAD."""
        base = self._current_branch()
        branch = f"agi-improve/{change_id[:12]}"
        self._run_git("checkout", "-b", branch)
        logger.info("[SafeModifier] Created branch '{}' from '{}'", branch, base)
        return branch

    def _commit_changes(self, message: str) -> bool:
        """Stage all changes and commit."""
        self._run_git("add", "-A")
        result = self._run_git("diff", "--cached", "--stat")
        if not result.stdout.strip():
            logger.info("[SafeModifier] No changes to commit")
            self._run_git("checkout", "-")  # back to original branch
            return False
        self._run_git("commit", "-m", message)
        return True

    def _merge_back(self, branch: str) -> bool:
        """Merge the feature branch back to the original branch."""
        original = self._run_git("rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
        base = self._run_git("rev-parse", "HEAD").stdout.strip()
        self._run_git("checkout", original.replace(branch, "").strip() or "main")
        try:
            self._run_git("merge", branch, "--no-ff", "-m",
                          f"agi-merge: {branch}")
            logger.info("[SafeModifier] Merged '{}' into main", branch)
            return True
        except subprocess.CalledProcessError:
            logger.warning("[SafeModifier] Merge conflict in '{}' — aborting merge", branch)
            self._run_git("merge", "--abort", check=False)
            return False

    def _abandon_branch(self, branch: str) -> None:
        """Delete the feature branch without merging."""
        original = self._run_git("rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
        # If we're on the branch, go back
        if original == branch:
            self._run_git("checkout", "-", check=False)
        self._run_git("branch", "-D", branch, check=False)
        logger.info("[SafeModifier] Abandoned branch '{}'", branch)

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    def run_tests(self, affected_files: list[str]) -> dict[str, Any]:
        """Run pytest on files related to the change."""
        results = {"tests_passed": 0, "tests_failed": 0, "output": "", "validation_log": []}

        # Find test files for the affected modules
        test_targets = []
        for f in affected_files:
            module_name = Path(f).stem
            # Check root tests/
            root_test = self.repo_path / "tests" / f"test_{module_name}.py"
            if root_test.exists():
                test_targets.append(str(root_test))
            # Check backend/tests/
            backend_test = self.repo_path / "backend/tests" / f"test_{module_name}.py"
            if backend_test.exists():
                test_targets.append(str(backend_test))

        if not test_targets:
            # Fall back to full backend test suite
            test_targets = ["backend/tests/"]

        try:
            env = os.environ.copy()
            env["CI"] = "true"
            result = subprocess.run(
                ["python", "-m", "pytest"] + test_targets + ["-q", "--no-header"],
                cwd=str(self.repo_path),
                capture_output=True,
                text=True,
                timeout=180,
                env=env,
            )
            results["output"] = result.stdout + result.stderr

            # Parse pytest summary
            for line in result.stdout.splitlines():
                if "passed" in line and "failed" in line:
                    parts = line.split()
                    for i, p in enumerate(parts):
                        if p == "passed":
                            results["tests_passed"] = int(parts[i - 1]) if i > 0 else 0
                        elif p == "failed":
                            results["tests_failed"] = int(parts[i - 1]) if i > 0 else 0
                    break

            results["validation_log"].append(
                f"Tests: {results['tests_passed']} passed, {results['tests_failed']} failed"
            )
        except subprocess.TimeoutExpired:
            results["validation_log"].append("Tests timed out after 180s")
            results["tests_failed"] = 999
        except Exception as exc:
            results["validation_log"].append(f"Test error: {exc}")
            results["tests_failed"] = 999

        return results

    # ------------------------------------------------------------------
    # Main API
    # ------------------------------------------------------------------

    def propose_change(self, change_type: ChangeType, title: str,
                       description: str, files_modified: list[str],
                       diff_summary: str, motivation: str,
                       risk_level: str = "medium") -> CodeChange:
        """Create a change proposal without applying it."""
        change = CodeChange(
            change_id=str(uuid.uuid4())[:16],
            change_type=change_type,
            title=title,
            description=description,
            files_modified=files_modified,
            diff_summary=diff_summary,
            motivation=motivation,
            risk_level=risk_level,
        )
        self.history.append(change)
        return change

    def apply_change(self, change: CodeChange,
                     callback) -> CodeChange:
        """Apply a change using git branch → modify → validate → merge flow.

        Args:
            change: The proposed change
            callback: Function that applies the actual file edits.
                      Receives (change, repo_path) and returns True on success.

        Returns:
            The updated CodeChange with final status
        """
        original_branch = self._current_branch()
        change.status = ChangeStatus.BRANCHED
        change.branch_name = self._create_branch(change.change_id)

        try:
            # Apply the actual code changes via callback
            change.status = ChangeStatus.APPLIED
            if not callback(change, str(self.repo_path)):
                logger.warning("[SafeModifier] Callback returned False for '{}'", change.change_id)
                self._abandon_branch(change.branch_name)
                change.status = ChangeStatus.ABANDONED
                return change

            # Commit
            if not self._commit_changes(
                f"agi({change.change_type.value}): {change.title}"
            ):
                change.status = ChangeStatus.ABANDONED
                return change

            # Validate
            results = self.run_tests(change.files_modified)
            change.validation_results = results
            change.status = ChangeStatus.VALIDATED

            if results["tests_failed"] == 0:
                # Merge
                if self._merge_back(change.branch_name):
                    change.status = ChangeStatus.MERGED
                    change.merged_at = time.time()
                    logger.info("[SafeModifier] MERGED: {} — {}", change.change_id, change.title)
                else:
                    change.status = ChangeStatus.ABANDONED
            else:
                logger.warning("[SafeModifier] FAILED: {} — {} tests failed",
                               change.change_id, results["tests_failed"])
                self._abandon_branch(change.branch_name)
                change.status = ChangeStatus.ABANDONED

        except Exception as exc:
            logger.error("[SafeModifier] Error applying change '{}': {}", change.change_id, exc)
            self._abandon_branch(change.branch_name)
            change.status = ChangeStatus.ABANDONED
        finally:
            # Return to original branch
            if self._current_branch() != original_branch:
                self._run_git("checkout", original_branch, check=False)

        return change

    def get_change(self, change_id: str) -> Optional[CodeChange]:
        """Look up a change by ID."""
        for c in self.history:
            if c.change_id == change_id:
                return c
        return None

    def get_stats(self) -> dict[str, int]:
        """Return summary statistics of all changes."""
        stats = {
            "total": len(self.history),
            "merged": sum(1 for c in self.history if c.status == ChangeStatus.MERGED),
            "abandoned": sum(1 for c in self.history if c.status == ChangeStatus.ABANDONED),
            "rolled_back": sum(1 for c in self.history if c.status == ChangeStatus.ROLLED_BACK),
        }
        return stats


# ---------------------------------------------------------------------------
# CodeGenerator — LLM-powered code generation
# ---------------------------------------------------------------------------

class CodeGenerator:
    """Generates code changes via LLM with validation gates.

    Wraps the existing StrategyComposer / strategy_synthesizer infrastructure
    for code-level generation across all module types.
    """

    def __init__(self) -> None:
        self._generation_count = 0

    async def generate_module(self, description: str,
                              target_path: str,
                              context: Optional[str] = None) -> Optional[GeneratedCode]:
        """Generate a new module or modify an existing one via LLM.

        Args:
            description: What the module should do
            target_path: Where to write it (relative to repo root)
            context: Optional context from codebase scanner (dependencies, etc.)

        Returns:
            GeneratedCode if successful, None on failure
        """
        self._generation_count += 1
        try:
            from backend.ai.strategy_composer import StrategyComposer
            composer = StrategyComposer()

            prompt = (
                f"Generate Python code for a new module at {target_path}.\n"
                f"Purpose: {description}\n"
            )
            if context:
                prompt += f"Context: {context}\n"
            prompt += (
                "Requirements:\n"
                "- Use proper type annotations\n"
                "- Use loguru for logging\n"
                "- Handle errors gracefully\n"
                "- Follow existing codebase patterns\n"
                "- Import from backend.config for settings\n"
                "- Return complete, production-ready code\n"
            )

            result = await composer.compose_new_strategy(
                db=None,
                user_prompt=prompt,
            )

            if result and result.get("code"):
                return GeneratedCode(
                    code=result["code"],
                    file_path=target_path,
                    strategy_name=result.get("strategy_name", f"gen_{self._generation_count}"),
                    confidence=0.7,
                    explanation=result.get("description", ""),
                )
        except Exception as exc:
            logger.error("[CodeGenerator] Generation failed: {}", exc)

        # Fallback: return a stub
        return GeneratedCode(
            code=self._generate_stub(target_path, description),
            file_path=target_path,
            strategy_name=f"stub_{self._generation_count}",
            confidence=0.3,
            explanation="LLM unavailable, generated stub",
        )

    @staticmethod
    def _generate_stub(target_path: str, description: str) -> str:
        """Generate a minimal stub when LLM is unavailable."""
        module_name = Path(target_path).stem.replace(".py", "")
        return (
            f'"""\n{module_name} — {description}\n"""\n\n'
            f"from __future__ import annotations\n\n"
            f"from loguru import logger\n\n\n"
            f"class {module_name.title().replace('_', '')}:\n"
            f'    """TODO: implement — {description}"""\n\n'
            f"    def __init__(self) -> None:\n"
            f"        logger.info(f\"{module_name} initialized\")\n"
        )


# ---------------------------------------------------------------------------
# ChangeTracker — persists change history
# ---------------------------------------------------------------------------

class ChangeTracker:
    """Persists change history to JSON for audit and rollback."""

    HISTORY_FILE = Path(".sisyphus/agi/change_history.json")

    def __init__(self, history_file: Optional[str] = None) -> None:
        self._file = Path(history_file) if history_file else self.HISTORY_FILE
        self._file.parent.mkdir(parents=True, exist_ok=True)
        self._changes: dict[str, dict[str, Any]] = {}
        self._load()

    def _load(self) -> None:
        if self._file.exists():
            try:
                data = json.loads(self._file.read_text())
                self._changes = data.get("changes", {})
            except (json.JSONDecodeError, KeyError):
                pass

    def _save(self) -> None:
        self._file.write_text(json.dumps(
            {"changes": self._changes}, indent=2, default=str
        ))

    def record(self, change: CodeChange) -> None:
        """Record a change's state."""
        self._changes[change.change_id] = {
            "change_id": change.change_id,
            "change_type": change.change_type.value,
            "title": change.title,
            "description": change.description,
            "files_modified": change.files_modified,
            "diff_summary": change.diff_summary,
            "status": change.status.value,
            "branch_name": change.branch_name,
            "risk_level": change.risk_level,
            "tests_passed": change.validation_results.get("tests_passed", 0),
            "tests_failed": change.validation_results.get("tests_failed", 0),
            "created_at": change.created_at,
            "merged_at": change.merged_at,
        }
        self._save()

    def get_all(self) -> list[dict[str, Any]]:
        return list(self._changes.values())

    def get_recent(self, limit: int = 20) -> list[dict[str, Any]]:
        sorted_changes = sorted(
            self._changes.values(),
            key=lambda c: c.get("created_at", 0),
            reverse=True,
        )
        return sorted_changes[:limit]
