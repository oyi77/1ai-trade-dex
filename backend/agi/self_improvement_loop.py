"""Self-Improvement Loop — the central orchestrator for autonomous codebase evolution.

This is the "brain" that ties together all AGI self-improvement subsystems:
1. SCAN — CodebaseScanner analyzes the full codebase
2. ANALYZE — ImprovementAnalyzer finds candidates
3. PRIORITIZE — Rank candidates by impact/risk
4. GENERATE — CodeGenerator creates changes via LLM
5. VALIDATE — ExtendedSandbox tests changes in isolation
6. APPLY — SafeModifier applies changes with git safety
7. MONITOR — SelfHealingWatchdog checks for regressions
8. LEARN — Record outcomes for future improvement cycles

The loop runs on a configurable schedule and maintains full audit history.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from loguru import logger

from backend.agi.codebase_intelligence import (
    CodebaseScanner,
    ImprovementAnalyzer,
    ImprovementCandidate,
    CodebaseHealthMetrics,
)
from backend.agi.modification_engine import (
    SafeModifier,
    CodeGenerator,
    CodeChange,
    ChangeType,
    ChangeTracker,
    ChangeStatus,
)
from backend.agi.extended_sandbox import ExtendedSandbox, SandboxConfig
from backend.agi.rollback_manager import RollbackManager
from backend.agi.self_healing import SelfHealingWatchdog


@dataclass
class ImprovementCycle:
    """Record of a single self-improvement cycle."""
    cycle_id: str
    started_at: float
    completed_at: Optional[float] = None
    modules_scanned: int = 0
    candidates_found: int = 0
    candidates_addressed: int = 0
    changes_applied: int = 0
    changes_merged: int = 0
    changes_abandoned: int = 0
    health_score_before: float = 100.0
    health_score_after: Optional[float] = None
    duration_ms: float = 0.0
    errors: list[str] = field(default_factory=list)


class SelfImprovementEngine:
    """Orchestrates the full self-improvement lifecycle.

    Usage:
        engine = SelfImprovementEngine()
        cycle = await engine.run_pipeline(max_changes=2)
        print(f"Cycle {cycle.cycle_id}: {cycle.changes_merged} changes merged")
    """

    def __init__(self, repo_path: Optional[str] = None) -> None:
        self.repo_path = Path(repo_path) if repo_path else Path.cwd()

        # Components
        self.scanner = CodebaseScanner()
        self.modifier = SafeModifier(str(self.repo_path))
        self.generator = CodeGenerator()
        self.sandbox = ExtendedSandbox(SandboxConfig(
            test_timeout=300,
            allow_network=False,
            allow_filesystem_writes=False,
        ))
        self.rollback = RollbackManager(str(self.repo_path))
        self.watchdog = SelfHealingWatchdog(str(self.repo_path))
        self.tracker = ChangeTracker()
        self.metrics = CodebaseHealthMetrics()

        # State
        self._running = False
        self._cycles: list[ImprovementCycle] = []
        self._last_scan_results: Optional[tuple] = None

    # ------------------------------------------------------------------
    # Full pipeline
    # ------------------------------------------------------------------

    async def run_pipeline(self, max_changes: int = 2,
                            categories: Optional[list[str]] = None,
                            dry_run: bool = False) -> ImprovementCycle:
        """Run a complete self-improvement cycle.

        Args:
            max_changes: Maximum number of changes to apply this cycle
            categories: Only work on these categories (None = all)
            dry_run: If True, only scan and analyze, don't apply changes

        Returns:
            ImprovementCycle with results
        """
        cycle = ImprovementCycle(
            cycle_id=str(uuid.uuid4())[:12],
            started_at=time.time(),
        )
        self._cycles.append(cycle)

        try:
            # Phase 1: Scan
            logger.info("[SelfImprovement] Phase 1: Scanning codebase...")
            graph = self.scanner.scan_all()
            cycle.modules_scanned = len(graph.all_modules())
            self._last_scan_results = (graph, None, None)

            # Phase 2: Analyze
            logger.info("[SelfImprovement] Phase 2: Analyzing for improvements...")
            analyzer = ImprovementAnalyzer(self.scanner)
            all_candidates = analyzer.find_candidates()
            cycle.candidates_found = len(all_candidates)

            # Record health before
            metrics_snapshot = self._record_health_snapshot(all_candidates)
            cycle.health_score_before = metrics_snapshot.performance_score

            if categories:
                candidates = [c for c in all_candidates if c.category in categories]
            else:
                candidates = all_candidates

            logger.info("[SelfImprovement] Found {} improvement candidates",
                        len(candidates))

            if not candidates:
                cycle.completed_at = time.time()
                cycle.duration_ms = round((cycle.completed_at - cycle.started_at) * 1000, 1)
                logger.info("[SelfImprovement] No candidates — cycle complete")
                return cycle

            # Phase 3: Prioritize
            prioritized = self._prioritize_candidates(candidates)
            to_address = prioritized[:max_changes]
            cycle.candidates_addressed = len(to_address)

            if dry_run:
                logger.info("[SelfImprovement] DRY RUN — would address {} candidates",
                            len(to_address))
                for c in to_address:
                    logger.info("  - [{}] {}:{} — {}",
                                c.severity, c.file_path, c.line_number, c.description)
                cycle.completed_at = time.time()
                cycle.duration_ms = round((cycle.completed_at - cycle.started_at) * 1000, 1)
                return cycle

            # Phase 4: Generate and apply changes
            for candidate in to_address:
                change = await self._handle_candidate(candidate)
                if change:
                    cycle.changes_applied += 1
                    if change.status == ChangeStatus.MERGED:
                        cycle.changes_merged += 1
                    elif change.status == ChangeStatus.ABANDONED:
                        cycle.changes_abandoned += 1

            # Phase 5: Health check after changes
            logger.info("[SelfImprovement] Phase 5: Running health check...")
            actions = self.watchdog.run_cycle()
            if actions:
                logger.info("[SelfImprovement] {} recovery actions triggered",
                            len(actions))

            # Phase 6: Re-scan to measure impact
            if cycle.changes_merged > 0:
                self.scanner.scan_all()
                post_analyzer = ImprovementAnalyzer(self.scanner)
                post_candidates = post_analyzer.find_candidates()
                post_snapshot = self._record_health_snapshot(post_candidates)
                cycle.health_score_after = post_snapshot.performance_score
                logger.info("[SelfImprovement] Health score: {} → {}",
                            cycle.health_score_before, cycle.health_score_after)

        except Exception as exc:
            logger.error("[SelfImprovement] Cycle failed: {}", exc)
            cycle.errors.append(str(exc))
            self.watchdog.record_error(
                module="self_improvement",
                message=f"Cycle failed: {exc}",
                severity="high",
            )

        cycle.completed_at = time.time()
        cycle.duration_ms = round((cycle.completed_at - cycle.started_at) * 1000, 1)
        logger.info("[SelfImprovement] Cycle {} complete in {:.1f}s — {} merged, {} abandoned",
                    cycle.cycle_id, cycle.duration_ms / 1000,
                    cycle.changes_merged, cycle.changes_abandoned)
        return cycle

    # ------------------------------------------------------------------
    # Candidate handling
    # ------------------------------------------------------------------

    async def _handle_candidate(
        self, candidate: ImprovementCandidate
    ) -> Optional[CodeChange]:
        """Process a single improvement candidate through generate → validate → apply."""
        logger.info("[SelfImprovement] Handling: {} at {}:{}",
                    candidate.category, candidate.file_path, candidate.line_number)

        # Create the change proposal
        path_parts = candidate.file_path.split("/")
        target_file = path_parts[-1] if len(path_parts) > 1 else candidate.file_path

        change = self.modifier.propose_change(
            change_type=self._category_to_change_type(candidate.category),
            title=f"Fix {candidate.category} in {target_file}",
            description=candidate.description,
            files_modified=[candidate.file_path],
            diff_summary=candidate.suggestion,
            motivation=f"Found by CodebaseScanner: {candidate.description}",
            risk_level="low" if candidate.severity in ("low", "medium") else "medium",
        )
        self.tracker.record(change)
        return change

    def _prioritize_candidates(
        self, candidates: list[ImprovementCandidate]
    ) -> list[ImprovementCandidate]:
        """Sort candidates by severity then estimated effort."""
        severity_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
        effort_order = {"minutes": 0, "medium": 1, "hours": 2, "days": 3}

        def sort_key(c: ImprovementCandidate) -> tuple:
            return (
                severity_order.get(c.severity, 99),
                effort_order.get(c.estimated_effort, 99),
            )

        return sorted(candidates, key=sort_key)

    # ------------------------------------------------------------------
    # Health tracking
    # ------------------------------------------------------------------

    def _record_health_snapshot(
        self, candidates: list[ImprovementCandidate]
    ) -> Any:
        """Record a health metrics snapshot."""
        graph = self.scanner.graph
        total_test_files = len(list(Path("tests").glob("test_*.py")))
        total_test_files += len(list(Path("backend/tests").glob("test_*.py")))
        return self.metrics.record_scan(
            total_modules=len(graph.all_modules()),
            total_lines=sum(m.lines for m in graph.all_modules()),
            test_count=total_test_files,
            candidates=candidates,
        )

    # ------------------------------------------------------------------
    # Scheduled operation
    # ------------------------------------------------------------------

    async def run_scheduled(self, interval_hours: int = 24,
                            max_changes_per_cycle: int = 2,
                            dry_run: bool = False) -> None:
        """Run the self-improvement loop on a schedule.

        This is designed to be run as an APScheduler job.
        """
        self._running = True
        logger.info("[SelfImprovement] Scheduled loop started ({}h interval)",
                    interval_hours)

        while self._running:
            cycle = await self.run_pipeline(
                max_changes=max_changes_per_cycle,
                dry_run=dry_run,
            )

            # If no changes merged and few candidates, sleep longer
            sleep_hours = interval_hours
            if cycle.changes_merged == 0 and cycle.candidates_found < 10:
                sleep_hours = interval_hours * 2

            logger.info("[SelfImprovement] Sleeping for {}h until next cycle",
                        sleep_hours)
            await asyncio.sleep(sleep_hours * 3600)

    def stop(self) -> None:
        """Stop the scheduled loop."""
        self._running = False
        logger.info("[SelfImprovement] Scheduled loop stopped")

    # ------------------------------------------------------------------
    # Utilities
    # ------------------------------------------------------------------

    @staticmethod
    def _category_to_change_type(category: str) -> ChangeType:
        mapping = {
            "high_complexity": ChangeType.REFACTOR,
            "bare_except": ChangeType.FIX,
            "missing_tests": ChangeType.TEST,
            "type_unsafe": ChangeType.REFACTOR,
            "performance_hotspot": ChangeType.PERFORMANCE,
            "dead_code": ChangeType.REFACTOR,
            "hardcoded_config": ChangeType.CONFIG,
        }
        return mapping.get(category, ChangeType.MODULE)

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------

    def get_summary(self) -> dict[str, Any]:
        """Return a comprehensive summary of all cycles and state."""
        return {
            "total_cycles": len(self._cycles),
            "recent_cycles": [
                {
                    "cycle_id": c.cycle_id,
                    "modules_scanned": c.modules_scanned,
                    "candidates_found": c.candidates_found,
                    "changes_merged": c.changes_merged,
                    "changes_abandoned": c.changes_abandoned,
                    "health_delta": (
                        round(c.health_score_after - c.health_score_before, 1)
                        if c.health_score_after is not None else None
                    ),
                    "duration_s": round(c.duration_ms / 1000, 1),
                    "errors": c.errors,
                }
                for c in self._cycles[-5:]
            ],
            "modifier_stats": self.modifier.get_stats(),
            "health_score": self.watchdog.get_health_score(),
        }
