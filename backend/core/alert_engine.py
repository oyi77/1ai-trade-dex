"""
Alert engine for PolyEdge.

Evaluates market events against user-defined alert rules and fires
notifications when conditions are met, respecting per-rule cooldowns.
"""
import time
from dataclasses import dataclass
from enum import Enum
from typing import Optional

from loguru import logger
class AlertCondition(str, Enum):
    PRICE_ABOVE = "price_above"
    PRICE_BELOW = "price_below"
    WHALE_TRADE = "whale_trade"
    DRAWDOWN = "drawdown"
    VOLUME_SPIKE = "volume_spike"


@dataclass
class AlertRule:
    id: str
    name: str
    condition: AlertCondition
    threshold: float
    market_ticker: Optional[str] = None  # None = applies to all
    channel: str = "telegram"
    enabled: bool = True
    triggered_count: int = 0
    cooldown_seconds: int = 300  # don't re-trigger within 5 min
    last_triggered: Optional[float] = None


class AlertEngine:
    """Evaluates alert rules against incoming market events."""

    def __init__(self) -> None:
        self._rules: dict[str, AlertRule] = {}

    def add_rule(self, rule: AlertRule) -> None:
        """Register or replace an alert rule."""
        self._rules[rule.id] = rule

    def remove_rule(self, rule_id: str) -> None:
        """Remove an alert rule by ID (no-op if not found)."""
        self._rules.pop(rule_id, None)

    def evaluate(self, event_type: str, data: dict) -> list[AlertRule]:
        """
        Check all enabled rules against data.

        Returns the list of rules that fired (cooldown respected and
        rule state updated in-place).
        """
        triggered: list[AlertRule] = []
        now = time.monotonic()

        for rule in self._rules.values():
            if not rule.enabled:
                continue
            # Cooldown guard
            if rule.last_triggered is not None:
                elapsed = now - rule.last_triggered
                if elapsed < rule.cooldown_seconds:
                    continue
            # Ticker filter
            ticker = data.get("market_ticker") or data.get("ticker")
            if rule.market_ticker is not None and ticker != rule.market_ticker:
                continue

            if self._check_condition(rule, data):
                rule.triggered_count += 1
                rule.last_triggered = now
                triggered.append(rule)
                logger.info(
                    "Alert rule '%s' triggered (count=%d)",
                    rule.name,
                    rule.triggered_count,
                )

        return triggered

    def _check_condition(self, rule: AlertRule, data: dict) -> bool:
        """Evaluate a single rule against event data."""
        condition = rule.condition

        if condition == AlertCondition.PRICE_ABOVE:
            price = data.get("price")
            return price is not None and price > rule.threshold

        if condition == AlertCondition.PRICE_BELOW:
            price = data.get("price")
            return price is not None and price < rule.threshold

        if condition == AlertCondition.WHALE_TRADE:
            amount = data.get("amount") or data.get("size") or 0.0
            return float(amount) >= rule.threshold

        if condition == AlertCondition.DRAWDOWN:
            drawdown = data.get("drawdown") or data.get("drawdown_pct") or 0.0
            return float(drawdown) >= rule.threshold

        if condition == AlertCondition.VOLUME_SPIKE:
            volume = data.get("volume") or data.get("volume_24h") or 0.0
            return float(volume) >= rule.threshold

        logger.warning("Unknown alert condition: %s", condition)
        return False
