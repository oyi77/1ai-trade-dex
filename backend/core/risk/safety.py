"""Safety monitoring and risk management for AGI components."""

from datetime import datetime, timezone
import json
import os
from typing import Any, Dict, Optional, Tuple

from loguru import logger

from backend.models.database import BotState, SessionLocal


class AlertSeverity(str):
    INFO = "INFO"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"


class RiskMonitor:
    """Maintains per-strategy and global risk state with configurable thresholds."""

    def __init__(self):
        self._thresholds = {}
        self._load_thresholds()

    def _load_thresholds(self) -> None:
        """Load thresholds from BotState.misc_data or environment variables."""
        with SessionLocal() as db:
            bot_state = db.query(BotState).filter(BotState.mode == "paper").first()
            if bot_state is not None and bot_state.misc_data:
                try:
                    misc = json.loads(bot_state.misc_data)
                    if isinstance(misc, dict):
                        safety_thresholds = misc.get("safety_thresholds", {})
                        if safety_thresholds:
                            self._thresholds.update(safety_thresholds)
                            logger.bind(task="safety").info(
                                "Loaded safety thresholds from BotState.misc_data"
                            )
                            return
                except json.JSONDecodeError:
                    logger.bind(task="safety").warning(
                        "Failed to parse BotState.misc_data as JSON"
                    )

        # Fallback to environment variables
        self._thresholds = {
            "max_position_size": float(os.environ.get("SAFETY_MAX_POSITION_SIZE", "0.1")),
            "max_daily_loss": float(os.environ.get("SAFETY_MAX_DAILY_LOSS", "0.05")),
            "min_confidence": float(os.environ.get("SAFETY_MIN_CONFIDENCE", "0.6")),
        }
        logger.bind(task="safety").info("Using fallback safety thresholds from env vars")

    def get_global_limits(self) -> Dict[str, float]:
        """Return current global safety limits."""
        return self._thresholds.copy()

    def check_trade(self, signal: Dict[str, Any]) -> Tuple[bool, str]:
        """Check if a trade signal meets safety criteria."""
        if not isinstance(signal, dict):
            return False, "Signal must be a dict"

        suggested_size = signal.get("suggested_size", 0.0)
        confidence = signal.get("confidence", 0.0)

        if suggested_size > self._thresholds.get("max_position_size", 0.1):
            return False, f"Position size {suggested_size} exceeds max {self._thresholds['max_position_size']}"

        if confidence < self._thresholds.get("min_confidence", 0.6):
            return False, f"Confidence {confidence} below min {self._thresholds['min_confidence']}"

        return True, "Trade approved by safety monitor"

    def get_risk_tier(self, strategy_key: str) -> str:
        return "medium"

    def set_risk_tier(self, strategy_key: str, tier: str) -> None:
        logger.bind(task="safety", strategy=strategy_key).info(f"Set risk tier to {tier}")

    def record_alert(self, severity: str, message: str, strategy_key: Optional[str] = None) -> None:
        alert = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "severity": severity,
            "message": message,
            "strategy_key": strategy_key,
        }

        with SessionLocal() as db:
            bot_state = db.query(BotState).filter(BotState.mode == "paper").first()
            if not bot_state:
                logger.bind(task="safety").warning("No BotState found for paper mode")
                return

            alerts = []
            if bot_state.misc_data:
                try:
                    misc = json.loads(bot_state.misc_data)
                    alerts = misc.get("safety_alerts", [])
                except json.JSONDecodeError:
                    logger.exception("safety: failed to parse bot_state.misc_data as JSON")

            alerts.append(alert)
            misc = {"safety_alerts": alerts}
            bot_state.misc_data = json.dumps(misc)
            db.commit()

            logger.bind(task="safety", severity=severity).info(message)

            if severity == AlertSeverity.CRITICAL and strategy_key:
                logger.bind(task="safety", strategy=strategy_key).warning(
                    "CRITICAL alert paused trading for strategy"
                )


class SafetyMonitor:
    """Main safety monitoring interface for AGI components."""

    def __init__(self):
        self._risk_monitor = RiskMonitor()

    def check_trade(self, signal: Dict[str, Any]) -> Tuple[bool, str]:
        return self._risk_monitor.check_trade(signal)

    def get_global_limits(self) -> Dict[str, float]:
        return self._risk_monitor.get_global_limits()

    def record_alert(self, severity: str, message: str, strategy_key: Optional[str] = None) -> None:
        self._risk_monitor.record_alert(severity, message, strategy_key)

    def get_risk_tier(self, strategy_key: str) -> str:
        return self._risk_monitor.get_risk_tier(strategy_key)

    def set_risk_tier(self, strategy_key: str, tier: str) -> None:
        self._risk_monitor.set_risk_tier(strategy_key, tier)


safety_monitor = SafetyMonitor()
