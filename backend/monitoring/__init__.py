"""Monitoring and metrics for PolyEdge trading bot."""

import importlib as _importlib

_SUBMODULES = ["trade_journal", "disk_monitor", "agi_metrics"]

def __getattr__(name: str):
    if name in _SUBMODULES:
        mod = _importlib.import_module(f"backend.monitoring.{name}")
        globals()[name] = mod
        return mod
    for s in _SUBMODULES:
        mod = _importlib.import_module(f"backend.monitoring.{s}")
        if hasattr(mod, name):
            globals()[name] = getattr(mod, name)
            return globals()[name]
    raise AttributeError(f"module 'backend.monitoring' has no attribute {name!r}")

from .metrics import (
    increment_trades,
    increment_signals,
    update_pnl,
    update_bankroll,
    record_api_latency,
    increment_api_errors,
    increment_scans,
    increment_settlements,
    update_strategy_status,
    get_metrics
)

__all__ = [
    'increment_trades',
    'increment_signals',
    'update_pnl',
    'update_bankroll',
    'record_api_latency',
    'increment_api_errors',
    'increment_scans',
    'increment_settlements',
    'update_strategy_status',
    'get_metrics',
]
