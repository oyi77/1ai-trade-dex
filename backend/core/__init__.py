"""Core execution kernel.

Subpackages:
    settlement  — trade settlement, reconciliation, dispute tracking
    risk        — risk management, circuit breakers, safety monitors
    scheduling  — APScheduler, job strategies, task management
    learning    — ML pipelines, calibration, self-debugging, auto-improvement
    wallet      — reconciliation, routing, allocation, equity tracking

Import directly from subpackages: ``from backend.core.risk.risk_manager import RiskManager``
"""


_SUBPACKAGES = {
    "settlement",
    "risk",
    "scheduling",
    "learning",
    "wallet",
    "strategy_executor",
}

# Aliases that live under backend.core.scheduling.<name> but are
# also accessed via backend.core.<name> for backward compatibility.
_SUBMODULE_ALIASES: dict[str, str] = {
    "scheduling_strategies": "backend.core.scheduling.scheduling_strategies",
    "settlement_helpers": "backend.core.settlement.settlement_helpers",
}


def __getattr__(name: str):
    """Lazy re-export from subpackages to avoid circular imports."""
    import importlib

    if name in _SUBPACKAGES:
        mod = importlib.import_module(f"backend.core.{name}")
        globals()[name] = mod
        return mod
    if name in _SUBMODULE_ALIASES:
        mod = importlib.import_module(_SUBMODULE_ALIASES[name])
        globals()[name] = mod
        return mod
    raise AttributeError(f"module 'backend.core' has no attribute {name!r}")
