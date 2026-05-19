"""Risk subpackage — risk management, circuit breakers, safety monitors."""
import importlib as _importlib

_SUBMODULES = [
    "risk_manager", "risk_manager_hft", "risk_profiles", "market_risk",
    "circuit_breaker", "circuit_breaker_pybreaker", "circuit_breaker_unified",
    "correlation_monitor", "crash_guardian", "safety",
    "position_sizer", "exposure_limits", "sanity_checks",
]

def __getattr__(name: str):
    if name in _SUBMODULES:
        mod = _importlib.import_module(f"backend.core.risk.{name}")
        globals()[name] = mod
        return mod
    for s in _SUBMODULES:
        mod = _importlib.import_module(f"backend.core.risk.{s}")
        if hasattr(mod, name):
            globals()[name] = getattr(mod, name)
            return globals()[name]
    raise AttributeError(f"module 'backend.core.risk' has no attribute {name!r}")
