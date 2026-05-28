"""
Strategy Module Loader for PolyEdge.

Discovers and imports strategy modules to trigger auto-registration
in STRATEGY_REGISTRY. Separated from registry.py to break a circular
import deadlock: registry.py defines STRATEGY_REGISTRY and BaseStrategy;
loader.py imports FROM registry (correct direction) while importing
strategy modules that trigger __init_subclass__ auto-registration.
"""

import importlib
import os

from loguru import logger as log


def _skip_module(module_name: str) -> bool:
    """Return True for utility modules that should not be imported as strategies."""
    _SKIP = frozenset(
        {
            "backend.strategies.base",
            "backend.strategies.registry",
            "backend.strategies.loader",
            "backend.strategies.types_hft",
            "backend.strategies.wallet_sync",
        }
    )
    return module_name in _SKIP


def _discover_flat(package: str, path: str) -> list[str]:
    """Discover single-file modules in a flat package directory."""
    import pkgutil

    modules: list[str] = []
    for finder, name, ispkg in pkgutil.iter_modules([path]):
        if name.startswith("_") or ispkg:
            continue
        full = f"{package}.{name}"
        if not _skip_module(full):
            modules.append(full)
    return modules


def _discover_recursive(package_root: str, path_root: str) -> list[str]:
    """Recursively discover all leaf modules in a package tree."""

    modules: list[str] = []
    seen: set[str] = set()

    def _walk(pkg: str, dir_path: str) -> None:
        if not os.path.isdir(dir_path):
            return
        for entry in sorted(os.listdir(dir_path)):
            child = os.path.join(dir_path, entry)
            if os.path.isdir(child):
                init_file = os.path.join(child, "__init__.py")
                if os.path.isfile(init_file):
                    _walk(f"{pkg}.{entry}", child)
            elif entry.endswith(".py") and not entry.startswith("_"):
                name = entry[:-3]
                full = f"{pkg}.{name}"
                if full not in seen and not _skip_module(full):
                    seen.add(full)
                    modules.append(full)

    _walk(package_root, path_root)
    return modules


def load_all_strategies() -> None:
    """Import all strategy and strategy-module files to trigger auto-registration.

    Discovers modules dynamically by scanning ``backend/strategies/`` (flat)
    and ``backend/modules/`` (recursive). Any Python file that contains a
    ``BaseStrategy`` subclass with a ``name`` attribute will be auto-registered
    in ``STRATEGY_REGISTRY`` via ``__init_subclass__``.

    Dropping a new ``.py`` file into either tree is sufficient — no config
    changes needed.
    """

    # Access registry from the canonical module (loader → registry, not circular)
    from backend.strategies.registry import STRATEGY_REGISTRY

    strategies_dir = os.path.join(os.path.dirname(__file__))
    modules_dir = os.path.join(os.path.dirname(__file__), "..", "modules")

    # Import unified_arb package explicitly (skipped by _discover_flat because ispkg=True)
    try:
        importlib.import_module("backend.strategies.unified_arb")
    except Exception as e:
        log.warning(f"Could not load unified_arb package: {e}")

    candidates: list[str] = []
    candidates.extend(_discover_flat("backend.strategies", strategies_dir))
    candidates.extend(_discover_recursive("backend.modules", modules_dir))

    loaded = 0
    errors = 0
    for module in sorted(candidates):
        try:
            importlib.import_module(module)
            loaded += 1
        except Exception as e:
            log.error(f"Could not load strategy module {module}: {e}", exc_info=True)
            errors += 1

    log.info(
        "Strategy discovery complete: %d loaded, %d errors, %d registered",
        loaded,
        errors,
        len(STRATEGY_REGISTRY),
    )
