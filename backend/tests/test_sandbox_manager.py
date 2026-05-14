import pytest
from backend.agi.sandbox.sandbox_manager import SandboxManager
from backend.agi.sandbox.results import SandboxResult


class TestSandboxManager:
    def setup_method(self):
        # Import nodes to trigger @node_registry.plugin decorators and populate the registry
        import backend.agi.nodes  # noqa: F401
        self.manager = SandboxManager()

    @pytest.mark.asyncio
    async def test_validate_strategy_runs_4_gate_pipeline(self):
        code = """
def get_data():
    return {"status": "ok"}
"""
        result = await self.manager.validate_strategy(code)
        assert isinstance(result, SandboxResult)
        assert result.status == "passed"
        assert "gate1_import_safety" in result.gates_passed
        assert "gate2_ast_safety" in result.gates_passed
        assert "gate3_resource_limits" in result.gates_passed
        assert "gate4_output_validation" in result.gates_passed

    @pytest.mark.asyncio
    async def test_validate_strategy_rejects_forbidden_imports(self):
        code = """
import os
from sys import path
"""
        result = await self.manager.validate_strategy(code)
        assert result.status == "failed"
        assert "gate1_import_safety" in result.gates_failed

    @pytest.mark.asyncio
    async def test_validate_strategy_rejects_exec_function(self):
        code = """
def run_code():
    exec("print('hello')")
"""
        result = await self.manager.validate_strategy(code)
        assert result.status == "failed"
        assert "gate2_ast_safety" in result.gates_failed

    @pytest.mark.asyncio
    async def test_validate_strategy_rejects_eval_function(self):
        code = """
def calculate():
    return eval("1 + 2")
"""
        result = await self.manager.validate_strategy(code)
        assert result.status == "failed"
        assert "gate2_ast_safety" in result.gates_failed

    @pytest.mark.asyncio
    async def test_validate_strategy_rejects_excessive_lines(self):
        code = "\n".join(["pass  # line {}".format(i) for i in range(501)])
        result = await self.manager.validate_strategy(code)
        assert result.status == "failed"
        assert "gate3_resource_limits" in result.gates_failed

    @pytest.mark.asyncio
    async def test_validate_strategy_rejects_too_many_loops(self):
        code = """
for i in range(10):
    pass
for j in range(10):
    pass
for k in range(10):
    pass
for l in range(10):
    pass
for m in range(10):
    pass
for n in range(10):
    pass
for o in range(10):
    pass
for p in range(10):
    pass
for q in range(10):
    pass
for r in range(10):
    pass
for s in range(10):
    pass
"""
        result = await self.manager.validate_strategy(code)
        assert result.status == "failed"
        assert "gate3_resource_limits" in result.gates_failed

    @pytest.mark.asyncio
    async def test_validate_strategy_rejects_no_return(self):
        code = """
def get_data():
    print("hello")
"""
        result = await self.manager.validate_strategy(code)
        assert result.status == "failed"
        assert "gate4_output_validation" in result.gates_failed

    @pytest.mark.asyncio
    async def test_validate_strategy_accepts_valid_strategy(self):
        code = """
def analyze_market(data):
    return {"prediction": "up", "confidence": 0.8}
"""
        result = await self.manager.validate_strategy(code)
        assert result.status == "passed"
        assert all(gate in result.gates_passed for gate in [
            "gate1_import_safety",
            "gate2_ast_safety",
            "gate3_resource_limits",
            "gate4_output_validation",
        ])

    @pytest.mark.asyncio
    async def test_validate_node_allows_safe_node(self):

        state = {"prices": [100, 101, 102]}
        result = await self.manager.validate_node("regime_detector", state)
        assert isinstance(result, SandboxResult)
        assert result.status == "failed"
        assert any("requires live data" in err for err in result.errors)

    @pytest.mark.asyncio
    async def test_validate_node_rejects_node_requiring_db(self):
        state = {"test": "data"}
        result = await self.manager.validate_node("regime_detector", state)
        assert isinstance(result, SandboxResult)
        assert result.status == "failed"
        assert any("requires live data" in err for err in result.errors)

    @pytest.mark.asyncio
    async def test_validate_node_rejects_unknown_node(self):
        state = {"test": "data"}
        result = await self.manager.validate_node("nonexistent_node", state)
        assert isinstance(result, SandboxResult)
        assert result.status == "error"
        assert any("Node not found" in err for err in result.errors)

    def test_get_result_retrieves_previous_result(self):
        code = """
def add(a, b):
    return a + b
"""
        import asyncio

        async def run():
            result = await self.manager.validate_strategy(code)
            return result

        loop = asyncio.new_event_loop()
        result = loop.run_until_complete(run())
        loop.close()

        retrieved = self.manager.get_result(result.run_id)
        assert retrieved is not None
        assert retrieved.run_id == result.run_id
        assert retrieved.status == result.status

    def test_get_result_returns_none_for_unknown_id(self):
        result = self.manager.get_result("nonexistent_id")
        assert result is None

    def test_list_results_returns_all_results(self):
        code = """
def test():
    return 42
"""
        import asyncio

        async def run():
            r1 = await self.manager.validate_strategy(code)
            r2 = await self.manager.validate_strategy(code + " # comment")
            return r1, r2

        loop = asyncio.new_event_loop()
        r1, r2 = loop.run_until_complete(run())
        loop.close()

        all_results = self.manager.list_results()
        assert len(all_results) >= 2
        assert any(r.run_id == r1.run_id for r in all_results)
        assert any(r.run_id == r2.run_id for r in all_results)

    def test_list_results_returns_empty_list_when_no_results(self):
        new_manager = SandboxManager()
        results = new_manager.list_results()
        assert results == []
