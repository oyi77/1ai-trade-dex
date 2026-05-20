"""Tests for CodeRefactoringAgent."""

import json
import os
import tempfile
from unittest.mock import patch, MagicMock
import pytest

from backend.agi.code_refactorer import CodeRefactoringAgent


class TestCodeRefactoringAgent:
    """Test suite for CodeRefactoringAgent."""

    @pytest.fixture
    def agent(self):
        """Create a CodeRefactoringAgent instance."""
        return CodeRefactoringAgent()

    @pytest.fixture
    def temp_module(self):
        """Create a temporary Python module for testing."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write(
                """
def add(a, b):
    '''Add two numbers.'''
    return a + b

def multiply(a, b):
    '''Multiply two numbers.'''
    result = a * b
    return result
"""
            )
            f.flush()
            yield f.name
        # Cleanup
        if os.path.exists(f.name):
            os.unlink(f.name)

    def test_agent_initialization(self, agent):
        """Test agent initialization."""
        assert agent.provider_registry is not None
        assert agent.safety_monitor is not None
        assert agent.logger is not None

    def test_is_protected_path(self, agent):
        """Test protected path detection."""
        assert agent._is_protected_path("backend/core/safety.py")
        assert agent._is_protected_path("backend/strategies/base_strategy.py")
        assert not agent._is_protected_path("backend/agi/code_refactorer.py")
        assert not agent._is_protected_path("backend/utils/helpers.py")

    def test_validate_diff_valid(self, agent):
        """Test validation of a valid diff."""
        valid_diff = """--- a/test.py
+++ b/test.py
@@ -1,3 +1,3 @@
 def add(a, b):
-    return a + b
+    return a + b  # improved
"""
        assert agent._validate_diff(valid_diff) is True

    def test_validate_diff_empty(self, agent):
        """Test validation of empty diff."""
        assert agent._validate_diff("") is False
        assert agent._validate_diff(None) is False

    def test_validate_diff_invalid(self, agent):
        """Test validation of invalid diffs."""
        # Missing headers
        assert agent._validate_diff("some code changes") is False
        # Missing hunks
        assert agent._validate_diff("--- a/test.py\n+++ b/test.py\n") is False

    def test_create_backup(self, agent, temp_module):
        """Test backup creation."""
        backup_path = f"{temp_module}.backup"
        try:
            # Read and backup
            with open(temp_module, "r") as src:
                with open(backup_path, "w") as dst:
                    dst.write(src.read())

            # Verify backup exists and matches
            assert os.path.exists(backup_path)
            with open(temp_module, "r") as src:
                with open(backup_path, "r") as dst:
                    assert src.read() == dst.read()
        finally:
            if os.path.exists(backup_path):
                os.unlink(backup_path)

    def test_restore_backup(self, agent, temp_module):
        """Test backup restoration."""
        original_content = None
        backup_path = f"{temp_module}.backup"

        try:
            # Create backup with original content
            with open(temp_module, "r") as f:
                original_content = f.read()
            with open(backup_path, "w") as f:
                f.write(original_content)

            # Modify original file
            with open(temp_module, "w") as f:
                f.write("modified content")

            # Verify modification
            with open(temp_module, "r") as f:
                assert f.read() == "modified content"

            # Restore from backup
            agent._restore_backup(temp_module, backup_path)

            # Verify restoration
            with open(temp_module, "r") as f:
                assert f.read() == original_content

        finally:
            if os.path.exists(backup_path):
                os.unlink(backup_path)

    @patch("backend.agi.code_refactorer.subprocess.run")
    def test_run_module_tests_pass(self, mock_run, agent, temp_module):
        """Test running tests that pass."""
        # Mock successful pytest run
        mock_run.return_value = MagicMock(returncode=0, stdout="tests passed")

        # Create dummy test file
        test_path = temp_module.replace(".py", "/tests/test_dummy.py")
        os.makedirs(os.path.dirname(test_path), exist_ok=True)
        with open(test_path, "w") as f:
            f.write("# dummy test")

        try:
            result = agent.run_module_tests(temp_module.replace(".py", "/dummy.py"))
            assert result is True
            mock_run.assert_called_once()
        finally:
            # Cleanup
            if os.path.exists(test_path):
                os.unlink(test_path)

    @patch("backend.agi.code_refactorer.subprocess.run")
    def test_run_module_tests_fail(self, mock_run, agent, temp_module):
        """Test running tests that fail."""
        # Mock failed pytest run
        mock_run.return_value = MagicMock(
            returncode=1, stdout="tests failed", stderr="error"
        )

        # Create dummy test file
        test_path = temp_module.replace(".py", "/tests/test_dummy.py")
        os.makedirs(os.path.dirname(test_path), exist_ok=True)
        with open(test_path, "w") as f:
            f.write("# dummy test")

        try:
            result = agent.run_module_tests(temp_module.replace(".py", "/dummy.py"))
            assert result is False
        finally:
            # Cleanup
            if os.path.exists(test_path):
                os.unlink(test_path)

    def test_run_module_tests_no_tests(self, agent, temp_module):
        """Test when no tests exist."""
        # Should return True (pass) if no tests found
        result = agent.run_module_tests(temp_module)
        assert result is True

    @patch("backend.agi.code_refactorer.subprocess.run")
    def test_rollback_via_git(self, mock_run, agent, temp_module):
        """Test rollback via git checkout."""
        mock_run.return_value = MagicMock(returncode=0, stdout="checked out")

        result = agent.rollback(temp_module)
        assert result is True
        mock_run.assert_called_once()
        args = mock_run.call_args[0][0]
        assert "git" in args
        assert "checkout" in args

    def test_rollback_via_backup(self, agent, temp_module):
        """Test rollback via backup file."""
        backup_path = f"{temp_module}.backup"
        original_content = None

        try:
            # Create backup
            with open(temp_module, "r") as f:
                original_content = f.read()
            with open(backup_path, "w") as f:
                f.write(original_content)

            # Modify original
            with open(temp_module, "w") as f:
                f.write("modified")

            # Rollback
            result = agent.rollback(temp_module)
            assert result is True

            # Verify restoration
            with open(temp_module, "r") as f:
                assert f.read() == original_content

        finally:
            if os.path.exists(backup_path):
                os.unlink(backup_path)

    @patch("backend.agi.code_refactorer.subprocess.run")
    def test_apply_refactor_success(self, mock_run, agent, temp_module):
        """Test successful refactor application."""
        # Mock patch command success
        mock_run.return_value = MagicMock(returncode=0, stderr="")

        diff = """--- a/test.py
+++ b/test.py
@@ -1,3 +1,3 @@
 def add(a, b):
-    return a + b
+    return a + b  # improved
"""

        result = agent.apply_refactor(temp_module, diff)
        assert result is True

        # Verify backup was created
        backup_path = f"{temp_module}.backup"
        assert os.path.exists(backup_path)
        os.unlink(backup_path)

    @patch("backend.agi.code_refactorer.subprocess.run")
    def test_apply_refactor_patch_failure(self, mock_run, agent, temp_module):
        """Test refactor application when patch fails."""
        # Mock patch command failure
        mock_run.return_value = MagicMock(returncode=1, stderr="patch failed")

        diff = "invalid diff"

        result = agent.apply_refactor(temp_module, diff)
        assert result is False

    def test_apply_refactor_invalid_diff(self, agent, temp_module):
        """Test refactor application with invalid diff."""
        result = agent.apply_refactor(temp_module, "not a valid diff")
        assert result is False

    @patch("backend.agi.code_refactorer.SessionLocal")
    def test_log_refactor_action(self, mock_session_local, agent, temp_module):
        """Test logging refactor actions."""
        # Mock database session
        mock_db = MagicMock()
        mock_bot_state = MagicMock()
        mock_bot_state.misc_data = json.dumps({"refactor_history": []})
        mock_db.query.return_value.filter.return_value.first.return_value = (
            mock_bot_state
        )
        mock_session_local.return_value = mock_db

        agent._log_refactor_action(
            "test_action", temp_module, "test goal", True, "test details"
        )

        # Verify database was updated
        mock_db.commit.assert_called_once()
        updated_misc = json.loads(mock_bot_state.misc_data)
        assert "refactor_history" in updated_misc
        assert len(updated_misc["refactor_history"]) > 0

    @patch.object(CodeRefactoringAgent, "propose_refactor")
    @patch.object(CodeRefactoringAgent, "apply_refactor")
    @patch.object(CodeRefactoringAgent, "run_module_tests")
    @patch.object(CodeRefactoringAgent, "_log_refactor_action")
    async def test_full_refactor_cycle_success(
        self,
        mock_log,
        mock_tests,
        mock_apply,
        mock_propose,
        agent,
        temp_module,
    ):
        """Test successful full refactor cycle."""
        mock_propose.return_value = "--- a/test\n+++ b/test\n@@ -1 +1 @@"
        mock_apply.return_value = True
        mock_tests.return_value = True

        success, msg = await agent.full_refactor_cycle(
            temp_module, "improve code", require_approval=False
        )

        assert success is True
        assert "successfully" in msg.lower()
        mock_propose.assert_called_once()
        mock_apply.assert_called_once()
        mock_tests.assert_called_once()

    @patch.object(CodeRefactoringAgent, "propose_refactor")
    @patch.object(CodeRefactoringAgent, "_log_refactor_action")
    async def test_full_refactor_cycle_propose_failure(
        self, mock_log, mock_propose, agent, temp_module
    ):
        """Test full cycle when proposal fails."""
        mock_propose.return_value = None

        success, msg = await agent.full_refactor_cycle(
            temp_module, "improve code", require_approval=False
        )

        assert success is False
        assert "Failed to propose" in msg

    @patch.object(CodeRefactoringAgent, "propose_refactor")
    @patch.object(CodeRefactoringAgent, "_log_refactor_action")
    async def test_full_refactor_cycle_protected_path(
        self, mock_log, mock_propose, agent
    ):
        """Test full cycle on protected path with requirement."""
        mock_propose.return_value = "--- a/test\n+++ b/test\n@@ -1 +1 @@"

        success, msg = await agent.full_refactor_cycle(
            "backend/core/safety.py", "improve code", require_approval=True
        )

        assert success is False
        assert "approval" in msg.lower()

    @patch.object(CodeRefactoringAgent, "propose_refactor")
    @patch.object(CodeRefactoringAgent, "apply_refactor")
    @patch.object(CodeRefactoringAgent, "run_module_tests")
    @patch.object(CodeRefactoringAgent, "rollback")
    @patch.object(CodeRefactoringAgent, "_log_refactor_action")
    async def test_full_refactor_cycle_test_failure(
        self,
        mock_log,
        mock_rollback,
        mock_tests,
        mock_apply,
        mock_propose,
        agent,
        temp_module,
    ):
        """Test full cycle when tests fail (triggers rollback)."""
        mock_propose.return_value = "--- a/test\n+++ b/test\n@@ -1 +1 @@"
        mock_apply.return_value = True
        mock_tests.return_value = False  # Tests fail

        success, msg = await agent.full_refactor_cycle(
            temp_module, "improve code", require_approval=False
        )

        assert success is False
        assert "rolled back" in msg.lower()
        mock_rollback.assert_called_once_with(temp_module)


# Integration tests (if database is available)
class TestCodeRefactorerIntegration:
    """Integration tests for CodeRefactoringAgent."""

    @pytest.fixture
    def agent(self):
        """Create agent for integration tests."""
        return CodeRefactoringAgent()

    def test_agent_can_initialize(self, agent):
        """Test that agent initializes without errors."""
        assert agent is not None
        assert hasattr(agent, "full_refactor_cycle")
        assert hasattr(agent, "propose_refactor")
        assert hasattr(agent, "apply_refactor")
        assert hasattr(agent, "rollback")


if __name__ == "__main__":
    pytest.main([__file__, "-xvs"])
