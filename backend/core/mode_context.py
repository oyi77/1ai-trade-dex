"""Mode execution context — encapsulates per-mode state for independent trading contexts.

Provides a dataclass to hold CLOB client, risk manager, and strategy configs
for each trading mode (paper, testnet, live). Enables isolated execution contexts
without circular imports or global state pollution.
"""

from dataclasses import dataclass, field
from typing import Dict

from backend.data.polymarket_clob import PolymarketCLOB
from backend.core.risk_manager import RiskManager
from backend.models.database import StrategyConfig


@dataclass
class ModeExecutionContext:
    """Encapsulates per-mode state for independent trading execution.

    Holds the CLOB client, risk manager, and strategy configurations
    for a specific trading mode (paper, testnet, or live). Enables
    isolated execution contexts without global state coupling.

    Attributes:
        mode: Trading mode identifier ("paper", "testnet", or "live").
        clob_client: Polymarket CLOB client for order placement/cancellation.
        risk_manager: Risk validator for trade proposals.
        strategy_configs: Dict mapping strategy name to StrategyConfig ORM model.
    """

    mode: str
    clob_client: PolymarketCLOB
    risk_manager: RiskManager
    strategy_configs: Dict[str, StrategyConfig] = field(default_factory=dict)


# Module-level storage for execution contexts
_contexts: Dict[str, ModeExecutionContext] = {}


def get_context(mode: str) -> ModeExecutionContext:
    """Retrieve execution context for a given mode.

    Args:
        mode: Trading mode identifier ("paper", "testnet", or "live").

    Returns:
        ModeExecutionContext for the requested mode.

    Raises:
        KeyError: If mode context has not been registered.
    """
    if mode not in _contexts:
        raise KeyError(f"No execution context registered for mode: {mode} (available: {list(_contexts.keys())})")
    return _contexts[mode]


def register_context(mode: str, context: ModeExecutionContext) -> None:
    """Register an execution context for a given mode.

    Args:
        mode: Trading mode identifier.
        context: ModeExecutionContext instance to register.
    """
    _contexts[mode] = context


def list_contexts() -> Dict[str, ModeExecutionContext]:
    """List all registered execution contexts.

    Returns:
        Dict mapping mode names to ModeExecutionContext instances.
    """
    return _contexts.copy()
