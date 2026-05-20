"""Scheduling subpackage — APScheduler, job strategies, task management."""

import importlib as _importlib

_SUBMODULES = [
    "scheduler",
    "scheduling_strategies",
    "fronttest_scheduler",
    "task_manager",
]


def __getattr__(name: str):
    if name in _SUBMODULES:
        mod = _importlib.import_module(f"backend.core.scheduling.{name}")
        globals()[name] = mod
        return mod
    for s in _SUBMODULES:
        mod = _importlib.import_module(f"backend.core.scheduling.{s}")
        if hasattr(mod, name):
            globals()[name] = getattr(mod, name)
            return globals()[name]
    raise AttributeError(f"module 'backend.core.scheduling' has no attribute {name!r}")
