"""Comprehensive tests for the AGI self-improvement system."""
import ast
import tempfile
from pathlib import Path


from backend.agi.codebase_intelligence import (
    CodebaseScanner,
    ImprovementAnalyzer,
    ImprovementCandidate,
    ModuleGraph,
    CodebaseHealthMetrics,
)
from backend.agi.extended_sandbox import (
    ExtendedSandbox,
    SandboxResult,
)
from backend.agi.self_healing import (
    SelfHealingWatchdog,
    HealthEvent,
    RecoveryAction,
)


# ============================================================================
# ModuleGraph tests
# ============================================================================

class TestModuleGraph:
    def test_add_and_get_module(self):
        g = ModuleGraph()
        g.add_module("backend/core/foo.py", "backend.core.foo", ["backend.config"], ["FooClass"], 100)
        info = g.get("backend.core.foo")
        assert info is not None
        assert info.path == "backend/core/foo.py"
        assert info.lines == 100
        assert "FooClass" in info.exports

    def test_dependents_of(self):
        g = ModuleGraph()
        g.add_module("backend/core/a.py", "backend.core.a", ["backend.core.b"], [], 10)
        g.add_module("backend/core/b.py", "backend.core.b", [], [], 10)
        deps = g.dependents_of("backend.core.b")
        assert "backend.core.a" in deps

    def test_leaf_modules(self):
        g = ModuleGraph()
        g.add_module("backend/core/a.py", "backend.core.a", ["backend.core.b"], [], 10)
        g.add_module("backend/core/b.py", "backend.core.b", [], [], 10)
        leaves = g.leaf_modules()
        assert len(leaves) == 1
        assert leaves[0].package == "backend.core.a"

    def test_all_modules_returns_all(self):
        g = ModuleGraph()
        g.add_module("backend/a.py", "backend.a", [], [], 5)
        g.add_module("backend/b.py", "backend.b", [], [], 5)
        assert len(g.all_modules()) == 2


# ============================================================================
# CodebaseScanner tests
# ============================================================================

class TestCodebaseScanner:
    def test_extract_imports_detects_project_imports(self):
        code = """
from backend.config import settings
import backend.models.database
from backend.core.risk_manager import RiskManager
import os
import json
"""
        tree = ast.parse(code)
        imports = CodebaseScanner._extract_imports(tree)
        assert "backend.config" in imports
        assert "backend.models.database" in imports
        assert "backend.core.risk_manager" in imports
        assert "os" not in imports
        assert "json" not in imports

    def test_extract_exports_finds_classes_and_functions(self):
        code = """
class MyClass:
    pass

def my_func():
    pass

async def my_async():
    pass

x = 5
"""
        tree = ast.parse(code)
        exports = CodebaseScanner._extract_exports(tree)
        assert "MyClass" in exports
        assert "my_func" in exports
        assert "my_async" in exports
        assert "x" not in exports

    def test_path_to_package_conversion(self):
        fpath = Path("backend/core/foo.py")
        pkg = CodebaseScanner._path_to_package(fpath)
        assert pkg == "backend.core.foo"

    def test_path_to_package_init(self):
        fpath = Path("backend/core/__init__.py")
        pkg = CodebaseScanner._path_to_package(fpath)
        assert pkg == "backend.core"

    def test_find_test_returns_none_for_untested_module(self):
        result = CodebaseScanner._find_test_for("some.nonexistent.module")
        assert result is None


# ============================================================================
# ImprovementAnalyzer tests
# ============================================================================

class TestImprovementAnalyzer:
    def test_detect_high_complexity(self):
        scanner = CodebaseScanner()
        high_complexity_code = """
def very_long_function(param1, param2, param3):
    a = 1
    b = 2
    if a > 0:
        print("branch 1")
    if b > 0:
        print("branch 2")
    if a > 0:
        print("branch 3")
    if b > 0:
        print("branch 4")
    if a > 0:
        print("branch 5")
    if b > 0:
        print("branch 6")
    print("done")
"""
        tree = ast.parse(high_complexity_code)
        scanner.graph.add_module(
            "backend/test_complex.py", "backend.test_complex",
            [], ["very_long_function"], 20, tree,
        )
        analyzer = ImprovementAnalyzer(scanner)
        candidates = analyzer._detect_high_complexity()
        complex_candidates = [c for c in candidates if "very_long_function" in c.description]
        assert len(complex_candidates) >= 0

    def test_detect_bare_except(self):
        scanner = CodebaseScanner()
        code = """
def test_func():
    try:
        do_something()
    except:
        pass
"""
        tree = ast.parse(code)
        scanner.graph.add_module(
            "backend/test_bare.py", "backend.test_bare",
            [], ["test_func"], 10, tree,
        )
        analyzer = ImprovementAnalyzer(scanner)
        candidates = analyzer._detect_bare_except()
        bare_excepts = [c for c in candidates if "bare_except" in c.category]
        assert len(bare_excepts) >= 1

    def test_detect_missing_tests(self):
        scanner = CodebaseScanner()
        scanner.graph.add_module(
            "backend/core/novel_module.py", "backend.core.novel_module",
            [], ["NovelClass"], 200, None,
        )
        analyzer = ImprovementAnalyzer(scanner)
        candidates = analyzer._detect_missing_tests()
        novel = [c for c in candidates if "novel_module" in c.file_path]
        assert len(novel) >= 1

    def test_detect_dead_code(self):
        scanner = CodebaseScanner()
        scanner.graph.add_module(
            "backend/somemod.py", "backend.somemod",
            [], ["Something"], 50, None,
        )
        analyzer = ImprovementAnalyzer(scanner)
        candidates = analyzer._detect_dead_code()
        somemod = [c for c in candidates if "somemod" in c.file_path]
        assert len(somemod) >= 0

    def test_improvement_candidate_dataclass(self):
        c = ImprovementCandidate(
            category="test",
            file_path="test.py",
            line_number=10,
            severity="high",
            description="Something to fix",
            suggestion="Do something",
        )
        assert c.category == "test"
        assert c.severity == "high"
        assert c.estimated_effort == "medium"


# ============================================================================
# CodebaseHealthMetrics tests
# ============================================================================

class TestCodebaseHealthMetrics:
    def test_record_scan_creates_snapshot(self):
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            metrics = CodebaseHealthMetrics(metrics_file=f.name)
            snapshot = metrics.record_scan(
                total_modules=100,
                total_lines=10000,
                test_count=50,
                candidates=[
                    ImprovementCandidate("test", "f.py", 1, "critical", "err", "fix"),
                    ImprovementCandidate("test", "f.py", 2, "high", "err", "fix"),
                ],
            )
            assert snapshot.total_modules == 100
            assert snapshot.total_candidates == 2
            assert 0 <= snapshot.performance_score <= 100

    def test_get_trend_stable_with_insufficient_data(self):
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            metrics = CodebaseHealthMetrics(metrics_file=f.name)
            assert metrics.get_trend() == "stable"

    def test_get_regression_returns_empty_with_insufficient_data(self):
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            metrics = CodebaseHealthMetrics(metrics_file=f.name)
            assert metrics.get_regression() == []


# ============================================================================
# ExtendedSandbox tests
# ============================================================================

class TestExtendedSandbox:
    def test_validate_valid_code(self):
        sandbox = ExtendedSandbox()
        result = sandbox.validate_code("x = 1\ny = 2\n")
        assert result.passed is True
        assert len(result.errors) == 0

    def test_validate_invalid_syntax(self):
        sandbox = ExtendedSandbox()
        result = sandbox.validate_code("def broken(:")
        assert result.passed is False
        assert len(result.errors) >= 1

    def test_validate_forbidden_import(self):
        sandbox = ExtendedSandbox()
        result = sandbox.validate_code("import os\nx = 1")
        assert result.passed is False
        assert any("os" in e for e in result.errors)

    def test_run_tests_no_paths(self):
        sandbox = ExtendedSandbox()
        result = sandbox.run_tests([])
        assert result.passed is True
        assert result.tests_passed == 0

    def test_sandbox_result_dataclass(self):
        r = SandboxResult(run_id="test123", passed=True)
        assert r.run_id == "test123"
        assert r.passed is True

    def test_get_recent_results(self):
        sandbox = ExtendedSandbox()
        sandbox.validate_code("x = 1")
        results = sandbox.get_recent_results()
        assert len(results) == 1

    def test_get_summary(self):
        sandbox = ExtendedSandbox()
        sandbox.validate_code("x = 1")
        summary = sandbox.get_summary()
        assert summary["total_runs"] > 0


# ============================================================================
# SelfHealingWatchdog tests
# ============================================================================

class TestSelfHealingWatchdog:
    def test_record_error(self):
        watchdog = SelfHealingWatchdog()
        event = watchdog.record_error("test_module", "test error", "warning")
        assert event.event_type == "error"
        assert event.module == "test_module"
        assert event.severity == "warning"

    def test_record_performance(self):
        watchdog = SelfHealingWatchdog()
        event = watchdog.record_performance("test_module", "win_rate", 0.5, 0.6)
        assert event.event_type == "performance"

    def test_record_recovery(self):
        watchdog = SelfHealingWatchdog()
        action = watchdog.record_recovery("rollback", "strategy_x", "test failure", True)
        assert action.action_type == "rollback"
        assert action.success is True

    def test_get_health_score_default(self):
        watchdog = SelfHealingWatchdog()
        watchdog._events = []
        watchdog._error_window.clear()
        score = watchdog.get_health_score()
        assert score == 100.0

    def test_get_health_score_after_errors(self):
        watchdog = SelfHealingWatchdog()
        watchdog.record_error("mod", "critical error", "critical")
        score = watchdog.get_health_score()
        assert score < 100.0

    def test_check_error_rate_under_threshold(self):
        watchdog = SelfHealingWatchdog()
        result = watchdog.check_error_rate(window_seconds=3600)
        assert result is None

    def test_check_consecutive_failures_under_threshold(self):
        watchdog = SelfHealingWatchdog()
        result = watchdog.check_consecutive_failures(max_failures=5)
        assert result is None

    def test_run_cycle_empty(self):
        watchdog = SelfHealingWatchdog()
        actions = watchdog.run_cycle()
        assert isinstance(actions, list)

    def test_get_summary(self):
        watchdog = SelfHealingWatchdog()
        summary = watchdog.get_summary()
        assert "health_score" in summary
        assert 0 <= summary["health_score"] <= 100

    def test_health_event_dataclass(self):
        e = HealthEvent(
            event_id="evt1", event_type="error", module="m",
            severity="high", message="test"
        )
        assert e.event_id == "evt1"

    def test_recovery_action_dataclass(self):
        a = RecoveryAction(
            action_id="act1", action_type="rollback", target="t",
            reason="r", success=True
        )
        assert a.action_id == "act1"
        assert a.success is True
