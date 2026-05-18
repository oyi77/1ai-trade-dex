"""Settlement subpackage — trade settlement, reconciliation, dispute tracking."""
import importlib as _importlib

_SUBMODULES = [
    "settlement", "settlement_helpers", "settlement_ws",
    "settlement_capture", "auto_redeem", "dispute_tracker",
]

def __getattr__(name: str):
    if name in _SUBMODULES:
        mod = _importlib.import_module(f"backend.core.settlement.{name}")
        globals()[name] = mod
        return mod
    for s in _SUBMODULES:
        mod = _importlib.import_module(f"backend.core.settlement.{s}")
        if hasattr(mod, name):
            globals()[name] = getattr(mod, name)
            return globals()[name]
    raise AttributeError(f"module 'backend.core.settlement' has no attribute {name!r}")
