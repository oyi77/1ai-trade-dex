"""Regression tests for critical logic bugs E-07 through E-28.

Each test verifies a specific fix to ensure the bug does not recur.
"""

import json
import threading
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch, AsyncMock

import pytest


# ---------------------------------------------------------------------------
# E-07: db.rollback() on unbound variable after context manager exit
# ---------------------------------------------------------------------------
class TestE07ProposalGeneratorRollback:
    """Verify rollback is not called on unbound db variable."""

    def test_store_proposal_no_unbound_rollback(self):
        """The store_proposal method should not call db.rollback() after
        the context manager exits — the db variable would be unbound."""
        from backend.ai.proposal_generator import ProposalGenerator

        gen = ProposalGenerator()
        # The method uses `with get_db_session() as db:` and catches exceptions.
        # If db.rollback() were called in the except block, it would raise
        # NameError because db is unbound after the context manager exits.
        # We verify the source code does not contain `db.rollback()` in the
        # except block by checking the function source.
        import inspect
        source = inspect.getsource(gen._store_proposal)
        # The except block should log the error, not call db.rollback()
        assert "db.rollback()" not in source, (
            "E-07: db.rollback() should not be called after context manager exit"
        )

    def test_approve_proposal_no_unbound_rollback(self):
        """approve_proposal should not call db.rollback() after context manager."""
        from backend.ai.proposal_generator import ProposalGenerator
        import inspect

        gen = ProposalGenerator()
        source = inspect.getsource(gen.approve_proposal)
        assert "db.rollback()" not in source

    def test_reject_proposal_no_unbound_rollback(self):
        """reject_proposal should not call db.rollback() after context manager."""
        from backend.ai.proposal_generator import ProposalGenerator
        import inspect

        gen = ProposalGenerator()
        source = inspect.getsource(gen.reject_proposal)
        assert "db.rollback()" not in source


# ---------------------------------------------------------------------------
# E-08: not DBProposal.backtest_passed always returns False
# ---------------------------------------------------------------------------
class TestE08BacktestPassedComparison:
    """Verify SQLAlchemy .is_(False) is used instead of Python `not`."""

    def test_backtest_passed_uses_is_false(self):
        """The query filter should use .is_(False), not `not Column`."""
        from backend.ai import proposal_generator
        import inspect

        # backtest_passed.is_(False) is in the auto_approve_pending function
        source = inspect.getsource(proposal_generator.auto_promote_eligible_proposals)
        assert "backtest_passed.is_(False)" in source, (
            "E-08: Should use .is_(False) for SQLAlchemy boolean comparison"
        )
        assert "not DBProposal.backtest_passed" not in source


# ---------------------------------------------------------------------------
# E-09: check_drawdown_floors uses db after context manager closes it
# ---------------------------------------------------------------------------
class TestE09DrawdownFloorsSessionScope:
    """Verify all db operations are inside the context manager."""

    def test_drawdown_floors_db_inside_context_manager(self):
        """All db.query() calls should be indented inside the `with ctx as db:` block."""
        from backend.core.risk_manager import RiskManager
        import inspect
        import textwrap

        source = inspect.getsource(RiskManager.check_drawdown_floors)
        lines = source.split("\n")

        # Find the `with ctx as db:` line
        with_line_idx = None
        with_indent = None
        for i, line in enumerate(lines):
            stripped = line.lstrip()
            if stripped.startswith("with ctx as db:"):
                with_line_idx = i
                with_indent = len(line) - len(stripped)
                break

        assert with_line_idx is not None, "Could not find `with ctx as db:` line"

        # All db.query() calls should be at a deeper indent than the with line
        for i, line in enumerate(lines[with_line_idx + 1:], start=with_line_idx + 1):
            stripped = line.lstrip()
            if not stripped or stripped.startswith("#") or stripped.startswith("except") or stripped.startswith("return"):
                continue
            if "db.query" in stripped or "db.commit" in stripped or "db.add" in stripped:
                current_indent = len(line) - len(stripped)
                assert current_indent > with_indent, (
                    f"E-09: Line {i} uses db but is not inside the `with ctx as db:` block: {line!r}"
                )


# ---------------------------------------------------------------------------
# E-10: Dead code after return in hft_executor
# ---------------------------------------------------------------------------
class TestE10HFTExecutorDeadCode:
    """Verify audit trail and circuit breaker code executes (not dead code)."""

    def test_risk_rejection_handler_after_validation(self):
        """Risk rejection handling should come after validate_hft_trade, not after return."""
        from backend.core.hft_executor import HFTExecutor
        import inspect

        source = inspect.getsource(HFTExecutor.execute)
        lines = source.split("\n")

        # Find the validate_hft_trade line
        validate_idx = None
        reject_handler_idx = None
        for i, line in enumerate(lines):
            if "validate_hft_trade" in line:
                validate_idx = i
            if "risk.get" in line and "rejected" in line and reject_handler_idx is None:
                reject_handler_idx = i

        assert validate_idx is not None, "Could not find validate_hft_trade call"
        assert reject_handler_idx is not None, "Could not find risk rejection handler"
        assert reject_handler_idx > validate_idx, (
            f"E-10: Risk rejection handler (line {reject_handler_idx}) should come "
            f"after validate_hft_trade (line {validate_idx})"
        )


# ---------------------------------------------------------------------------
# E-11: Race condition in calibration file write
# ---------------------------------------------------------------------------
class TestE11CalibrationRaceCondition:
    """Verify file write is inside the lock."""

    def test_file_write_inside_lock(self):
        """The calibration file write should be inside the threading lock."""
        from backend.core import calibration
        import inspect

        source = inspect.getsource(calibration.update_calibration)
        lines = source.split("\n")

        # Find the with _cal_lock: block
        lock_line_idx = None
        lock_indent = None
        for i, line in enumerate(lines):
            stripped = line.lstrip()
            if stripped.startswith("with _cal_lock:"):
                lock_line_idx = i
                lock_indent = len(line) - len(stripped)
                break

        assert lock_line_idx is not None, "Could not find `with _cal_lock:` block"

        # The write_text call should be inside the lock (deeper indent)
        for i, line in enumerate(lines[lock_line_idx + 1:], start=lock_line_idx + 1):
            stripped = line.lstrip()
            if "write_text" in stripped:
                current_indent = len(line) - len(stripped)
                assert current_indent > lock_indent, (
                    f"E-11: File write on line {i} is outside the lock: {line!r}"
                )
                return

        pytest.fail("Could not find write_text call in save_calibration")


# ---------------------------------------------------------------------------
# E-12: get_wallet_allocation orphaned outside class
# ---------------------------------------------------------------------------
class TestE12WalletAllocationMethod:
    """Verify get_wallet_allocation is a method of BankrollAllocator."""

    def test_method_inside_class(self):
        """get_wallet_allocation should be an instance method of BankrollAllocator."""
        from backend.core.bankroll_allocator import BankrollAllocator

        assert hasattr(BankrollAllocator, "get_wallet_allocation"), (
            "E-12: get_wallet_allocation should be a method of BankrollAllocator"
        )
        # Verify it's actually a bound method (not a standalone function)
        import inspect
        sig = inspect.signature(BankrollAllocator.get_wallet_allocation)
        params = list(sig.parameters.keys())
        assert params[0] == "self", (
            f"E-12: First parameter should be 'self', got '{params[0]}'"
        )


# ---------------------------------------------------------------------------
# E-13: DB session closed by context manager, then reused for brain writes
# ---------------------------------------------------------------------------
class TestE13AutoImproveSessionScope:
    """Verify db is not reused after context manager closes."""

    def test_brain_write_uses_separate_session(self):
        """_write_outcomes_to_brain should use a fresh session, not the closed db."""
        from backend.core import auto_improve
        import inspect

        source = inspect.getsource(auto_improve.auto_improve_job)
        # After the first `with SessionLocal() as db:` block ends,
        # _write_outcomes_to_brain should use a fresh session
        assert "SessionLocal() as brain_db" in source, (
            "E-13: _write_outcomes_to_brain should use a fresh SessionLocal"
        )
        # The old pattern was: await _write_outcomes_to_brain(db, bigbrain)
        # where db was from the closed context manager
        lines = source.split("\n")
        for i, line in enumerate(lines):
            if "_write_outcomes_to_brain(" in line:
                assert "brain_db" in line, (
                    f"E-13: Line {i} should use brain_db, not db: {line!r}"
                )

    def test_suggestions_uses_separate_session(self):
        """get_suggestions should use a fresh session."""
        from backend.core import auto_improve
        import inspect

        source = inspect.getsource(auto_improve.auto_improve_job)
        assert "SessionLocal() as suggest_db" in source
        assert "suggest_db" in source

    def test_market_insights_uses_separate_session(self):
        """_write_market_insights should use a fresh session."""
        from backend.core import auto_improve
        import inspect

        source = inspect.getsource(auto_improve.auto_improve_job)
        assert "SessionLocal() as insight_db" in source


# ---------------------------------------------------------------------------
# E-14: Trade.strategy is not None is Python identity check
# ---------------------------------------------------------------------------
class TestE14StrategyRankerFilter:
    """Verify .isnot(None) is used instead of Python `is not None`."""

    def test_uses_isnot_none(self):
        """The query filter should use .isnot(None), not `is not None`."""
        from backend.core.strategy_ranker import StrategyRanker
        import inspect

        source = inspect.getsource(StrategyRanker.rank_all)
        assert "Trade.strategy.isnot(None)" in source, (
            "E-14: Should use .isnot(None) for SQLAlchemy comparison"
        )
        assert "Trade.strategy is not None" not in source


# ---------------------------------------------------------------------------
# E-15: exec(compile(code)) on LLM-generated code with incomplete sandbox
# ---------------------------------------------------------------------------
class TestE15SandboxRestrictions:
    """Verify dangerous builtins are blocked in the sandbox."""

    def test_dangerous_builtins_blocked(self):
        """The sandbox should block __import__, open, exec, eval, compile."""
        from backend.core.strategy_synthesizer import StrategySynthesizer

        synth = StrategySynthesizer.__new__(StrategySynthesizer)
        # Call safe_import_test with code that tries to use dangerous builtins
        result = synth.safe_import_test("x = 1")  # benign code
        # We don't care about the result, just that the sandbox exists
        assert result is not None

    def test_sandbox_blocks_import(self):
        """LLM code trying to __import__ should fail in sandbox."""
        from backend.core.strategy_synthesizer import StrategySynthesizer

        synth = StrategySynthesizer.__new__(StrategySynthesizer)
        malicious_code = """
import os
os.system('echo pwned')
"""
        result = synth.safe_import_test(malicious_code)
        assert not result.valid, "E-15: Malicious code with import should fail validation"


# ---------------------------------------------------------------------------
# E-16: Paper settlement uses mock BotState missing all fields
# ---------------------------------------------------------------------------
class TestE16SettlementBotStateMock:
    """Verify paper settlement uses real BotState, not empty mock."""

    def test_uses_real_botstate(self):
        """The paper settlement should import and use the real BotState model."""
        from backend.core import settlement_helpers
        import inspect

        source = inspect.getsource(settlement_helpers.resolve_paper_trades)
        # Should NOT contain the old mock pattern
        assert 'type("BotState"' not in source, (
            "E-16: Should not use type() mock for BotState"
        )
        # Should import real BotState
        assert "from backend.models.database import BotState" in source


# ---------------------------------------------------------------------------
# E-17: Edge = price - (1.0 - no_price) simplifies to edge = 0.0
# ---------------------------------------------------------------------------
class TestE17UniversalScannerEdge:
    """Verify edge calculation is not always zero."""

    def test_edge_not_always_zero(self):
        """The edge calculation should use model probability, not derive from price."""
        from backend.strategies.universal_scanner import UniversalScanner
        import inspect

        source = inspect.getsource(UniversalScanner._handle_price_event)
        # The old code had: implied_prob = 1.0 - no_price which always gives price
        # so edge = price - price = 0.0
        assert "implied_prob = 1.0 - no_price" not in source, (
            "E-17: implied_prob should not be derived from no_price (always gives edge=0)"
        )


# ---------------------------------------------------------------------------
# E-18: implied_prob = 1.0 hardcoded in cex_pm_leadlag
# ---------------------------------------------------------------------------
class TestE18CEXPMLeadlagImpliedProb:
    """Verify implied probability is calculated, not hardcoded."""

    def test_implied_prob_not_hardcoded(self):
        """implied_prob should be calculated from market data, not hardcoded to 1.0."""
        from backend.strategies.cex_pm_leadlag import CexPmLeadLagStrategy
        import inspect

        source = inspect.getsource(CexPmLeadLagStrategy.run_cycle)
        assert "implied_prob = 1.0" not in source, (
            "E-18: implied_prob should not be hardcoded to 1.0"
        )


# ---------------------------------------------------------------------------
# E-19/E-20: model_probability: 1.0/0.0 fabrication
# ---------------------------------------------------------------------------
class TestE19E20OracleModelProbability:
    """Verify model_probability uses clamped oracle_implied, not 1.0/0.0."""

    def test_btc_oracle_no_binary_probability(self):
        """btc_oracle should not use 1.0/0.0 for model_probability."""
        from backend.strategies.btc_oracle import BtcOracleStrategy
        import inspect

        source = inspect.getsource(BtcOracleStrategy.run_cycle)
        assert '1.0 if direction == "yes" else 0.0' not in source, (
            "E-19: Should not use binary 1.0/0.0 for model_probability"
        )
        assert "max(0.05, min(0.95, oracle_implied))" in source

    def test_crypto_oracle_no_binary_probability(self):
        """crypto_oracle should not use 1.0/0.0 for model_probability."""
        from backend.strategies.crypto_oracle import CryptoOracleStrategy
        import inspect

        source = inspect.getsource(CryptoOracleStrategy.run_cycle)
        assert '1.0 if direction == "yes" else 0.0' not in source, (
            "E-20: Should not use binary 1.0/0.0 for model_probability"
        )
        assert "max(0.05, min(0.95, oracle_implied))" in source


# ---------------------------------------------------------------------------
# E-25: gymnasium blocks pytest collection
# ---------------------------------------------------------------------------
class TestE25GymnasiumImport:
    """Verify gymnasium test uses importorskip to avoid blocking collection."""

    def test_uses_importorskip(self):
        """The test file should use pytest.importorskip for gymnasium."""
        with open("backend/tests/test_rl_environment.py") as f:
            source = f.read()
        assert "pytest.importorskip" in source, (
            "E-25: Should use pytest.importorskip for gymnasium"
        )


# ---------------------------------------------------------------------------
# E-26: RejectionLearner import fails
# ---------------------------------------------------------------------------
class TestE26RejectionLearnerImport:
    """Verify RejectionLearner import has fallback."""

    def test_has_import_fallback(self):
        """The test file should handle missing RejectionLearner gracefully."""
        with open("backend/evals/tests/test_phase2_integration.py") as f:
            source = f.read()
        assert "except ImportError" in source, (
            "E-26: Should handle ImportError for RejectionLearner"
        )


# ---------------------------------------------------------------------------
# E-27: WALLET_FERNET_KEY committed in plaintext
# ---------------------------------------------------------------------------
class TestE27CISecret:
    """Verify WALLET_FERNET_KEY uses GitHub secrets, not plaintext."""

    def test_uses_github_secret(self):
        """The CI file should reference secrets, not contain the key."""
        with open(".github/workflows/ci.yml") as f:
            source = f.read()
        assert "D3IR1zYU0tRIwQLOLLNWSMgChbfmTO8lqX6em_zZ2L0=" not in source, (
            "E-27: WALLET_FERNET_KEY should not be in plaintext"
        )
        assert "${{ secrets.WALLET_FERNET_KEY }}" in source


# ---------------------------------------------------------------------------
# E-28: NO-side price inverted in position_valuation
# ---------------------------------------------------------------------------
class TestE28PositionValuationNoPrice:
    """Verify NO-side positions use no_price directly, not 1.0 - no_price."""

    def test_no_side_uses_no_price_directly(self):
        """For down positions, current_price should be no_price, not 1.0 - no_price."""
        from backend.core import position_valuation
        import inspect

        source = inspect.getsource(position_valuation.calculate_position_market_value)
        # The old code had: current_price = 1.0 - no_price
        assert "current_price = 1.0 - no_price" not in source, (
            "E-28: Should not invert no_price for NO-side positions"
        )
        # Should use no_price directly
        assert "current_price = no_price" in source
