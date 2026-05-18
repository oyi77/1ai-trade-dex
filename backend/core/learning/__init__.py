"""Learning subpackage — ML pipelines, calibration, self-debugging, auto-improvement."""
import importlib as _importlib

_SUBMODULES = [
    "learning_pipeline", "learning_system", "online_learner",
    "auto_improve", "self_debugger", "retrain_trigger",
    "calibration", "calibration_tracker",
]

def __getattr__(name: str):
    if name in _SUBMODULES:
        mod = _importlib.import_module(f"backend.core.learning.{name}")
        globals()[name] = mod
        return mod
    for s in _SUBMODULES:
        mod = _importlib.import_module(f"backend.core.learning.{s}")
        if hasattr(mod, name):
            globals()[name] = getattr(mod, name)
            return globals()[name]
    raise AttributeError(f"module 'backend.core.learning' has no attribute {name!r}")
