"""Wallet subpackage — reconciliation, routing, allocation, equity tracking.

Supports both submodule imports (``from backend.core.wallet import bankroll_allocator``)
and symbol imports (``from backend.core.wallet import WalletReconciler``).
"""
import importlib as _importlib


def __getattr__(name: str):
    """Lazy import: first check if it's a submodule name, then search symbols."""
    # Check if it's a submodule
    _submodules = [
        "wallet_reconciliation",
        "wallet_router",
        "wallet_auto_discovery",
        "bankroll_reconciliation",
        "bankroll_allocator",
        "equity_calculator",
    ]
    if name in _submodules:
        mod = _importlib.import_module(f"backend.core.wallet.{name}")
        globals()[name] = mod
        return mod

    # Search submodules for symbol
    _modules = [f"backend.core.wallet.{n}" for n in _submodules]
    for mod_path in _modules:
        mod = _importlib.import_module(mod_path)
        if hasattr(mod, name):
            val = getattr(mod, name)
            globals()[name] = val
            return val
    raise AttributeError(f"module 'backend.core.wallet' has no attribute {name!r}")
