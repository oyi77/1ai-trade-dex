"""Regression tests for scheduler queue-mode wiring."""

import ast
from pathlib import Path


def test_queue_worker_mode_keeps_settlement_check_scheduled():
    """Queue mode must not remove settlement_check without a periodic queue producer."""

    source = Path("backend/core/scheduler.py").read_text()
    tree = ast.parse(source)

    assignments = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        if any(
            isinstance(target, ast.Name) and target.id == "jobs_to_remove"
            for target in node.targets
        ):
            assignments.append(node.value)

    assert assignments, "scheduler should explicitly define queue-mode jobs_to_remove"
    assert all(
        "settlement_check" not in ast.unparse(value) for value in assignments
    ), "settlement_check must remain scheduled so live exposure can be released"


def test_settlement_check_has_misfire_grace_for_transient_lock_delays():
    """Settlement should recover from short scheduler stalls instead of being dropped."""

    source = Path("backend/core/scheduler.py").read_text()
    tree = ast.parse(source)
    persist_calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "_persist_and_add_job"
    ]

    settlement_calls = [
        node
        for node in persist_calls
        if any(
            keyword.arg == "id" and isinstance(keyword.value, ast.Constant)
            and keyword.value.value == "settlement_check"
            for keyword in node.keywords
        )
    ]
    assert settlement_calls, "settlement_check must be scheduled explicitly"
    assert all(
        any(
            keyword.arg == "misfire_grace_time"
            and isinstance(keyword.value, ast.Constant)
            and keyword.value.value >= 60
            for keyword in call.keywords
        )
        for call in settlement_calls
    ), "settlement_check needs grace time to catch up after bounded DB lock waits"


def test_auto_redeem_is_registered_for_crash_recovery_when_enabled():
    """Automatic redemption must survive scheduler restarts when explicitly enabled."""

    source = Path("backend/core/scheduler.py").read_text()
    tree = ast.parse(source)

    registry = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name) and target.id == "JOB_FUNCTION_REGISTRY"
            for target in node.targets
        )
    )
    registry_source = ast.unparse(registry)
    assert "auto_redeem_job" in registry_source

    persist_calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "_persist_and_add_job"
    ]

    auto_redeem_calls = [
        node
        for node in persist_calls
        if any(
            keyword.arg == "id"
            and isinstance(keyword.value, ast.Constant)
            and keyword.value.value == "auto_redeem"
            for keyword in node.keywords
        )
    ]
    assert auto_redeem_calls, "auto_redeem must be persisted when scheduled"
    assert all(
        any(
            keyword.arg == "misfire_grace_time"
            and isinstance(keyword.value, ast.Constant)
            and keyword.value.value >= 60
            for keyword in call.keywords
        )
        for call in auto_redeem_calls
    ), "auto_redeem needs grace time so brief scheduler stalls do not skip cleanup"


def test_postgres_for_update_applies_transaction_local_lock_timeouts():
    """BotState row locks must fail fast without moving async jobs to another loop."""

    source = Path("backend/models/database.py").read_text()
    tree = ast.parse(source)

    helper = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef)
        and node.name == "_apply_postgres_lock_timeouts"
    )
    helper_source = ast.unparse(helper)
    assert "SET LOCAL" in helper_source
    assert "lock_timeout" in helper_source
    assert "statement_timeout" in helper_source

    for_update_fn = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "for_update"
    )
    assert any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "_apply_postgres_lock_timeouts"
        for node in ast.walk(for_update_fn)
    ), "PostgreSQL FOR UPDATE paths must set transaction-local lock timeouts first"
