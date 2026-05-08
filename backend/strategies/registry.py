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


def _auto_register(cls) -> None:
    """Register a BaseStrategy subclass by its `name` attribute."""
    name = getattr(cls, "name", None)
    if name and name not in STRATEGY_REGISTRY:
        STRATEGY_REGISTRY[name] = cls


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
    except Exception:
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
    except Exception:
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


def load_all_strategies() -> None:
    """Import all strategy modules to trigger auto-registration."""
    import importlib

    strategy_modules = [
        "backend.modules.execution.copy_trader",
        "backend.modules.scanners.weather_emos",
        "backend.strategies.btc_oracle",
        "backend.strategies.btc_momentum",
        "backend.strategies.cex_pm_leadlag",
        "backend.strategies.realtime_scanner",
        "backend.modules.data_feeds.whale_pnl_tracker",
        "backend.strategies.market_maker",
        "backend.strategies.bond_scanner",
        "backend.strategies.general_market_scanner",
        "backend.strategies.line_movement_detector",
        "backend.strategies.universal_scanner",
        "backend.strategies.probability_arb",
        "backend.strategies.cross_market_arb",
        "backend.modules.data_feeds.whale_frontrun",
        "backend.strategies.agi_meta_strategy",
        "backend.strategies.types_hft",
    ]
    for module in strategy_modules:
        try:
            importlib.import_module(module)
        except Exception as e:
            # Catch all exceptions (SyntaxError, AttributeError, etc.), not just
            # ImportError — a bad strategy file must not kill the entire registration loop.
            logging.getLogger(__name__).error(
                f"Could not load strategy module {module}: {e}", exc_info=True
            )
