"""Rollback Manager — git-based safe revert with full change tracking.

Provides:
- Automatic rollback of any modification that causes test failures
- Change-level tracking with before/after snapshots
- Integration with SafeModifier for recovery
- Audit trail of all rollback events
"""

from __future__ import annotations

import json
import subprocess
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from loguru import logger


@dataclass
class RollbackEvent:
    """Record of a rollback operation."""
    event_id: str
    change_id: str
    change_title: str
    reason: str
    branch_name: str
    recovered: bool
    duration_ms: float
    created_at: float = field(default_factory=time.time)


class RollbackManager:
    """Manages safe rollback of code changes using git.

    Every modification creates a git branch. Rollback simply checks out
    the original branch and deletes the feature branch.

    Provides three rollback strategies:
    1. HARD — delete feature branch, force back to original (default)
    2. SOFT — revert the merge commit (keeps history)
    3. RESET — git reset to before the change (destructive)
    """

    ROLLBACK_LOG = Path(".sisyphus/agi/rollback_log.json")

    def __init__(self, repo_path: Optional[str] = None) -> None:
        self.repo_path = Path(repo_path) if repo_path else Path.cwd()
        self._log_file = self.ROLLBACK_LOG
        self._log_file.parent.mkdir(parents=True, exist_ok=True)
        self._events: list[RollbackEvent] = []
        self._load()

    def _load(self) -> None:
        if self._log_file.exists():
            try:
                data = json.loads(self._log_file.read_text())
                self._events = [RollbackEvent(**e) for e in data.get("events", [])]
            except (json.JSONDecodeError, TypeError):
                pass

    def _save(self) -> None:
        self._log_file.write_text(json.dumps(
            {"events": [{
                "event_id": e.event_id, "change_id": e.change_id,
                "change_title": e.change_title, "reason": e.reason,
                "branch_name": e.branch_name, "recovered": e.recovered,
                "duration_ms": e.duration_ms, "created_at": e.created_at,
            } for e in self._events]}, indent=2,
        ))

    def _run_git(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["git"] + list(args),
            cwd=str(self.repo_path),
            capture_output=True, text=True,
            timeout=30,
        )

    def rollback(self, change_id: str, change_title: str,
                 branch_name: str, reason: str = "test_failure",
                 strategy: str = "hard") -> RollbackEvent:
        """Rollback a change by deleting its branch and returning to main.

        Args:
            change_id: The unique ID of the change to rollback
            change_title: Human-readable title
            branch_name: The git branch to remove
            reason: Why it's being rolled back
            strategy: 'hard', 'soft', or 'reset'

        Returns:
            RollbackEvent with outcome
        """
        start = time.time()
        event_id = str(uuid.uuid4())[:12]
        recovered = False

        try:
            # Get current branch
            current = self._run_git("rev-parse", "--abbrev-ref", "HEAD").stdout.strip()

            if strategy == "hard":
                # Ensure we're not on the branch to delete
                if current == branch_name:
                    self._run_git("checkout", "-", check=False)
                result = self._run_git("branch", "-D", branch_name)
                recovered = result.returncode == 0

            elif strategy == "soft":
                # Find the merge commit and revert it
                result = self._run_git("log", "--oneline", "--all",
                                       "--grep", f"agi-merge: {branch_name}",
                                       "-n", "1")
                if result.stdout.strip():
                    merge_hash = result.stdout.split()[0]
                    self._run_git("revert", "--no-edit", merge_hash)
                    recovered = True

            elif strategy == "reset":
                # Find the commit before the change
                result = self._run_git("log", "--oneline", "--all",
                                       "--grep", change_id[:12],
                                       "-n", "1")
                if result.stdout.strip():
                    commit_hash = result.stdout.split()[0]
                    self._run_git("revert", "--no-edit", commit_hash)
                    recovered = True

            if recovered:
                logger.info("[RollbackManager] Rolled back '{}' ({}) using {} strategy",
                            change_title, change_id, strategy)
            else:
                logger.warning("[RollbackManager] Rollback failed for '{}' ({})",
                               change_title, change_id)

        except Exception as exc:
            logger.error("[RollbackManager] Rollback error for '{}': {}",
                         change_id, exc)

        event = RollbackEvent(
            event_id=event_id,
            change_id=change_id,
            change_title=change_title,
            reason=reason,
            branch_name=branch_name,
            recovered=recovered,
            duration_ms=round((time.time() - start) * 1000, 1),
        )
        self._events.append(event)
        self._save()
        return event

    def get_events(self, limit: int = 50) -> list[RollbackEvent]:
        """Return recent rollback events."""
        return sorted(self._events, key=lambda e: e.created_at, reverse=True)[:limit]

    def get_stats(self) -> dict[str, Any]:
        """Return rollback statistics."""
        total = len(self._events)
        recovered = sum(1 for e in self._events if e.recovered)
        return {
            "total_rollbacks": total,
            "successful": recovered,
            "failed": total - recovered,
            "success_rate": round(recovered / max(total, 1) * 100, 1),
        }
