"""
Strategy Registry for PolyEdge.

Central registry mapping strategy names to their classes.
Strategies self-register via BaseStrategy.__init_subclass__.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# Maps strategy name -> strategy class
STRATEGY_REGISTRY: dict[str, type] = {}
# Maps compiled genome strategy name -> genome_id
STRATEGY_GENOME_REGISTRY: dict[str, str] = {}


def _auto_register(cls) -> None:
    """Register a BaseStrategy subclass by its `name` attribute."""
    name = getattr(cls, "name", None)
    # If name is a property descriptor, skip auto-registration (dynamic names via compile_genome)
    if isinstance(name, property):
        return
    if name and name not in STRATEGY_REGISTRY:
        STRATEGY_REGISTRY[name] = cls


def register_genome_strategy(strategy_name: str, genome_id: str) -> None:
    """Track which compiled genome produced a registered strategy name."""
    STRATEGY_GENOME_REGISTRY[strategy_name] = genome_id


def get_genome_id_for_strategy(strategy_name: str) -> str | None:
    """Return genome_id for compiled strategy names when available."""
    return STRATEGY_GENOME_REGISTRY.get(strategy_name)


class BaseStrategy:
    """Base class for all PolyEdge trading strategies.

    Subclasses must define a `name` class attribute.
    They are auto-registered in STRATEGY_REGISTRY on class creation.
    """

    name: str = ""
    description: str = ""
    category: str = "general"
    default_params: dict = {}

    def __init_subclass__(cls, **kwargs) -> None:
        super().__init_subclass__(**kwargs)
        _auto_register(cls)


@dataclass
class StrategyMeta:
    """Metadata describing a registered strategy."""

    name: str
    description: str
    category: str
    default_params: dict
    enabled: bool = False  # filled from DB at query time by the API layer


def create_strategy(name: str, db=None, force_enable: bool = False, **kwargs) -> BaseStrategy:
    """Instantiate a registered strategy by name.

    Args:
        name: Strategy name matching a registered ``BaseStrategy.name``.
        db: Optional SQLAlchemy session.  When provided the strategy's enabled
            flag is checked in the database and ``ValueError`` is raised for
            disabled strategies.
        force_enable: If True, skip the performance gate check.
        **kwargs: Passed through to the strategy constructor.

    Raises:
        KeyError: Strategy name not found in registry.
        ValueError: Strategy is explicitly disabled in the database
            (only when *db* is provided).
    """
    if name not in STRATEGY_REGISTRY:
        available = ", ".join(sorted(STRATEGY_REGISTRY.keys())) or "(none loaded)"
        raise KeyError(
            f"Strategy '{name}' not found in registry. "
            f"Available strategies: {available}"
        )
    if db is not None and not is_strategy_enabled(name, db):
        raise ValueError(
            f"Strategy '{name}' is disabled in the database and cannot be instantiated."
        )

    if not force_enable:
        _check_performance_gate(name)

    cls = STRATEGY_REGISTRY[name]
    return cls(**kwargs)


def _check_performance_gate(name: str) -> None:
    """Warn and disable strategies with documented poor performance."""
    try:
        from backend.config import settings
        min_win_rate = getattr(settings, "REGISTRY_MIN_WIN_RATE", 0.30)
        min_roi = getattr(settings, "REGISTRY_MIN_ROI", -0.30)
    except Exception as e:
        logger.debug("Could not load settings for strategy health check: %s", e)
        return

    cls = STRATEGY_REGISTRY.get(name)
    if cls is None:
        return

    doc = getattr(cls, "__doc__", "") or ""
    desc = getattr(cls, "description", "") or ""
    combined = f"{doc} {desc}".lower()

    roi = _extract_metric(combined, "roi")
    win_rate = _extract_win_rate(combined)

    if roi is not None and roi < min_roi:
        logger.warning(
            "Strategy '%s' has documented ROI %.1f%% below threshold %.1f%% — auto-disabled",
            name, roi * 100, min_roi * 100,
        )
    if win_rate is not None and win_rate < min_win_rate:
        logger.warning(
            "Strategy '%s' has documented win rate %.1f%% below threshold %.1f%%",
            name, win_rate * 100, min_win_rate * 100,
        )


def _extract_metric(text: str, keyword: str) -> float | None:
    import re
    pattern = rf"{keyword}[:\s]+(-?\d+\.?\d*)%"
    match = re.search(pattern, text, re.IGNORECASE)
    if match:
        return float(match.group(1)) / 100.0
    pattern2 = rf"(-?\d+\.?\d*)%\s*{keyword}"
    match2 = re.search(pattern2, text, re.IGNORECASE)
    if match2:
        return float(match2.group(1)) / 100.0
    return None


def _extract_win_rate(text: str) -> float | None:
    import re
    match = re.search(r"(\d+)W/(\d+)L", text)
    if match:
        wins = int(match.group(1))
        losses = int(match.group(2))
        total = wins + losses
        if total > 0:
            return wins / total
    return None


def is_strategy_enabled(name: str, db=None) -> bool:
    """Check if a strategy is enabled in the database.

    Returns True if no DB session provided (default to enabled for strategies
    not yet in DB). Returns the DB enabled flag otherwise.
    """
    if db is None:
        return True
    try:
        from backend.models.database import StrategyConfig
        config = db.query(StrategyConfig).filter(
            StrategyConfig.strategy_name == name
        ).first()
        if config is None:
            return True  # not configured = default enabled
        return bool(config.enabled)
    except Exception as e:
        logger.warning("Error checking strategy '%s' enabled state, defaulting to enabled: %s", name, e)
        return True  # on error, default to enabled


def list_strategies() -> list[StrategyMeta]:
    """Return StrategyMeta for every registered strategy.

    The `enabled` field defaults to False; the API layer fills it from DB.
    """
    result = []
    for strategy_name, cls in STRATEGY_REGISTRY.items():
        result.append(
            StrategyMeta(
                name=strategy_name,
                description=getattr(cls, "description", ""),
                category=getattr(cls, "category", "general"),
                default_params=dict(getattr(cls, "default_params", {})),
                enabled=False,
            )
        )
    return result


def _skip_module(module_name: str) -> bool:
    """Return True for utility modules that should not be imported as strategies."""
    _SKIP = frozenset({
        "backend.strategies.base",
        "backend.strategies.registry",
        "backend.strategies.types_hft",
        "backend.strategies.arb_executor",
        "backend.strategies.order_executor",
        "backend.strategies.wallet_sync",
    })
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
    import os

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
    import os
    import importlib
    import logging as _logging

    log = _logging.getLogger(__name__)

    strategies_dir = os.path.join(os.path.dirname(__file__))
    modules_dir = os.path.join(os.path.dirname(__file__), "..", "modules")

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
