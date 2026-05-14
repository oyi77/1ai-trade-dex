"""Codebase Intelligence — deep understanding of the PolyEdge codebase.

Provides module discovery, dependency graph construction, improvement
candidate identification via static analysis, and health metrics tracking.

This is the perceptual layer of the self-improvement AGI system.
"""

from __future__ import annotations

import ast
import json
import os
import time
from collections import defaultdict
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from loguru import logger


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class ModuleInfo:
    """Information about a single Python module in the codebase."""
    path: str                    # Relative path (e.g. backend/core/risk_manager.py)
    package: str                 # Python dotted name (e.g. backend.core.risk_manager)
    lines: int                   # Total lines of code
    imports: list[str] = field(default_factory=list)       # Modules this file imports
    imported_by: list[str] = field(default_factory=list)   # Modules that import this
    exports: list[str] = field(default_factory=list)       # Defined classes/functions
    has_tests: bool = False
    ast_node: Optional[ast.AST] = None  # Cached AST for re-analysis


@dataclass
class ImprovementCandidate:
    """An identified opportunity for codebase improvement."""
    category: str        # e.g. "high_complexity", "bare_except", "missing_tests"
    file_path: str
    line_number: int
    severity: str        # "critical", "high", "medium", "low"
    description: str
    suggestion: str
    estimated_effort: str = "medium"  # "minutes", "hours", "days"


@dataclass
class CodebaseSnapshot:
    """A point-in-time snapshot of codebase health metrics."""
    timestamp: float
    total_modules: int
    total_lines: int
    test_count: int
    total_candidates: int
    critical_candidates: int
    high_candidates: int
    medium_candidates: int
    low_candidates: int
    performance_score: float  # 0-100, higher is better


# ---------------------------------------------------------------------------
# ModuleGraph — dependency analysis
# ---------------------------------------------------------------------------

class ModuleGraph:
    """Directed graph of module dependencies.

    Edge A → B means "module A imports module B".
    """

    def __init__(self) -> None:
        self._modules: dict[str, ModuleInfo] = {}

    def add_module(self, path: str, package: str, imports: list[str],
                   exports: list[str], lines: int, ast_node: Any = None) -> ModuleInfo:
        info = ModuleInfo(
            path=path,
            package=package,
            lines=lines,
            imports=imports,
            exports=exports,
            ast_node=ast_node,
        )
        self._modules[package] = info
        return info

    def get(self, package: str) -> Optional[ModuleInfo]:
        return self._modules.get(package)

    def all_modules(self) -> list[ModuleInfo]:
        return list(self._modules.values())

    def dependents_of(self, package: str) -> list[str]:
        """Modules that DIRECTLY import *package*."""
        return [p for p, info in self._modules.items() if package in info.imports]

    def dependencies_of(self, package: str) -> list[str]:
        """Modules that *package* DIRECTLY imports."""
        info = self._modules.get(package)
        return info.imports if info else []

    def leaf_modules(self) -> list[ModuleInfo]:
        """Modules with ZERO in-project dependents — safest to modify."""
        return [info for info in self._modules.values()
                if not self.dependents_of(info.package)]

    def core_modules(self) -> list[ModuleInfo]:
        """Modules with the MOST in-project dependents — highest risk."""
        scored = [(len(self.dependents_of(info.package)), info)
                  for info in self._modules.values()]
        scored.sort(reverse=True)
        return [info for _, info in scored[:10]]

    def find_dead_code(self) -> list[ModuleInfo]:
        """Modules that no other project module imports."""
        project_packages = set(self._modules.keys())
        return [
            info for info in self._modules.values()
            if info.package in project_packages
            and not any(
                info.package in self._modules[p].imports
                for p in project_packages if p != info.package
            )
        ]

    def render(self) -> str:
        """ASCII summary of the dependency graph."""
        lines = [f"ModuleGraph: {len(self._modules)} modules"]
        for info in sorted(self._modules.values(), key=lambda m: m.package):
            deps = self.dependents_of(info.package)
            dep_count = len(deps)
            lines.append(
                f"  {info.package} ({info.lines} lines, "
                f"{len(info.imports)} imports, {dep_count} dependents)"
            )
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# CodebaseScanner — walks files, builds graph
# ---------------------------------------------------------------------------

class CodebaseScanner:
    """Walks the backend/ tree, parses every .py file, builds ModuleGraph."""

    BASE_DIR = Path("backend")

    def __init__(self) -> None:
        self.graph = ModuleGraph()
        self._scan_time: float = 0.0

    def scan_all(self) -> ModuleGraph:
        """Full scan of the entire backend/ codebase."""
        start = time.time()
        self.graph = ModuleGraph()

        # Phase 1: collect all Python files
        py_files: list[Path] = []
        for root, dirs, files in os.walk(str(self.BASE_DIR)):
            # Skip common non-source directories
            dirs[:] = [d for d in dirs if not d.startswith(("__pycache__", ".", "venv",
                                                              "node_modules", "alembic"))]
            for f in files:
                if f.endswith(".py"):
                    py_files.append(Path(root) / f)

        # Phase 2: parse each file
        imports_map: dict[str, list[str]] = {}
        for fpath in py_files:
            pkg = self._path_to_package(fpath)
            try:
                source = fpath.read_text(encoding="utf-8", errors="replace")
                tree = ast.parse(source)
                imports = self._extract_imports(tree)
                exports = self._extract_exports(tree)
                lines = len(source.splitlines())
                self.graph.add_module(
                    path=str(fpath),
                    package=pkg,
                    imports=imports,
                    exports=exports,
                    lines=lines,
                    ast_node=tree,
                )
                imports_map[pkg] = imports
            except SyntaxError:
                logger.warning("[CodebaseScanner] Syntax error in {}", pkg)
            except Exception as exc:
                logger.debug("[CodebaseScanner] Skipping {}: {}", pkg, exc)

        # Phase 3: resolve inter-project imports (populate imported_by)
        project_packages = set(self.graph._modules.keys())
        for pkg, info in self.graph._modules.items():
            # Filter imports to only project-internal ones
            internal_imports = [i for i in info.imports if i in project_packages]
            info.imports = internal_imports
            for dep in internal_imports:
                dep_info = self.graph._modules.get(dep)
                if dep_info and pkg not in dep_info.imported_by:
                    dep_info.imported_by.append(pkg)

        # Phase 4: mark which modules have tests
        for info in self.graph._modules.values():
            test_path = self._find_test_for(info.package)
            info.has_tests = test_path is not None

        self._scan_time = time.time() - start
        logger.info("[CodebaseScanner] Scanned {} modules in {:.1f}s",
                    len(self.graph._modules), self._scan_time)
        return self.graph

    @staticmethod
    def _path_to_package(fpath: Path) -> str:
        """Convert backend/core/foo.py → backend.core.foo"""
        relative = fpath.relative_to(CodebaseScanner.BASE_DIR.parent
                                     if fpath.parts[0] == "backend"
                                     else CodebaseScanner.BASE_DIR)
        parts = list(relative.parts)
        if parts[-1] == "__init__.py":
            parts.pop()
        else:
            parts[-1] = parts[-1].replace(".py", "")
        return ".".join(parts)

    @staticmethod
    def _extract_imports(tree: ast.AST) -> list[str]:
        """Extract all project-module imports from an AST."""
        imports: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    name = alias.name.split(".")[0]
                    if name.startswith("backend"):
                        imports.append(alias.name)
            elif isinstance(node, ast.ImportFrom) and node.module:
                if node.module.startswith("backend"):
                    imports.append(node.module)
        return list(set(imports))

    @staticmethod
    def _extract_exports(tree: ast.AST) -> list[str]:
        """Extract top-level class and function names from an AST."""
        exports: list[str] = []
        for node in ast.iter_child_nodes(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                exports.append(node.name)
        return exports

    @staticmethod
    def _find_test_for(package: str) -> Optional[str]:
        """Check if a test file exists for the given package."""
        # Converts backend.core.foo -> tests/test_foo.py or backend/tests/test_foo.py
        parts = package.split(".")
        if len(parts) >= 2:
            module_name = parts[-1]
            # Check root tests/
            root_test = Path(f"tests/test_{module_name}.py")
            if root_test.exists():
                return str(root_test)
            # Check backend/tests/
            backend_test = Path(f"backend/tests/test_{module_name}.py")
            if backend_test.exists():
                return str(backend_test)
            # Check sub-packages
            sub_test = Path(f"backend/tests/test_{'_'.join(parts[1:])}.py")
            if sub_test.exists():
                return str(sub_test)
        return None


# ---------------------------------------------------------------------------
# ImprovementAnalyzer — identifies improvement candidates
# ---------------------------------------------------------------------------

class ImprovementAnalyzer:
    """Static analysis to find codebase improvement opportunities."""

    HIGH_COMPLEXITY_THRESHOLD = 50    # lines
    MAX_BRANCHES = 5

    def __init__(self, scanner: CodebaseScanner) -> None:
        self.scanner = scanner
        self.graph = scanner.graph

    def find_candidates(self) -> list[ImprovementCandidate]:
        """Run ALL detectors and return combined results."""
        candidates: list[ImprovementCandidate] = []
        candidates.extend(self._detect_high_complexity())
        candidates.extend(self._detect_bare_except())
        candidates.extend(self._detect_missing_tests())
        candidates.extend(self._detect_type_unsafe())
        candidates.extend(self._detect_performance_hotspots())
        candidates.extend(self._detect_dead_code())
        candidates.extend(self._detect_hardcoded_config())
        return candidates

    # ------------------------------------------------------------------
    # Detector: HIGH_COMPLEXITY — functions over 50 lines or 5+ branches
    # ------------------------------------------------------------------

    def _detect_high_complexity(self) -> list[ImprovementCandidate]:
        candidates: list[ImprovementCandidate] = []
        for info in self.graph.all_modules():
            if not info.ast_node:
                continue
            for node in ast.walk(info.ast_node):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    end = node.end_lineno or 0
                    start = node.lineno
                    length = end - start
                    branches = sum(1 for _ in ast.walk(node)
                                   if isinstance(_, (ast.If, ast.For, ast.While,
                                                     ast.Try, ast.ExceptHandler)))
                    if length > self.HIGH_COMPLEXITY_THRESHOLD or branches > self.MAX_BRANCHES:
                        severity = "high" if length > 100 else "medium"
                        candidates.append(ImprovementCandidate(
                            category="high_complexity",
                            file_path=info.path,
                            line_number=start,
                            severity=severity,
                            description=f"{node.name}: {length} lines, {branches} branches",
                            suggestion="Refactor into smaller functions or use strategy pattern",
                            estimated_effort="hours" if length > 100 else "medium",
                        ))
        return candidates

    # ------------------------------------------------------------------
    # Detector: BARE_EXCEPT — except: pass or bare except without logging
    # ------------------------------------------------------------------

    def _detect_bare_except(self) -> list[ImprovementCandidate]:
        candidates: list[ImprovementCandidate] = []
        for info in self.graph.all_modules():
            if not info.ast_node:
                continue
            for node in ast.walk(info.ast_node):
                if isinstance(node, ast.ExceptHandler):
                    if node.type is None:
                        candidates.append(ImprovementCandidate(
                            category="bare_except",
                            file_path=info.path,
                            line_number=node.lineno,
                            severity="high",
                            description="Bare except: handler catches ALL exceptions",
                            suggestion="Add explicit exception type or use logger.exception()",
                            estimated_effort="minutes",
                        ))
                    # Check if body is just "pass" or empty
                    if (node.type is not None
                            and len(node.body) == 1
                            and isinstance(node.body[0], ast.Pass)):
                        candidates.append(ImprovementCandidate(
                            category="bare_except",
                            file_path=info.path,
                            line_number=node.lineno,
                            severity="medium",
                            description="Empty except handler — error silently swallowed",
                            suggestion="Log the exception with logger.exception()",
                            estimated_effort="minutes",
                        ))
        return candidates

    # ------------------------------------------------------------------
    # Detector: MISSING_TESTS — modules without test coverage
    # ------------------------------------------------------------------

    def _detect_missing_tests(self) -> list[ImprovementCandidate]:
        candidates: list[ImprovementCandidate] = []
        for info in self.graph.all_modules():
            # Skip __init__.py, abstract base classes, models
            if info.package.endswith("__init__"):
                continue
            if "abc" in info.exports or "ABC" in info.exports:
                continue
            if "Base" in info.exports or "Abstract" in " ".join(info.exports):
                continue
            if not info.has_tests and info.lines > 50:
                candidates.append(ImprovementCandidate(
                    category="missing_tests",
                    file_path=info.path,
                    line_number=1,
                    severity="medium",
                    description=f"No test file found for {info.package} ({info.lines} lines)",
                    suggestion=f"Create tests/test_{info.path.split('/')[-1]} with pytest",
                    estimated_effort="hours",
                ))
        return candidates

    # ------------------------------------------------------------------
    # Detector: TYPE_UNSAFE — functions without type annotations
    # ------------------------------------------------------------------

    def _detect_type_unsafe(self) -> list[ImprovementCandidate]:
        candidates: list[ImprovementCandidate] = []
        for info in self.graph.all_modules():
            if not info.ast_node:
                continue
            for node in ast.walk(info.ast_node):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    # Check if any argument lacks annotation
                    args = node.args
                    untyped = []
                    for arg in args.args + args.kwonlyargs + ([args.vararg] if args.vararg else []):
                        if arg.arg != "self" and arg.arg != "cls" and arg.annotation is None:
                            untyped.append(arg.arg)
                    if untyped and node.lineno:
                        candidates.append(ImprovementCandidate(
                            category="type_unsafe",
                            file_path=info.path,
                            line_number=node.lineno,
                            severity="low",
                            description=f"{node.name}: untyped params: {', '.join(untyped[:5])}",
                            suggestion="Add type annotations to function signature",
                            estimated_effort="minutes",
                        ))
        return candidates

    # ------------------------------------------------------------------
    # Detector: PERFORMANCE_HOTSPOT — sync I/O inside async functions
    # ------------------------------------------------------------------

    def _detect_performance_hotspots(self) -> list[ImprovementCandidate]:
        """Detect blocking calls (time.sleep, requests.get, etc.) inside async functions."""
        BLOCKING_CALLS = {"time.sleep", "requests.get", "requests.post",
                          "subprocess.run", "subprocess.call",
                          "open(", ".read()", ".write()", "json.load(open"}
        candidates: list[ImprovementCandidate] = []
        for info in self.graph.all_modules():
            if not info.ast_node:
                continue
            for node in ast.walk(info.ast_node):
                if isinstance(node, ast.AsyncFunctionDef):
                    for child in ast.walk(node):
                        if isinstance(child, ast.Call):
                            call_str = ""
                            if isinstance(child.func, ast.Attribute):
                                call_str = f"{ast.unparse(child.func)}"
                            elif isinstance(child.func, ast.Name):
                                call_str = child.func.id
                            for blocking in BLOCKING_CALLS:
                                if blocking in call_str:
                                    candidates.append(ImprovementCandidate(
                                        category="performance_hotspot",
                                        file_path=info.path,
                                        line_number=child.lineno,
                                        severity="high",
                                        description=f"Blocking call '{call_str}' inside async {node.name}",
                                        suggestion=f"Use async equivalent of {blocking} or wrap in asyncio.to_thread()",
                                        estimated_effort="minutes",
                                    ))
        return candidates

    # ------------------------------------------------------------------
    # Detector: DEAD_CODE — modules nobody imports
    # ------------------------------------------------------------------

    def _detect_dead_code(self) -> list[ImprovementCandidate]:
        candidates: list[ImprovementCandidate] = []
        dead = self.graph.find_dead_code()
        for info in dead:
            # Skip __init__.py and __main__.py
            if info.package.endswith(("__init__", "__main__")):
                continue
            candidates.append(ImprovementCandidate(
                category="dead_code",
                file_path=info.path,
                line_number=1,
                severity="low",
                description=f"Module {info.package} has no in-project consumers",
                suggestion="Consider removing or consolidating; or add exports if it's a public API",
                estimated_effort="medium",
            ))
        return candidates

    # ------------------------------------------------------------------
    # Detector: HARDCODED_CONFIG — magic numbers/strings in core logic
    # ------------------------------------------------------------------

    def _detect_hardcoded_config(self) -> list[ImprovementCandidate]:
        """Detect magic numbers and strings that should be config settings."""
        candidates: list[ImprovementCandidate] = []
        for info in self.graph.all_modules():
            if not info.ast_node or "test_" in info.path:
                continue
            for node in ast.walk(info.ast_node):
                # Look for numeric literals in range that are likely tunable constants
                if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
                    if 5 <= node.value <= 3600 and not self._is_in_test_or_config(info.path):
                        # Only flag if used in a comparison or assignment
                        parent = getattr(node, 'parent', None)
                        if parent and isinstance(parent, (ast.Compare, ast.Assign)):
                            candidates.append(ImprovementCandidate(
                                category="hardcoded_config",
                                file_path=info.path,
                                line_number=node.lineno,
                                severity="low",
                                description=f"Magic number {node.value} should be configurable",
                                suggestion="Extract to settings or strategy params",
                                estimated_effort="minutes",
                            ))
        return candidates

    @staticmethod
    def _is_in_test_or_config(path: str) -> bool:
        return "test_" in path or "config.py" in path or "settings" in path


# ---------------------------------------------------------------------------
# CodebaseHealthMetrics — tracks quality over time
# ---------------------------------------------------------------------------

class CodebaseHealthMetrics:
    """Tracks codebase health metrics over time for trend detection."""

    METRICS_FILE = Path(".sisyphus/agi/codebase_metrics.json")

    def __init__(self, metrics_file: Optional[str] = None) -> None:
        self._file = Path(metrics_file) if metrics_file else self.METRICS_FILE
        self._file.parent.mkdir(parents=True, exist_ok=True)
        self._history: list[CodebaseSnapshot] = []
        self._load()

    def _load(self) -> None:
        if self._file.exists():
            try:
                data = json.loads(self._file.read_text())
                self._history = [CodebaseSnapshot(**s) for s in data]
            except (json.JSONDecodeError, KeyError, TypeError) as exc:
                logger.warning("[CodebaseHealthMetrics] Failed to load metrics: {}", exc)

    def _save(self) -> None:
        self._file.write_text(json.dumps(
            [asdict(s) for s in self._history], indent=2, default=str
        ))

    def record_scan(self, total_modules: int, total_lines: int, test_count: int,
                    candidates: list[ImprovementCandidate]) -> CodebaseSnapshot:
        """Record a new scan snapshot."""
        critical = sum(1 for c in candidates if c.severity == "critical")
        high = sum(1 for c in candidates if c.severity == "high")
        medium = sum(1 for c in candidates if c.severity == "medium")
        low = sum(1 for c in candidates if c.severity == "low")

        # Performance score: 100 - weighted issues per module
        total_issues = len(candidates)
        weighted = critical * 10 + high * 5 + medium * 2 + low
        perf_score = max(0.0, 100.0 - (weighted / max(total_modules, 1)) * 20)

        snapshot = CodebaseSnapshot(
            timestamp=time.time(),
            total_modules=total_modules,
            total_lines=total_lines,
            test_count=test_count,
            total_candidates=total_issues,
            critical_candidates=critical,
            high_candidates=high,
            medium_candidates=medium,
            low_candidates=low,
            performance_score=round(perf_score, 1),
        )
        self._history.append(snapshot)
        # Keep last 100 snapshots
        if len(self._history) > 100:
            self._history = self._history[-100:]
        self._save()
        return snapshot

    def get_trend(self) -> str:
        """Return 'improving', 'declining', or 'stable' based on last 3 scans."""
        if len(self._history) < 3:
            return "stable"
        recent = self._history[-3:]
        scores = [s.performance_score for s in recent]
        if scores[-1] > scores[0] + 2:
            return "improving"
        elif scores[-1] < scores[0] - 2:
            return "declining"
        return "stable"

    def get_regression(self) -> list[str]:
        """Detect new high-severity issues since last scan."""
        if len(self._history) < 2:
            return []
        prev, curr = self._history[-2], self._history[-1]
        regressions: list[str] = []
        if curr.high_candidates > prev.high_candidates:
            regressions.append(
                f"High-severity candidates increased: {prev.high_candidates} → {curr.high_candidates}"
            )
        if curr.critical_candidates > prev.critical_candidates:
            regressions.append(
                f"Critical candidates increased: {prev.critical_candidates} → {curr.critical_candidates}"
            )
        if curr.performance_score < prev.performance_score - 5:
            regressions.append(
                f"Performance score dropped: {prev.performance_score} → {curr.performance_score}"
            )
        return regressions

    def latest(self) -> Optional[CodebaseSnapshot]:
        """Get the most recent snapshot."""
        return self._history[-1] if self._history else None


# ---------------------------------------------------------------------------
# Convenience: full scan
# ---------------------------------------------------------------------------

def run_full_codebase_scan() -> tuple[ModuleGraph, list[ImprovementCandidate], CodebaseSnapshot]:
    """Convenience: run scanner + analyzer + metrics in one call."""
    scanner = CodebaseScanner()
    graph = scanner.scan_all()
    analyzer = ImprovementAnalyzer(scanner)
    candidates = analyzer.find_candidates()
    metrics = CodebaseHealthMetrics()
    total_test_files = len(list(Path("tests").glob("test_*.py")))
    total_test_files += len(list(Path("backend/tests").glob("test_*.py")))
    snapshot = metrics.record_scan(
        total_modules=len(graph.all_modules()),
        total_lines=sum(m.lines for m in graph.all_modules()),
        test_count=total_test_files,
        candidates=candidates,
    )
    return graph, candidates, snapshot
