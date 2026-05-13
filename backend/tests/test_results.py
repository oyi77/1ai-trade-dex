from datetime import datetime
from backend.agi.sandbox.results import SandboxResult


class TestSandboxResult:
    def test_constructor_defaults(self):
        result = SandboxResult(run_id="test-run", status="passed")

        assert result.run_id == "test-run"
        assert result.status == "passed"
        assert result.gates_passed == []
        assert result.gates_failed == []
        assert result.errors == []
        assert result.warnings == []
        assert result.execution_time_ms == 0.0
        assert isinstance(result.created_at, datetime)

    def test_passed_property(self):
        passed_result = SandboxResult(run_id="test", status="passed")
        failed_result = SandboxResult(run_id="test", status="failed")

        assert passed_result.passed is True
        assert failed_result.passed is False

    def test_passed_property_with_error_status(self):
        error_result = SandboxResult(run_id="test", status="error")
        assert error_result.passed is False

    def test_to_dict(self):
        now = datetime.now()
        result = SandboxResult(
            run_id="test-run-123",
            status="passed",
            gates_passed=["gate1", "gate2"],
            gates_failed=["gate3"],
            errors=["error1"],
            warnings=["warning1"],
            execution_time_ms=150.5,
            created_at=now,
        )

        result_dict = result.to_dict()

        assert result_dict["run_id"] == "test-run-123"
        assert result_dict["status"] == "passed"
        assert result_dict["gates_passed"] == ["gate1", "gate2"]
        assert result_dict["gates_failed"] == ["gate3"]
        assert result_dict["errors"] == ["error1"]
        assert result_dict["warnings"] == ["warning1"]
        assert result_dict["execution_time_ms"] == 150.5
        assert isinstance(result_dict["created_at"], str)

    def test_to_dict_serializes_datetime(self):
        result = SandboxResult(run_id="test", status="passed", created_at=datetime(2024, 1, 1, 12, 0, 0))

        result_dict = result.to_dict()

        assert result_dict["created_at"] == "2024-01-01T12:00:00"

    def test_result_with_all_empty_lists(self):
        result = SandboxResult(run_id="test", status="failed")

        assert result.gates_passed == []
        assert result.gates_failed == []
        assert result.errors == []
        assert result.warnings == []

    def test_result_with_non_empty_gates(self):
        result = SandboxResult(
            run_id="test",
            status="passed",
            gates_passed=["syntax", "lint", "sandbox"],
            gates_failed=[],
        )

        assert len(result.gates_passed) == 3
        assert "syntax" in result.gates_passed

    def test_result_with_non_empty_errors(self):
        result = SandboxResult(
            run_id="test",
            status="failed",
            errors=["Syntax error", "Validation failed"],
        )

        assert len(result.errors) == 2
        assert "Syntax error" in result.errors


def test_sandbox_result_passed_states():
    result_passed = SandboxResult(run_id="test", status="passed")
    result_failed = SandboxResult(run_id="test", status="failed")

    assert result_passed.passed is True
    assert result_failed.passed is False


def test_sandbox_result_construction_order():
    now = datetime.now()
    result = SandboxResult(
        run_id="run-1",
        status="passed",
        created_at=now,
        gates_passed=["a", "b"],
        gates_failed=["c"],
        errors=["error"],
        warnings=["warn"],
        execution_time_ms=100.0,
    )

    assert result.run_id == "run-1"
    assert result.status == "passed"
    assert result.gates_passed == ["a", "b"]
    assert result.gates_failed == ["c"]
    assert result.errors == ["error"]
    assert result.warnings == ["warn"]
    assert result.execution_time_ms == 100.0
    assert result.created_at == now


def test_sandbox_result_default_empty_lists():
    result = SandboxResult(run_id="test", status="passed")

    assert result.gates_passed == []
    assert result.gates_failed == []
    assert result.errors == []
    assert result.warnings == []


def test_sandbox_result_zero_execution_time():
    result = SandboxResult(run_id="test", status="passed", execution_time_ms=0)

    assert result.execution_time_ms == 0


def test_sandbox_result_large_execution_time():
    result = SandboxResult(run_id="test", status="passed", execution_time_ms=999999.99)

    assert result.execution_time_ms == 999999.99
