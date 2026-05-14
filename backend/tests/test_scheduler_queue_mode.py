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
