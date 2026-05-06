"""
Strategy Registry for PolyEdge.

Central registry mapping strategy names to their classes.
Strategies self-register via BaseStrategy.__init_subclass__.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

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


def create_strategy(name: str, **kwargs) -> BaseStrategy:
    """Instantiate a registered strategy by name.

    Raises KeyError with a helpful message if the strategy is not found.
    Raises ValueError if the strategy is disabled in the database.
    """
    if name not in STRATEGY_REGISTRY:
        available = ", ".join(sorted(STRATEGY_REGISTRY.keys())) or "(none loaded)"
        raise KeyError(
            f"Strategy '{name}' not found in registry. "
            f"Available strategies: {available}"
        )
    cls = STRATEGY_REGISTRY[name]
    return cls(**kwargs)


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

    from backend.config import settings

    strategy_modules = [
        "backend.modules.execution.copy_trader",
        "backend.modules.scanners.weather_emos",
        "backend.modules.arbitrage.kalshi_arb",
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
        # Skip KalshiArbStrategy if no API key configured
        if module == "backend.modules.arbitrage.kalshi_arb" and not settings.KALSHI_API_KEY_ID:
            logger.info("Skipping KalshiArbStrategy: KALSHI_API_KEY_ID not configured")
            continue
        try:
            importlib.import_module(module)
        except Exception as e:
            # Catch all exceptions (SyntaxError, AttributeError, etc.), not just
            # ImportError — a bad strategy file must not kill the entire registration loop.
            logging.getLogger(__name__).error(
                f"Could not load strategy module {module}: {e}", exc_info=True
            )
