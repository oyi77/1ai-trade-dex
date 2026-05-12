"""Tests for sandbox validator 4-gate pipeline."""

import pytest

from backend.agi.sandbox.sandbox_validator import SandboxValidator, GateCheck
from backend.agi.sandbox.results import SandboxResult


class TestSandboxValidator:
    def setup_method(self):
        self.validator = SandboxValidator()

    def test_gate1_rejects_forbidden_imports(self):
        forbidden_code = """
import os
from sys import path
from backend.models.database import Database
from backend.data.polymarket_clob import PolymarketClient
"""
        result = self.validator.validate(forbidden_code)
        assert result.status == "failed"
        assert "gate1_import_safety" in result.gates_failed
        assert any("Forbidden import" in err for err in result.errors)

    def test_gate1_allows_safe_imports(self):
        safe_code = """
import json
import math
from datetime import datetime
from typing import List, Dict

def get_data():
    return {"status": "ok"}
"""
        result = self.validator.validate(safe_code)
        assert result.status == "passed"
        assert "gate1_import_safety" in result.gates_passed

    def test_gate2_rejects_exec_function(self):
        dangerous_code = """
def run_code():
    exec("print('hello')")
"""
        result = self.validator.validate(dangerous_code)
        assert result.status == "failed"
        assert "gate2_ast_safety" in result.gates_failed
        assert any("exec" in err for err in result.errors)

    def test_gate2_rejects_eval_function(self):
        dangerous_code = """
def calculate():
    return eval("1 + 2")
"""
        result = self.validator.validate(dangerous_code)
        assert result.status == "failed"
        assert "gate2_ast_safety" in result.gates_failed
        assert any("eval" in err for err in result.errors)

    def test_gate2_rejects_compile_function(self):
        dangerous_code = """
def create_code():
    compile("x = 1", "<string>", "exec")
"""
        result = self.validator.validate(dangerous_code)
        assert result.status == "failed"
        assert "gate2_ast_safety" in result.gates_failed
        assert any("compile" in err for err in result.errors)

    def test_gate2_allows_safe_code(self):
        safe_code = """
def add_numbers(a, b):
    return a + b

result = add_numbers(1, 2)
"""
        result = self.validator.validate(safe_code)
        assert result.status == "passed"
        assert "gate2_ast_safety" in result.gates_passed

    def test_gate3_rejects_excessive_lines(self):
        excessive_lines = "\n".join(["pass  # line {}".format(i) for i in range(501)])
        excessive_lines += "\nreturn True"
        result = self.validator.validate(excessive_lines)
        assert result.status == "failed"
        assert "gate3_resource_limits" in result.gates_failed
        assert "exceeds 500 line limit" in result.warnings[0]

    def test_gate3_rejects_too_many_loops(self):
        too_many_loops = """
def process():
    for i in range(10):
        for j in range(10):
            for k in range(10):
                for l in range(10):
                    for m in range(10):
                        for n in range(10):
                            for o in range(10):
                                for p in range(10):
                                    for q in range(10):
                                        for r in range(10):
                                            for s in range(10):
                                                pass
    return True
"""
        result = self.validator.validate(too_many_loops)
        assert result.status == "failed"
        assert "gate3_resource_limits" in result.gates_failed
        assert "Too many loops" in result.warnings[0]

    def test_gate3_allows_safe_resource_usage(self):
        """Gate 3 should allow code within limits."""
        safe_code = """
def process_items(items):
    results = []
    for item in items:
        results.append(item * 2)
    return results
"""
        result = self.validator.validate(safe_code)
        assert result.status == "passed"
        assert "gate3_resource_limits" in result.gates_passed

    def test_gate4_rejects_no_return_statement(self):
        """Gate 4 should reject code without return statement."""
        no_return_code = """
def process():
    x = 1 + 2
    print(x)
"""
        result = self.validator.validate(no_return_code)
        assert result.status == "failed"
        assert "gate4_output_validation" in result.gates_failed
        assert "No return statement" in result.errors[0]

    def test_gate4_allows_code_with_return(self):
        """Gate 4 should allow code with return statement."""
        with_return_code = """
def get_result():
    x = 1 + 2
    return x
"""
        result = self.validator.validate(with_return_code)
        assert result.status == "passed"
        assert "gate4_output_validation" in result.gates_passed

    def test_valid_code_passes_all_gates(self):
        """Valid code should pass all 4 gates."""
        valid_code = """
import json
from typing import Dict

def generate_signal():
    data = {"status": "ok", "confidence": 0.8}
    return json.dumps(data)
"""
        result = self.validator.validate(valid_code)
        assert result.status == "passed"
        assert len(result.gates_failed) == 0
        assert len(result.errors) == 0
        assert "gate1_import_safety" in result.gates_passed
        assert "gate2_ast_safety" in result.gates_passed
        assert "gate3_resource_limits" in result.gates_passed
        assert "gate4_output_validation" in result.gates_passed

    def test_invalid_code_fails_appropriate_gate(self):
        gate1_only_code = "import os"
        result = self.validator.validate(gate1_only_code)
        assert "gate1_import_safety" in result.gates_failed
        assert "gate2_ast_safety" in result.gates_failed

        gate4_only_code = "x = 1\nprint(x)"
        result = self.validator.validate(gate4_only_code)
        assert "gate1_import_safety" in result.gates_passed
        assert "gate2_ast_safety" in result.gates_passed
        assert "gate3_resource_limits" in result.gates_passed
        assert "gate4_output_validation" in result.gates_failed

    def test_result_has_required_fields(self):
        code = """
def test():
    return 1
"""
        result = self.validator.validate(code)
        assert hasattr(result, "run_id")
        assert hasattr(result, "status")
        assert hasattr(result, "gates_passed")
        assert hasattr(result, "gates_failed")
        assert hasattr(result, "errors")
        assert hasattr(result, "warnings")
        assert hasattr(result, "execution_time_ms")

    def test_result_to_dict(self):
        """SandboxResult.to_dict should return proper dictionary."""
        code = """
def test():
    return 1
"""
        result = self.validator.validate(code)
        result_dict = result.to_dict()
        assert isinstance(result_dict, dict)
        assert "run_id" in result_dict
        assert "status" in result_dict
        assert "gates_passed" in result_dict
        assert "gates_failed" in result_dict
        assert "errors" in result_dict
        assert "warnings" in result_dict
        assert "execution_time_ms" in result_dict
        assert "created_at" in result_dict
