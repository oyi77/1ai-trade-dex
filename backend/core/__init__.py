"""Core execution kernel.

Subpackages:
    settlement  — trade settlement, reconciliation, dispute tracking
    risk        — risk management, circuit breakers, safety monitors
    scheduling  — APScheduler, job strategies, task management
    learning    — ML pipelines, calibration, self-debugging, auto-improvement
    wallet      — reconciliation, routing, allocation, equity tracking

All flat imports (e.g. ``from backend.core.settlement import ...``) continue
to work via backward-compatible shim modules at the package root.
"""


def __getattr__(name: str):
    """Lazy re-export from subpackages to avoid circular imports."""
    _subpackages = {
        "settlement",
        "risk",
        "scheduling",
        "learning",
        "wallet",
    }
    if name in _subpackages:
        import importlib
        mod = importlib.import_module(f"backend.core.{name}")
        globals()[name] = mod
        return mod
    raise AttributeError(f"module 'backend.core' has no attribute {name!r}")
