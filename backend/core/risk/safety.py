"""DEPRECATED: Use backend.core.safety instead.

Safety monitoring and risk management for AGI components.

This module will be removed in a future release.
"""



from datetime import datetime, timezone
import json
import math
import os
from typing import Any, Dict, Optional, Tuple

from loguru import logger

from backend.models.database import BotState, SessionLocal, StrategyConfig, Trade


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
            "max_position_size": float(
                os.environ.get("SAFETY_MAX_POSITION_SIZE", "0.1")
            ),
            "max_daily_loss": float(os.environ.get("SAFETY_MAX_DAILY_LOSS", "0.05")),
            "min_confidence": float(os.environ.get("SAFETY_MIN_CONFIDENCE", "0.6")),
        }
        logger.bind(task="safety").info(
            "Using fallback safety thresholds from env vars"
        )

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
            return (
                False,
                f"Position size {suggested_size} exceeds max {self._thresholds['max_position_size']}",
            )

        if confidence < self._thresholds.get("min_confidence", 0.6):
            return (
                False,
                f"Confidence {confidence} below min {self._thresholds['min_confidence']}",
            )

        return True, "Trade approved by safety monitor"

    def get_risk_tier(self, strategy_key: str) -> str:
        """Get risk tier from StrategyConfig, or compute from strategy metrics."""
        try:
            with SessionLocal() as db:
                config = (
                    db.query(StrategyConfig)
                    .filter(StrategyConfig.strategy_name == strategy_key)
                    .first()
                )
                if config and config.risk_tier:
                    return config.risk_tier
        except Exception:
            logger.bind(task="safety", strategy=strategy_key).exception(
                "Failed to read risk tier from DB"
            )

        # Compute tier from strategy metrics
        computed = self._compute_risk_tier(strategy_key)
        # Persist the computed tier for next time
        self.set_risk_tier(strategy_key, computed)
        return computed

    def _compute_risk_tier(self, strategy_key: str) -> str:
        """Compute risk tier from settled trade metrics: win rate, Sharpe, max drawdown."""
        try:
            with SessionLocal() as db:
                settled_trades = (
                    db.query(Trade.pnl, Trade.size)
                    .filter(
                        Trade.strategy == strategy_key,
                        Trade.settled.is_(True),
                        Trade.pnl.isnot(None),
                    )
                    .all()
                )

            if len(settled_trades) < 5:
                return "moderate"

            pnls = [float(t.pnl) for t in settled_trades if t.pnl is not None]
            wins = sum(1 for p in pnls if p > 0)
            win_rate = wins / len(pnls) if pnls else 0.0

            # Sharpe ratio (annualized from per-trade returns)
            mean_pnl = sum(pnls) / len(pnls)
            variance = sum((p - mean_pnl) ** 2 for p in pnls) / len(pnls)
            std_pnl = math.sqrt(variance) if variance > 0 else 0.0
            sharpe = (mean_pnl / std_pnl * math.sqrt(252)) if std_pnl > 0 else 0.0

            # Max drawdown: largest peak-to-trough decline in cumulative PnL
            cumulative = 0.0
            peak = 0.0
            max_dd = 0.0
            for p in pnls:
                cumulative += p
                if cumulative > peak:
                    peak = cumulative
                dd = peak - cumulative
                if dd > max_dd:
                    max_dd = dd

            # Map metrics to tier
            # Conservative: high win rate, positive Sharpe, low drawdown
            # Aggressive: lower win rate or higher drawdown
            score = 0.0
            # Win rate contribution (0-40 points)
            if win_rate >= 0.65:
                score += 40
            elif win_rate >= 0.55:
                score += 30
            elif win_rate >= 0.45:
                score += 20
            elif win_rate >= 0.35:
                score += 10

            # Sharpe contribution (0-30 points)
            if sharpe >= 2.0:
                score += 30
            elif sharpe >= 1.0:
                score += 20
            elif sharpe >= 0.5:
                score += 10

            # Drawdown contribution (0-30 points, inverse - lower DD is better)
            avg_size = (
                sum(float(t.size or 0) for t in settled_trades) / len(settled_trades)
                if settled_trades
                else 1.0
            )
            dd_ratio = max_dd / (avg_size * len(pnls)) if avg_size > 0 and pnls else 0.0
            if dd_ratio <= 0.05:
                score += 30
            elif dd_ratio <= 0.10:
                score += 20
            elif dd_ratio <= 0.20:
                score += 10

            # Score to tier mapping
            if score >= 80:
                return "safe"
            elif score >= 60:
                return "conservative"
            elif score >= 40:
                return "moderate"
            elif score >= 20:
                return "aggressive"
            else:
                return "crazy"

        except Exception:
            logger.bind(task="safety", strategy=strategy_key).exception(
                "Failed to compute risk tier"
            )
            return "moderate"

    def set_risk_tier(self, strategy_key: str, tier: str) -> None:
        """Persist risk tier to StrategyConfig DB table."""
        valid_tiers = ("safe", "conservative", "moderate", "aggressive", "crazy")
        if tier not in valid_tiers:
            logger.bind(task="safety", strategy=strategy_key).warning(
                "Invalid risk tier '{}', must be one of {}", tier, valid_tiers
            )
            return
        try:
            with SessionLocal() as db:
                config = (
                    db.query(StrategyConfig)
                    .filter(StrategyConfig.strategy_name == strategy_key)
                    .first()
                )
                if config:
                    config.risk_tier = tier
                else:
                    config = StrategyConfig(
                        strategy_name=strategy_key, risk_tier=tier, enabled=False
                    )
                    db.add(config)
                db.commit()
                logger.bind(task="safety", strategy=strategy_key).info(
                    "Persisted risk tier to {}", tier
                )
        except Exception:
            logger.bind(task="safety", strategy=strategy_key).exception(
                "Failed to persist risk tier"
            )

    def record_alert(
        self, severity: str, message: str, strategy_key: Optional[str] = None
    ) -> None:
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
                    logger.exception(
                        "safety: failed to parse bot_state.misc_data as JSON"
                    )

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

    def record_alert(
        self, severity: str, message: str, strategy_key: Optional[str] = None
    ) -> None:
        self._risk_monitor.record_alert(severity, message, strategy_key)

    def get_risk_tier(self, strategy_key: str) -> str:
        return self._risk_monitor.get_risk_tier(strategy_key)

    def set_risk_tier(self, strategy_key: str, tier: str) -> None:
        self._risk_monitor.set_risk_tier(strategy_key, tier)


safety_monitor = SafetyMonitor()
