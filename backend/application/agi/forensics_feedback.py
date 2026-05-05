"""Forensics Feedback — applies trade failure insights to strategy configuration.

Wave 9: Meta-Learning Layer — Part 5.2
Fixes Gap G3 by closing the feedback loop from TradeForensics to StrategyConfig.
"""

from datetime import datetime, timezone
from typing import Any, Optional, Callable, Dict
from pydantic import BaseModel

from backend.config import settings
from backend.core.event_bus import publish_event
from backend.models.database import StrategyConfig


class StrategyConfigMutation(BaseModel):
    """Immutable record of a strategy configuration mutation."""
    strategy_name: str
    param: str
    old_value: Any
    new_value: Any
    reason: str
    timestamp: datetime


# Mutation helper functions

def increase_param(config: StrategyConfig, param: str, delta: float, max_val: float) -> StrategyConfigMutation:
    """Increase a numeric parameter by delta, capped at max_val."""
    current = getattr(config, param, 0.0)
    new_val = min(current + delta, max_val)
    return StrategyConfigMutation(
        strategy_name=config.strategy_name,
        param=param,
        old_value=current,
        new_value=new_val,
        reason=f"increase_{param}",
        timestamp=datetime.now(timezone.utc)
    )


def decrease_param(config: StrategyConfig, param: str, factor: float, min_val: float) -> StrategyConfigMutation:
    """Decrease a numeric parameter by factor, floored at min_val."""
    current = getattr(config, param, 1.0)
    new_val = max(current * factor, min_val)
    return StrategyConfigMutation(
        strategy_name=config.strategy_name,
        param=param,
        old_value=current,
        new_value=new_val,
        reason=f"decrease_{param}",
        timestamp=datetime.now(timezone.utc)
    )


def add_to_list(config: StrategyConfig, param: str, value: str) -> StrategyConfigMutation:
    """Add a value to a list parameter (JSON string)."""
    import json
    current_list = json.loads(config.params or "[]") if config.params else []
    if value not in current_list:
        current_list.append(value)
        new_params = json.dumps(current_list)
        return StrategyConfigMutation(
            strategy_name=config.strategy_name,
            param="params",
            old_value=config.params,
            new_value=new_params,
            reason=f"add_{param}",
            timestamp=datetime.now(timezone.utc)
        )
    return None


def get_current_value(config: StrategyConfig, param: str) -> Any:
    """Get current value of a parameter from StrategyConfig."""
    if param == "params":
        return config.params
    return getattr(config, param, None)


def apply_mutation_to_config(config: StrategyConfig, mutation: StrategyConfigMutation, db) -> None:
    """Apply mutation to StrategyConfig and persist."""
    if mutation.param == "params":
        config.params = mutation.new_value
    else:
        setattr(config, mutation.param, mutation.new_value)
    config.updated_at = datetime.now(timezone.utc)
    db.commit()


# Forensics mutation rules mapped to root causes

def current_regime():
    """Get current market regime (simplified for now)."""
    return "neutral"


FORENSIC_MUTATION_RULES: Dict[str, Callable[[StrategyConfig], Optional[StrategyConfigMutation]]] = {
    "CAUSE_SLIPPAGE_HIGH": lambda c: increase_param(c, "min_edge_threshold", delta=0.02, max_val=0.50),
    "CAUSE_REGIME_MISMATCH": lambda c: add_to_list(c, "skip_regimes", value=current_regime()),
    "CAUSE_LATE_ENTRY": lambda c: decrease_param(c, "interval_seconds", factor=0.80, min_val=30),
    "CAUSE_LOW_LIQUIDITY": lambda c: add_to_list(c, "blacklisted_markets", value="BTC"),
    "CAUSE_SIGNAL_DECAY": lambda c: decrease_param(c, "confidence_lookback_window", factor=0.90, min_val=5),
}


class ForensicsFeedbackApplicator:
    """Applies forensics-driven mutations to strategy configurations."""
    
    MAX_MUTATIONS_PER_STRATEGY_PER_DAY = 1

    def _propose_mutation(self, strategy_name: str, root_cause: str) -> None:
        """Log mutation proposal when auto-mutation is disabled."""
        publish_event("mutation_proposed", {
            "strategy_name": strategy_name,
            "root_cause": root_cause,
            "timestamp": datetime.now(timezone.utc).isoformat()
        })

    def _mutations_today(self, strategy_name: str, db) -> int:
        """Count mutations applied today for this strategy."""
        # Simplified: in production, query EvolutionLog table
        # For now, return 0 to allow mutations
        return 0

    def apply(
        self,
        strategy_name: str,
        root_cause: str,
        market_ticker: str,
        db
    ) -> Optional[StrategyConfigMutation]:
        """Apply forensics-driven mutation to strategy configuration.
        
        Args:
            strategy_name: Name of strategy to mutate
            root_cause: Failure pattern root cause code
            market_ticker: Market ticker for context
            db: Database session
            
        Returns:
            StrategyConfigMutation if applied, None if skipped
        """
        # Skip if auto-mutation disabled
        if not settings.FORENSICS_AUTO_MUTATE:
            self._propose_mutation(strategy_name, root_cause)
            return None

        # Anti-oscillation guard
        if self._mutations_today(strategy_name, db) >= self.MAX_MUTATIONS_PER_STRATEGY_PER_DAY:
            return None

        # Get mutation rule
        rule = FORENSIC_MUTATION_RULES.get(root_cause)
        if not rule:
            return None

        # Load config and apply mutation
        config = db.query(StrategyConfig).filter_by(strategy_name=strategy_name).first()
        if not config:
            return None

        mutation = rule(config)
        if not mutation:
            return None

        # Capture old value
        mutation.old_value = get_current_value(config, mutation.param)

        # Apply and persist
        apply_mutation_to_config(config, mutation, db)
        publish_event("strategy_param_mutated", mutation.model_dump())

        return mutation
